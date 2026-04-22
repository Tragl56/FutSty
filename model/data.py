"""
data.py — Módulo de dados com suporte a múltiplas fontes.

Fontes (em ordem de prioridade):
  1. API Futebol (api-futebol.com.br) — dados BR nativos
  2. Football-Data.org (football-data.org) — dados globais com BSA
  3. Dados históricos locais calibrados (fallback sempre disponível)

Cache local em data/ com TTL configurável.
"""

import json
import os
import time
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List

CACHE_DIR = Path(__file__).parent.parent / "data"
CACHE_TTL_HOURS = 6   # Mais agressivo que o proj2 (era 24h)

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

# ──────────────────────────────────────────
# Dados históricos calibrados (Brasileirão Série A 2019-2024)
# forca_ataque:    gols_marcados/jogo ÷ média_liga (1.0 = médio)
# fraqueza_defesa: gols_sofridos/jogo ÷ média_liga (1.0 = médio)
# home_boost:      fator multiplicador de vantagem em casa
# forma:           últimos 5 jogos (W/D/L) — para contexto futuro
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
    {"home": "Flamengo",    "away": "Palmeiras",     "rodada": 1, "data": "2025-05-10"},
    {"home": "Grêmio",      "away": "Internacional",  "rodada": 1, "data": "2025-05-10"},
    {"home": "São Paulo",   "away": "Corinthians",   "rodada": 1, "data": "2025-05-11"},
    {"home": "Atlético-MG", "away": "Cruzeiro",      "rodada": 1, "data": "2025-05-11"},
    {"home": "Botafogo",    "away": "Fluminense",    "rodada": 1, "data": "2025-05-11"},
    {"home": "Fortaleza",   "away": "Bahia",         "rodada": 2, "data": "2025-05-17"},
    {"home": "Athletico-PR","away": "Bragantino",    "rodada": 2, "data": "2025-05-17"},
    {"home": "Internacional","away": "Santos",        "rodada": 2, "data": "2025-05-18"},
]


