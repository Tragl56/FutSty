"""
data.py — Módulo de dados com suporte a múltiplas fontes.

Fontes (em ordem de prioridade):
  1. API Futebol (api-futebol.com.br) — dados BR nativos
  2. Football-Data.org (football-data.org) — dados globais com BSA
  3. Dados históricos locais calibrados (fallback sempre disponível)

Cache local em data/ com TTL configurável (CACHE_TTL_HOURS).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import time
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import (  # noqa: E402
    API_FUTEBOL_KEY,
    CACHE_TTL_HOURS,
    CAMPEONATO_ID_PADRAO,
    DATA_DIR,
    FOOTBALL_DATA_KEY,
    HTTP_RETRIES,
    HTTP_TIMEOUT,
    VERSION,
)

log = logging.getLogger(__name__)

CACHE_DIR = DATA_DIR

# ──────────────────────────────────────────
# Contextos de jogo
# ──────────────────────────────────────────
CONTEXT_FACTORS: Dict[str, float] = {
    "normal":           1.00,
    "classico":         0.95,   # Clássicos tendem a ser mais truncados
    "decisivo":         0.90,   # Jogos de mata-mata = mais cautelosos
    "rebaixamento":     0.87,   # Alta pressão = blocos baixos
    "titulo":           0.93,
    "copa_brasil":      0.92,
    "libertadores":     0.88,
}

CONTEXT_DESCRIPTIONS: Dict[str, str] = {
    "normal":           "Rodada regular do campeonato",
    "classico":         "Derby ou clássico estadual",
    "decisivo":         "Jogo eliminatório ou de decisão",
    "rebaixamento":     "Times na luta contra o rebaixamento",
    "titulo":           "Disputa direta pelo título",
    "copa_brasil":      "Copa do Brasil (ida ou volta)",
    "libertadores":     "Copa Libertadores",
}

# Estatísticas neutras usadas quando um time é desconhecido.
STATS_PADRAO: Dict[str, float] = {
    "forca_ataque": 1.0,
    "fraqueza_defesa": 1.0,
    "home_boost": 1.10,
    "elo": 1500,
}

# ──────────────────────────────────────────
# Dados históricos calibrados (Brasileirão Série A 2019-2024)
# forca_ataque:    gols_marcados/jogo ÷ média_liga (1.0 = médio)
# fraqueza_defesa: gols_sofridos/jogo ÷ média_liga (1.0 = médio)
# home_boost:      fator multiplicador de vantagem em casa
# elo:             rating de força relativa
# ──────────────────────────────────────────
FALLBACK_STATS: Dict[str, Dict] = {
    "Flamengo":       {"forca_ataque": 1.72, "fraqueza_defesa": 0.72, "home_boost": 1.18, "elo": 1820},
    "Palmeiras":      {"forca_ataque": 1.65, "fraqueza_defesa": 0.68, "home_boost": 1.15, "elo": 1810},
    "Atlético-MG":    {"forca_ataque": 1.58, "fraqueza_defesa": 0.75, "home_boost": 1.20, "elo": 1780},
    "Botafogo":       {"forca_ataque": 1.48, "fraqueza_defesa": 0.80, "home_boost": 1.12, "elo": 1740},
    "Bragantino":     {"forca_ataque": 1.42, "fraqueza_defesa": 0.85, "home_boost": 1.12, "elo": 1700},
    "Internacional":  {"forca_ataque": 1.42, "fraqueza_defesa": 0.88, "home_boost": 1.18, "elo": 1710},
    "São Paulo":      {"forca_ataque": 1.40, "fraqueza_defesa": 0.82, "home_boost": 1.12, "elo": 1705},
    "Grêmio":         {"forca_ataque": 1.38, "fraqueza_defesa": 0.85, "home_boost": 1.22, "elo": 1698},
    "Athletico-PR":   {"forca_ataque": 1.38, "fraqueza_defesa": 0.83, "home_boost": 1.25, "elo": 1695},
    "Corinthians":    {"forca_ataque": 1.35, "fraqueza_defesa": 0.90, "home_boost": 1.10, "elo": 1680},
    "Fortaleza":      {"forca_ataque": 1.35, "fraqueza_defesa": 0.85, "home_boost": 1.28, "elo": 1688},
    "Cruzeiro":       {"forca_ataque": 1.32, "fraqueza_defesa": 0.90, "home_boost": 1.15, "elo": 1665},
    "Fluminense":     {"forca_ataque": 1.30, "fraqueza_defesa": 0.88, "home_boost": 1.14, "elo": 1660},
    "Santos":         {"forca_ataque": 1.28, "fraqueza_defesa": 0.92, "home_boost": 1.10, "elo": 1640},
    "Bahia":          {"forca_ataque": 1.25, "fraqueza_defesa": 0.95, "home_boost": 1.18, "elo": 1630},
    "Vasco":          {"forca_ataque": 1.22, "fraqueza_defesa": 0.95, "home_boost": 1.08, "elo": 1620},
    "Ceará":          {"forca_ataque": 1.18, "fraqueza_defesa": 0.98, "home_boost": 1.20, "elo": 1600},
    "Goiás":          {"forca_ataque": 1.15, "fraqueza_defesa": 1.00, "home_boost": 1.10, "elo": 1590},
    "América-MG":     {"forca_ataque": 1.10, "fraqueza_defesa": 1.02, "home_boost": 1.12, "elo": 1575},
    "Sport":          {"forca_ataque": 1.12, "fraqueza_defesa": 1.05, "home_boost": 1.15, "elo": 1570},
    "Cuiabá":         {"forca_ataque": 1.05, "fraqueza_defesa": 1.08, "home_boost": 1.14, "elo": 1555},
    "Coritiba":       {"forca_ataque": 1.05, "fraqueza_defesa": 1.10, "home_boost": 1.12, "elo": 1550},
    "Juventude":      {"forca_ataque": 1.02, "fraqueza_defesa": 1.12, "home_boost": 1.16, "elo": 1545},
    "Avaí":           {"forca_ataque": 0.98, "fraqueza_defesa": 1.15, "home_boost": 1.18, "elo": 1535},
    "Chapecoense":    {"forca_ataque": 0.95, "fraqueza_defesa": 1.18, "home_boost": 1.12, "elo": 1520},
}

# Partidas de demonstração (usadas quando não há API configurada)
DEMO_MATCHES: List[Dict] = [
    {"home": "Flamengo",     "away": "Palmeiras",     "rodada": 1, "data": "2025-05-10"},
    {"home": "Grêmio",       "away": "Internacional", "rodada": 1, "data": "2025-05-10"},
    {"home": "São Paulo",    "away": "Corinthians",   "rodada": 1, "data": "2025-05-11"},
    {"home": "Atlético-MG",  "away": "Cruzeiro",      "rodada": 1, "data": "2025-05-11"},
    {"home": "Botafogo",     "away": "Fluminense",    "rodada": 1, "data": "2025-05-11"},
    {"home": "Fortaleza",    "away": "Bahia",         "rodada": 2, "data": "2025-05-17"},
    {"home": "Athletico-PR", "away": "Bragantino",    "rodada": 2, "data": "2025-05-17"},
    {"home": "Internacional", "away": "Santos",       "rodada": 2, "data": "2025-05-18"},
]


# ──────────────────────────────────────────
# Resolução de nomes de times
# ──────────────────────────────────────────
# As APIs externas devolvem nomes longos ("CR Flamengo", "Clube Atlético
# Mineiro") enquanto FALLBACK_STATS usa nomes curtos. Sem tradução, a busca
# exata falhava silenciosamente e o time caía em estatísticas neutras — ou
# seja, a fonte secundária de dados gerava previsões sem informação.

def normalizar_nome(nome: str) -> str:
    """'Atlético-MG ' → 'atleticomg'. Sem acento, caixa ou pontuação."""
    if not nome:
        return ""
    sem_acento = unicodedata.normalize("NFKD", str(nome))
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return "".join(c for c in sem_acento.lower() if c.isalnum())


# Variantes conhecidas devolvidas pelas APIs externas → nome canônico.
ALIASES_TIMES: Dict[str, str] = {
    "crflamengo": "Flamengo",
    "flamengorj": "Flamengo",
    "sepalmeiras": "Palmeiras",
    "palmeirassp": "Palmeiras",
    "clubeatleticomineiro": "Atlético-MG",
    "atleticomineiro": "Atlético-MG",
    "atletico mineiro": "Atlético-MG",
    "atleticomineiromg": "Atlético-MG",
    "galo": "Atlético-MG",
    "botafogofr": "Botafogo",
    "botafogorj": "Botafogo",
    "botafogodefutebolteregatas": "Botafogo",
    "rbbragantino": "Bragantino",
    "redbullbragantino": "Bragantino",
    "bragantinosp": "Bragantino",
    "scinternacional": "Internacional",
    "internacionalrs": "Internacional",
    "inter": "Internacional",
    "saopaulofc": "São Paulo",
    "saopaulosp": "São Paulo",
    "gremiofbpa": "Grêmio",
    "gremiors": "Grêmio",
    "gremiofootballportoalegrense": "Grêmio",
    "caparanaense": "Athletico-PR",
    "clubeatleticoparanaense": "Athletico-PR",
    "athleticoparanaense": "Athletico-PR",
    "atleticoparanaense": "Athletico-PR",
    "atleticopr": "Athletico-PR",
    "sccorinthianspaulista": "Corinthians",
    "corinthianssp": "Corinthians",
    "fortalezaec": "Fortaleza",
    "fortalezaesporteclube": "Fortaleza",
    "cruzeiroec": "Cruzeiro",
    "cruzeiromg": "Cruzeiro",
    "fluminensefc": "Fluminense",
    "fluminenserj": "Fluminense",
    "santosfc": "Santos",
    "santossp": "Santos",
    "ecbahia": "Bahia",
    "esporteclubebahia": "Bahia",
    "bahiaba": "Bahia",
    "crvascodagama": "Vasco",
    "vascodagama": "Vasco",
    "vascorj": "Vasco",
    "cearasc": "Ceará",
    "cearasportingclub": "Ceará",
    "goiasec": "Goiás",
    "goiasesporteclube": "Goiás",
    "americafc": "América-MG",
    "americamineiro": "América-MG",
    "americamg": "América-MG",
    "screcife": "Sport",
    "sportrecife": "Sport",
    "sportclubdorecife": "Sport",
    "sportpe": "Sport",
    "cuiabaec": "Cuiabá",
    "cuiabaesporteclube": "Cuiabá",
    "cuiabamt": "Cuiabá",
    "coritibafbc": "Coritiba",
    "coritibafootballclub": "Coritiba",
    "coritibapr": "Coritiba",
    "ecjuventude": "Juventude",
    "esporteclubejuventude": "Juventude",
    "juventuders": "Juventude",
    "avaifc": "Avaí",
    "avaisc": "Avaí",
    "associacaochapecoensedefutebol": "Chapecoense",
    "chapecoensesc": "Chapecoense",
    "chape": "Chapecoense",
}

# Tokens genéricos de clube descartados na busca aproximada.
_TOKENS_GENERICOS = {
    "fc", "ec", "sc", "cr", "se", "ac", "fr", "cf", "aa", "ca",
    "clube", "club", "esporte", "esportivo", "futebol", "sociedade",
    "associacao", "atletica", "regatas", "recreativo", "sporting",
}


def _construir_indice() -> Dict[str, str]:
    indice = {normalizar_nome(nome): nome for nome in FALLBACK_STATS}
    indice.update({normalizar_nome(k): v for k, v in ALIASES_TIMES.items()})
    return indice


_INDICE_TIMES = _construir_indice()


def resolver_time(nome: str) -> Optional[str]:
    """
    Traduz qualquer grafia para o nome canônico em FALLBACK_STATS.

    Aceita caixa e acento livres ('atletico-mg', 'ATLÉTICO MG'), nomes
    oficiais das APIs ('Clube Atlético Mineiro') e apelidos comuns.
    Devolve None quando o nome é desconhecido ou ambíguo.
    """
    if not nome:
        return None

    bruto = str(nome).strip()
    if bruto in FALLBACK_STATS:
        return bruto

    chave = normalizar_nome(bruto)
    if not chave:
        return None
    if chave in _INDICE_TIMES:
        return _INDICE_TIMES[chave]

    # Descarta tokens genéricos de clube ("EC Bahia" → "bahia").
    tokens = [
        normalizar_nome(t)
        for t in bruto.replace("-", " ").replace("/", " ").split()
    ]
    tokens = [t for t in tokens if t and t not in _TOKENS_GENERICOS]
    if tokens:
        chave_tokens = "".join(tokens)
        if chave_tokens in _INDICE_TIMES:
            return _INDICE_TIMES[chave_tokens]

    # Último recurso: contenção única (evita casar 'Atlético' com dois times).
    candidatos = {
        canonico
        for k, canonico in _INDICE_TIMES.items()
        if len(k) >= 4 and (k in chave or chave in k)
    }
    if len(candidatos) == 1:
        return candidatos.pop()

    return None


class DataFetcher:
    """
    Orquestrador de dados com fallback em 3 camadas:
      API Futebol → Football-Data.org → dados históricos locais
    """

    def __init__(
        self,
        api_futebol_key: Optional[str] = None,
        football_data_key: Optional[str] = None,
        cache_dir: Optional[Path] = None,
        cache_ttl_hours: Optional[float] = None,
    ):
        self.api_futebol_key = api_futebol_key or API_FUTEBOL_KEY
        self.football_data_key = football_data_key or FOOTBALL_DATA_KEY
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.cache_ttl_hours = (
            float(cache_ttl_hours) if cache_ttl_hours is not None else CACHE_TTL_HOURS
        )

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"FutebolElite/{VERSION}"})

        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ──────────────────────────────────────────
    # Cache helpers
    # ──────────────────────────────────────────

    def _cache_path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in key)
        # Sufixo estável evita colisão entre chaves que só diferem em
        # caracteres substituídos por '_' (ex.: 'Ceará' e 'Cearb'). Usa
        # hashlib porque hash() do Python é aleatorizado por processo e
        # faria o cache nunca acertar entre execuções.
        if safe != key:
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
            safe = f"{safe}_{digest}"
        return self.cache_dir / f"{safe[:120]}.json"

    def _read_cache(self, key: str) -> Optional[Dict]:
        p = self._cache_path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            ts = datetime.fromisoformat(data.get("_cached_at", "2000-01-01"))
            if datetime.now() - ts > timedelta(hours=self.cache_ttl_hours):
                return None
            return data
        except (OSError, ValueError, json.JSONDecodeError) as e:
            log.debug("Cache ilegível para %s: %s", key, e)
            return None

    def _write_cache(self, key: str, data: dict) -> None:
        """
        Grava o cache sem mutar o dicionário recebido e sem deixar arquivo
        pela metade caso o processo morra no meio da escrita.
        """
        payload = {**data, "_cached_at": datetime.now().isoformat()}
        destino = self._cache_path(key)
        temp = destino.with_suffix(".json.tmp")
        try:
            temp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            os.replace(temp, destino)
        except OSError as e:
            log.warning("Não foi possível gravar cache %s: %s", destino.name, e)
            temp.unlink(missing_ok=True)

    @staticmethod
    def _sem_metadados(data: Dict) -> Dict:
        return {k: v for k, v in data.items() if not k.startswith("_")}

    # ──────────────────────────────────────────
    # HTTP
    # ──────────────────────────────────────────

    def _get(self, url: str, headers: Dict[str, str], fonte: str) -> Optional[Dict]:
        """GET com retry exponencial curto. Devolve None em qualquer falha."""
        for tentativa in range(max(1, HTTP_RETRIES + 1)):
            try:
                r = self.session.get(url, headers=headers, timeout=HTTP_TIMEOUT)
                if r.status_code == 429:  # rate limit
                    espera = 2 ** tentativa
                    log.warning("[%s] rate limit; aguardando %ss", fonte, espera)
                    time.sleep(espera)
                    continue
                r.raise_for_status()
                return r.json()
            except (requests.RequestException, ValueError) as e:
                if tentativa == HTTP_RETRIES:
                    log.warning("[%s] falha em %s: %s", fonte, url, e)
                    return None
                time.sleep(2 ** tentativa)
        return None

    def _get_api_futebol(self, endpoint: str) -> Optional[Dict]:
        if not self.api_futebol_key:
            return None
        return self._get(
            f"https://api.api-futebol.com.br/v1{endpoint}",
            {"Authorization": f"Bearer {self.api_futebol_key}"},
            "API Futebol",
        )

    def _get_football_data(self, endpoint: str) -> Optional[Dict]:
        if not self.football_data_key:
            return None
        return self._get(
            f"https://api.football-data.org/v4{endpoint}",
            {"X-Auth-Token": self.football_data_key},
            "Football-Data",
        )

    # ──────────────────────────────────────────
    # Interface pública
    # ──────────────────────────────────────────

    def get_team_stats(self, team_name: str) -> Dict:
        """
        Retorna estatísticas normalizadas. Tenta cache → API → fallback local.

        Nomes são resolvidos de forma tolerante a acento, caixa e grafia
        das APIs; times realmente desconhecidos recebem STATS_PADRAO.
        """
        canonico = resolver_time(team_name) or str(team_name).strip()

        cache_key = f"stats_{canonico}"
        cached = self._read_cache(cache_key)
        if cached:
            return self._sem_metadados(cached)

        api_data = self._get_api_futebol(f"/times/{canonico}/estatisticas")
        if api_data:
            stats = self._normalizar_api_futebol(api_data)
            self._write_cache(cache_key, stats)
            return stats

        if canonico in FALLBACK_STATS:
            return dict(FALLBACK_STATS[canonico])

        log.info("Time desconhecido '%s' — usando estatísticas neutras.", team_name)
        return dict(STATS_PADRAO)

    def time_conhecido(self, team_name: str) -> bool:
        """True se o nome resolve para um time com dados calibrados."""
        return resolver_time(team_name) is not None

    def get_proximos_jogos(self, campeonato_id: int = CAMPEONATO_ID_PADRAO) -> List[Dict]:
        """Busca próximos jogos. Cache → API Futebol → Football-Data → demo."""
        cache_key = f"proximos_{campeonato_id}"
        cached = self._read_cache(cache_key)
        if cached and cached.get("jogos"):
            return cached["jogos"]

        data = self._get_api_futebol(f"/campeonatos/{campeonato_id}/rodadas")
        if data:
            jogos = self._extrair_proximos(data)
            if jogos:
                self._write_cache(cache_key, {"jogos": jogos})
                return jogos

        fd_data = self._get_football_data("/competitions/BSA/matches?status=SCHEDULED")
        if fd_data:
            jogos = self._extrair_fd_matches(fd_data)
            if jogos:
                self._write_cache(cache_key, {"jogos": jogos})
                return jogos

        log.info("Nenhuma fonte externa disponível — usando partidas de demonstração.")
        return [dict(j) for j in DEMO_MATCHES]

    def get_tabela(self, campeonato_id: int = CAMPEONATO_ID_PADRAO) -> List[Dict]:
        """Retorna classificação do campeonato (vazia sem API configurada)."""
        data = self._get_api_futebol(f"/campeonatos/{campeonato_id}/tabela")
        if data:
            return data.get("times", [])
        return []

    def listar_times(self) -> List[str]:
        return sorted(FALLBACK_STATS.keys())

    def get_time_stats_formatado(self, team_name: str) -> Dict:
        """Stats enriquecidos com metadados para exibição no dashboard."""
        canonico = resolver_time(team_name) or str(team_name).strip()
        stats = self.get_team_stats(canonico)

        fa = float(stats.get("forca_ataque", 1.0))
        if fa >= 1.60:
            nivel = "⭐⭐⭐⭐⭐ Elite"
        elif fa >= 1.40:
            nivel = "⭐⭐⭐⭐ Forte"
        elif fa >= 1.25:
            nivel = "⭐⭐⭐ Médio-Alto"
        elif fa >= 1.10:
            nivel = "⭐⭐ Médio"
        else:
            nivel = "⭐ Abaixo da Média"

        return {**stats, "nivel": nivel, "nome": canonico}

    # ──────────────────────────────────────────
    # Normalizadores
    # ──────────────────────────────────────────

    @staticmethod
    def _normalizar_api_futebol(data: Dict) -> Dict:
        """
        Converte contagens brutas em fatores normalizados pela média da liga.

        Ataque e defesa usam a **mesma** referência — a média de gols por time
        por jogo, (HOME_AVG + AWAY_AVG)/2. Normalizar ataque por HOME_AVG e
        defesa por AWAY_AVG colocaria os dois em escalas diferentes e
        incompatíveis com FALLBACK_STATS.
        """
        from model.engine import LEAGUE_AWAY_AVG, LEAGUE_HOME_AVG

        media_liga = (LEAGUE_HOME_AVG + LEAGUE_AWAY_AVG) / 2

        def _num(chave: str, padrao: float) -> float:
            try:
                return float(data.get(chave, padrao))
            except (TypeError, ValueError):
                return padrao

        jogos = max(_num("jogos", 1.0), 1.0)
        gols_m = max(_num("gols_marcados", media_liga), 0.0)
        gols_s = max(_num("gols_sofridos", media_liga), 0.0)

        return {
            "forca_ataque":    round(max((gols_m / jogos) / media_liga, 0.05), 3),
            "fraqueza_defesa": round(max((gols_s / jogos) / media_liga, 0.05), 3),
            "home_boost":      1.15,
            "elo":             1600,
            "jogos":           int(jogos),
        }

    @staticmethod
    def _extrair_proximos(data: Dict) -> List[Dict]:
        jogos = []
        for rodada in data.get("rodadas", []) or []:
            for jogo in rodada.get("partidas", []) or []:
                if jogo.get("status") not in ("agendado", "nao_iniciado"):
                    continue
                home = (jogo.get("time_mandante") or {}).get("nome_popular", "")
                away = (jogo.get("time_visitante") or {}).get("nome_popular", "")
                if not home or not away:
                    continue
                jogos.append({
                    "home":   resolver_time(home) or home,
                    "away":   resolver_time(away) or away,
                    "data":   jogo.get("data_realizacao", ""),
                    "rodada": rodada.get("rodada", 0),
                })
        return jogos

    @staticmethod
    def _extrair_fd_matches(data: Dict) -> List[Dict]:
        jogos = []
        for m in data.get("matches", []) or []:
            home = (m.get("homeTeam") or {}).get("name", "")
            away = (m.get("awayTeam") or {}).get("name", "")
            if not home or not away:
                continue
            jogos.append({
                "home":   resolver_time(home) or home,
                "away":   resolver_time(away) or away,
                "data":   (m.get("utcDate") or "")[:10],
                "rodada": m.get("matchday", 0),
            })
        return jogos