class DataFetcher:
    """
    Orquestrador de dados com fallback em 3 camadas:
      API Futebol → Football-Data.org → dados históricos locais
    """

    def __init__(
        self,
        api_futebol_key: Optional[str] = None,
        football_data_key: Optional[str] = None,
    ):
        self.api_futebol_key   = api_futebol_key   or os.getenv("API_FUTEBOL_KEY")
        self.football_data_key = football_data_key or os.getenv("FOOTBALL_DATA_KEY")

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "FutebolElite/1.0"})

        CACHE_DIR.mkdir(exist_ok=True)

    # ──────────────────────────────────────────
    # Cache helpers
    # ──────────────────────────────────────────

    def _cache_path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in key)
        return CACHE_DIR / f"{safe}.json"

    def _read_cache(self, key: str) -> Optional[Dict]:
        p = self._cache_path(key)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            ts = datetime.fromisoformat(data.get("_cached_at", "2000-01-01"))
            if datetime.now() - ts > timedelta(hours=CACHE_TTL_HOURS):
                return None
            return data
        except Exception:
            return None

    def _write_cache(self, key: str, data: dict):
        data["_cached_at"] = datetime.now().isoformat()
        self._cache_path(key).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ──────────────────────────────────────────
    # API Futebol (api-futebol.com.br)
    # ──────────────────────────────────────────

    def _get_api_futebol(self, endpoint: str) -> Optional[Dict]:
        if not self.api_futebol_key:
            return None
        url = f"https://api.api-futebol.com.br/v1{endpoint}"
        try:
            r = self.session.get(
                url,
                headers={"Authorization": f"Bearer {self.api_futebol_key}"},
                timeout=10,
            )
            r.raise_for_status()
            time.sleep(0.3)
            return r.json()
        except Exception as e:
            print(f"[API Futebol] Erro em {endpoint}: {e}")
            return None

    # ──────────────────────────────────────────
    # Football-Data.org (fallback secundário)
    # ──────────────────────────────────────────

    def _get_football_data(self, endpoint: str) -> Optional[Dict]:
        if not self.football_data_key:
            return None
        url = f"https://api.football-data.org/v4{endpoint}"
        try:
            r = self.session.get(
                url,
                headers={"X-Auth-Token": self.football_data_key},
                timeout=10,
            )
            r.raise_for_status()
            time.sleep(0.3)
            return r.json()
        except Exception as e:
            print(f"[Football-Data] Erro em {endpoint}: {e}")
            return None

    # ──────────────────────────────────────────
    # Interface pública
    # ──────────────────────────────────────────

    def get_team_stats(self, team_name: str) -> Dict:
        """Retorna estatísticas normalizadas. Tenta API → cache → fallback."""
        cache_key = f"stats_{team_name}"
        cached = self._read_cache(cache_key)
        if cached:
            return {k: v for k, v in cached.items() if not k.startswith("_")}

        # Tenta API Futebol
        api_data = self._get_api_futebol(f"/times/{team_name}/estatisticas")
        if api_data:
            stats = self._normalizar_api_futebol(api_data)
            self._write_cache(cache_key, stats)
            return stats

        # Fallback Football-Data.org — necessita mapeamento de nome
        # (omitido por ora; adicionar mapeamento team_name → id quando necessário)

        # Fallback local calibrado
        return FALLBACK_STATS.get(team_name, {
            "forca_ataque": 1.0,
            "fraqueza_defesa": 1.0,
            "home_boost": 1.10,
            "elo": 1500,
        })

    def get_proximos_jogos(self, campeonato_id: int = 10) -> List[Dict]:
        """Busca próximos jogos. API → cache → demo."""
        cache_key = f"proximos_{campeonato_id}"
        cached = self._read_cache(cache_key)
        if cached:
            return cached.get("jogos", [])

        data = self._get_api_futebol(f"/campeonatos/{campeonato_id}/rodadas")
        if data:
            jogos = self._extrair_proximos(data)
            self._write_cache(cache_key, {"jogos": jogos})
            return jogos

        # Fallback Football-Data
        fd_data = self._get_football_data("/competitions/BSA/matches?status=SCHEDULED")
        if fd_data:
            jogos = self._extrair_fd_matches(fd_data)
            self._write_cache(cache_key, {"jogos": jogos})
            return jogos

        return DEMO_MATCHES

    def get_tabela(self, campeonato_id: int = 10) -> List[Dict]:
        """Retorna classificação do campeonato."""
        data = self._get_api_futebol(f"/campeonatos/{campeonato_id}/tabela")
        if data:
            return data.get("times", [])
        return []

    def get_historico_confrontos(self, home: str, away: str) -> List[Dict]:
        """Head-to-head dos últimos confrontos (via Football-Data quando disponível)."""
        # Retorna lista vazia quando sem API — pode ser expandido
        return []

    def listar_times(self) -> List[str]:
        return sorted(FALLBACK_STATS.keys())

    def get_time_stats_formatado(self, team_name: str) -> Dict:
        """Stats enriquecidos com metadados para exibição no dashboard."""
        stats = self.get_team_stats(team_name)
        elo = stats.get("elo", 1500)

        # Classificação qualitativa baseada em força de ataque
        fa = stats["forca_ataque"]
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

        return {**stats, "nivel": nivel, "nome": team_name}

    # ──────────────────────────────────────────
    # Normalizadores
    # ──────────────────────────────────────────

    @staticmethod
    def _normalizar_api_futebol(data: Dict) -> Dict:
        from model.engine import LEAGUE_HOME_AVG, LEAGUE_AWAY_AVG
        gols_m = data.get("gols_marcados", 1)
        gols_s = data.get("gols_sofridos", 1)
        jogos  = max(data.get("jogos", 1), 1)
        return {
            "forca_ataque":    round((gols_m / jogos) / LEAGUE_HOME_AVG, 3),
            "fraqueza_defesa": round((gols_s / jogos) / LEAGUE_AWAY_AVG, 3),
            "home_boost":      1.15,
            "elo":             1600,
            "jogos":           jogos,
        }

    @staticmethod
    def _extrair_proximos(data: Dict) -> List[Dict]:
        jogos = []
        for rodada in data.get("rodadas", []):
            for jogo in rodada.get("partidas", []):
                if jogo.get("status") in ("agendado", "nao_iniciado"):
                    jogos.append({
                        "home":   jogo.get("time_mandante", {}).get("nome_popular", ""),
                        "away":   jogo.get("time_visitante", {}).get("nome_popular", ""),
                        "data":   jogo.get("data_realizacao", ""),
                        "rodada": rodada.get("rodada", 0),
                    })
        return jogos

    @staticmethod
    def _extrair_fd_matches(data: Dict) -> List[Dict]:
        jogos = []
        for m in data.get("matches", []):
            jogos.append({
                "home":   m.get("homeTeam", {}).get("name", ""),
                "away":   m.get("awayTeam", {}).get("name", ""),
                "data":   m.get("utcDate", "")[:10],
                "rodada": m.get("matchday", 0),
            })
        return jogos
