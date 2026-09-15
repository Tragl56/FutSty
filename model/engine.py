"""
engine.py — Motor Estatístico Avançado

Implementa:
  - Modelo de Poisson bivariado para previsão de placares
  - Correção Dixon-Coles para baixa contagem de gols (0-0, 0-1, 1-0, 1-1)
  - xPoints (pontos esperados por partida)
  - Simulação Monte Carlo para validação cruzada
  - Métricas de volume: BTTS e Over 2.5

Médias de referência — Brasileirão Série A (histórico 2019-2024):
  Mandante: 1.50 gols/jogo  |  Visitante: 1.15 gols/jogo

Garantia de consistência
------------------------
Todas as métricas publicadas (1X2, placares, BTTS, Over 2.5 e Monte Carlo)
derivam de **uma única** matriz de placares já corrigida e normalizada.
Isso evita o cenário em que o heatmap mostra uma distribuição e as barras de
probabilidade mostram outra.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.stats import poisson

# ──────────────────────────────────────────
# Constantes calibradas para o Brasileirão
# ──────────────────────────────────────────
LEAGUE_HOME_AVG: float = 1.50
LEAGUE_AWAY_AVG: float = 1.15

# Tamanho mínimo da matriz de placares (0..MAX_GOALS em cada eixo).
# Para λ típicos (~1.5) uma matriz 9×9 cobre >99.9% da massa de probabilidade;
# para λ altos o tamanho cresce automaticamente até MAX_GOALS_CAP.
MAX_GOALS: int = 8
MAX_GOALS_CAP: int = 15

# Poisson subestima empates no futebol. Aplicado à diagonal da matriz
# (e não só ao 1X2) para que todas as métricas fiquem coerentes entre si.
DRAW_CORRECTION: float = 1.10

# Parâmetro Dixon-Coles ρ — controla a correlação nos quatro placares baixos.
#
# ATENÇÃO AO SINAL. Com os τ do artigo original (ver _dixon_coles_tau):
#   ρ < 0  →  INFLA 0-0 e 1-1 e reduz 1-0 e 0-1. É o sinal que Dixon & Coles
#            (1997) estimaram para dados reais (ρ̂ ≈ -0.13) e o que corresponde
#            a "Poisson subestima placares baixos/empates".
#   ρ > 0  →  faz o CONTRÁRIO: reduz 0-0 e 1-1, aumenta 1-0 e 0-1.
#
# O valor abaixo é positivo, então hoje o modelo reduz 0-0 e 1-1 — efeito
# oposto ao descrito no README. Mantido como está para não alterar as
# previsões já calibradas; troque para -0.12 se a intenção era inflar
# empates de placar baixo.
RHO: float = 0.12

# Limites de segurança para λ. O teto evita outliers vindos de fallbacks
# extremos; o piso evita divisão por zero e matrizes degeneradas.
MIN_LAMBDA: float = 0.05
MAX_LAMBDA: float = 6.0

DEFAULT_HOME_BOOST: float = 1.15

# Seed padrão do Monte Carlo — resultados reprodutíveis.
# Passe ``mc_seed=None`` para amostragem verdadeiramente aleatória.
MC_SEED: int = 42


# ──────────────────────────────────────────
# Dataclasses de resultado
# ──────────────────────────────────────────

@dataclass
class ScoreProbability:
    home: int
    away: int
    prob: float

    @property
    def label(self) -> str:
        return f"{self.home}×{self.away}"

    def to_dict(self) -> Dict:
        return {"home": self.home, "away": self.away, "prob": self.prob, "label": self.label}


@dataclass
class MatchAnalysis:
    home_team: str
    away_team: str
    competition: str
    context: str

    # Lambdas
    lambda_home: float
    lambda_away: float

    # Probabilidades analíticas (Poisson + Dixon-Coles)
    prob_home: float
    prob_draw: float
    prob_away: float

    # Probabilidades Monte Carlo (opcional)
    mc_prob_home: Optional[float] = None
    mc_prob_draw: Optional[float] = None
    mc_prob_away: Optional[float] = None
    mc_simulations: int = 0

    # Placares mais prováveis
    top_scores: List[ScoreProbability] = field(default_factory=list)

    # Métricas adicionais
    xpoints_home: float = 0.0
    xpoints_away: float = 0.0
    total_goals_expected: float = 0.0
    btts_prob: float = 0.0   # Both Teams To Score
    over_2_5_prob: float = 0.0

    # Matriz completa (serializada como list para JSON)
    score_matrix: List[List[float]] = field(default_factory=list)

    @property
    def mc_max_divergencia(self) -> Optional[float]:
        """Maior divergência (em pontos percentuais) entre Poisson e Monte Carlo."""
        if self.mc_simulations <= 0 or self.mc_prob_home is None:
            return None
        return max(
            abs(self.prob_home - self.mc_prob_home),
            abs(self.prob_draw - self.mc_prob_draw),
            abs(self.prob_away - self.mc_prob_away),
        ) * 100

    def summary(self) -> str:
        lines = [
            f"\n{'='*52}",
            f"  ⚽  {self.home_team}  ×  {self.away_team}",
            f"  {self.competition}  |  Contexto: {self.context}",
            f"{'='*52}",
            "  Probabilidades (Poisson):",
            f"    {self.home_team:<22} {self.prob_home:.1%}",
            f"    {'Empate':<22} {self.prob_draw:.1%}",
            f"    {self.away_team:<22} {self.prob_away:.1%}",
            "\n  Gols esperados (λ):",
            f"    {self.home_team}: {self.lambda_home:.2f}   |   {self.away_team}: {self.lambda_away:.2f}",
            f"    Total esperado: {self.total_goals_expected:.2f}",
            "\n  Métricas extras:",
            f"    Ambos marcam (BTTS): {self.btts_prob:.1%}",
            f"    Over 2.5 gols:       {self.over_2_5_prob:.1%}",
            "\n  Placares mais prováveis:",
        ]
        for s in self.top_scores[:6]:
            lines.append(f"    {s.label:<8}  {s.prob:.1%}")

        lines.append(
            f"\n  xPoints:  {self.home_team} {self.xpoints_home:.2f}"
            f"  |  {self.away_team} {self.xpoints_away:.2f}"
        )

        if self.mc_simulations > 0:
            lines += [
                f"\n  Monte Carlo ({self.mc_simulations:,} simulações):",
                f"    {self.home_team}: {self.mc_prob_home:.1%}"
                f"  |  Empate: {self.mc_prob_draw:.1%}"
                f"  |  {self.away_team}: {self.mc_prob_away:.1%}",
                f"    Divergência máx. vs Poisson: {self.mc_max_divergencia:.1f}pp",
            ]

        lines.append(f"{'='*52}\n")
        return "\n".join(lines)


# ──────────────────────────────────────────
# Correção Dixon-Coles
# ──────────────────────────────────────────

def rho_efetivo(lh: float, la: float, rho: float = RHO) -> float:
    """
    Limita ρ à faixa em que a correção Dixon-Coles continua gerando
    probabilidades não-negativas (Dixon & Coles, 1997):

        max(-1/λh, -1/λa)  ≤  ρ  ≤  min(1, 1/(λh·λa))

    Sem esse limite, λ altos (ex.: 4.0 × 3.5 com ρ=0.12) tornam
    τ(0,0) = 1 - λh·λa·ρ negativo e a matriz ganha células negativas.
    """
    lh = max(float(lh), MIN_LAMBDA)
    la = max(float(la), MIN_LAMBDA)
    limite_sup = min(1.0, 1.0 / (lh * la))
    limite_inf = max(-1.0 / lh, -1.0 / la)
    return float(min(max(rho, limite_inf), limite_sup))


def _dixon_coles_tau(home_goals: int, away_goals: int, lh: float, la: float, rho: float) -> float:
    """
    Fator de correção para placares 0-0, 1-0, 0-1, 1-1.
    Para outros placares, retorna 1.0 (sem ajuste).
    """
    if home_goals == 0 and away_goals == 0:
        return 1 - lh * la * rho
    if home_goals == 0 and away_goals == 1:
        return 1 + lh * rho
    if home_goals == 1 and away_goals == 0:
        return 1 + la * rho
    if home_goals == 1 and away_goals == 1:
        return 1 - rho
    return 1.0


# ──────────────────────────────────────────
# Motor principal
# ──────────────────────────────────────────

def calcular_lambda(
    atk_home: float,
    def_home: float,
    atk_away: float,
    def_away: float,
    home_boost: float = DEFAULT_HOME_BOOST,
    context_factor: float = 1.0,
) -> Tuple[float, float]:
    """
    Calcula λ para mandante e visitante.

    λ_home = atk_home × def_away × HOME_AVG × home_boost × context
    λ_away = atk_away × def_home × AWAY_AVG × context

    Resultados são limitados a [MIN_LAMBDA, MAX_LAMBDA].
    """
    lh = atk_home * def_away * LEAGUE_HOME_AVG * home_boost * context_factor
    la = atk_away * def_home * LEAGUE_AWAY_AVG * context_factor
    lh = min(max(lh, MIN_LAMBDA), MAX_LAMBDA)
    la = min(max(la, MIN_LAMBDA), MAX_LAMBDA)
    return round(lh, 3), round(la, 3)


def tamanho_matriz(lh: float, la: float) -> int:
    """
    Escolhe o maior índice de gols da matriz.

    Usa μ + 5σ (σ = √μ para Poisson) para cobrir a cauda, com piso em
    MAX_GOALS e teto em MAX_GOALS_CAP. Para λ típicos do Brasileirão o
    resultado é exatamente MAX_GOALS.
    """
    mu = max(float(lh), float(la), MIN_LAMBDA)
    necessario = int(math.ceil(mu + 5.0 * math.sqrt(mu)))
    return int(min(MAX_GOALS_CAP, max(MAX_GOALS, necessario)))


def construir_matriz(
    lh: float,
    la: float,
    usar_dixon_coles: bool = True,
    rho: float = RHO,
    draw_correction: float = DRAW_CORRECTION,
    size: Optional[int] = None,
) -> np.ndarray:
    """
    Constrói a matriz de probabilidades de placar com Poisson bivariado.

    Ordem das operações:
      1. produto externo das pmfs de Poisson;
      2. correção Dixon-Coles nos quatro placares baixos (ρ limitado);
      3. correção de empates na diagonal;
      4. normalização única, para que ``matriz.sum() == 1``.

    A correção de empates é aplicada aqui (e não depois, só no 1X2) para que
    placares, BTTS, Over 2.5 e Monte Carlo descrevam a mesma distribuição.
    """
    lh = min(max(float(lh), MIN_LAMBDA), MAX_LAMBDA)
    la = min(max(float(la), MIN_LAMBDA), MAX_LAMBDA)

    n = int(size) if size is not None else tamanho_matriz(lh, la)
    gols = np.arange(n + 1)

    matriz = np.outer(poisson.pmf(gols, lh), poisson.pmf(gols, la))

    if usar_dixon_coles:
        r = rho_efetivo(lh, la, rho)
        matriz[0, 0] *= _dixon_coles_tau(0, 0, lh, la, r)
        matriz[0, 1] *= _dixon_coles_tau(0, 1, lh, la, r)
        matriz[1, 0] *= _dixon_coles_tau(1, 0, lh, la, r)
        matriz[1, 1] *= _dixon_coles_tau(1, 1, lh, la, r)

    if draw_correction != 1.0:
        np.fill_diagonal(matriz, np.diag(matriz) * draw_correction)

    # Blindagem: ρ já é limitado, mas erros de ponto flutuante podem deixar
    # um resíduo negativo minúsculo nas células corrigidas.
    np.clip(matriz, 0.0, None, out=matriz)

    total = matriz.sum()
    if total > 0:
        matriz /= total

    return matriz


def extrair_probabilidades(matriz: np.ndarray) -> Tuple[float, float, float]:
    """
    Extrai P(home), P(draw), P(away) marginalizando a matriz.

    Matriz[h][a] = P(mandante marca h, visitante marca a), portanto:
      - triângulo inferior (h > a) → vitória do mandante
      - diagonal (h == a)          → empate
      - triângulo superior (h < a) → vitória do visitante

    A correção de empates já foi aplicada em ``construir_matriz``; aqui a
    função apenas soma, sem reponderar nada.
    """
    m = np.asarray(matriz, dtype=float)
    ph = float(np.tril(m, -1).sum())
    pd = float(np.trace(m))
    pa = float(np.triu(m, 1).sum())

    total = ph + pd + pa
    if total <= 0:
        return 1 / 3, 1 / 3, 1 / 3
    return ph / total, pd / total, pa / total


def extrair_top_scores(matriz: np.ndarray, n: int = 10) -> List[ScoreProbability]:
    """Retorna os N placares mais prováveis, do mais para o menos provável."""
    m = np.asarray(matriz, dtype=float)
    n = max(1, min(int(n), m.size))

    flat = m.ravel()
    # argpartition acha os N maiores em O(size); depois ordena só esses N.
    candidatos = np.argpartition(flat, -n)[-n:]
    candidatos = candidatos[np.argsort(flat[candidatos])[::-1]]

    casa, fora = np.divmod(candidatos, m.shape[1])
    return [
        ScoreProbability(home=int(h), away=int(a), prob=float(flat[i]))
        for h, a, i in zip(casa, fora, candidatos)
    ]


def calcular_xpoints(ph: float, pd: float, pa: float) -> Tuple[float, float]:
    """xP = P(W)×3 + P(D)×1. Métrica moderna de performance esperada."""
    return round(ph * 3 + pd, 2), round(pa * 3 + pd, 2)


def calcular_btts(matriz: np.ndarray) -> float:
    """P(ambos marcam) = 1 - P(home=0) - P(away=0) + P(0×0)."""
    m = np.asarray(matriz, dtype=float)
    prob = 1.0 - float(m[0, :].sum()) - float(m[:, 0].sum()) + float(m[0, 0])
    return float(min(max(prob, 0.0), 1.0))


def calcular_over(matriz: np.ndarray, linha: float = 2.5) -> float:
    """P(total de gols > ``linha``). Com linha=2.5 equivale a P(total ≥ 3)."""
    m = np.asarray(matriz, dtype=float)
    totais = np.add.outer(np.arange(m.shape[0]), np.arange(m.shape[1]))
    prob = float(m[totais > linha].sum())
    return float(min(max(prob, 0.0), 1.0))


def calcular_over25(matriz: np.ndarray) -> float:
    """P(total de gols > 2.5). Mantido por compatibilidade."""
    return calcular_over(matriz, 2.5)


def monte_carlo(
    lh: float,
    la: float,
    n: int = 10_000,
    matriz: Optional[np.ndarray] = None,
    seed: Optional[int] = MC_SEED,
) -> Dict:
    """
    Simulação Monte Carlo — valida a agregação do modelo analítico.

    Amostra placares **da matriz corrigida** (Dixon-Coles + empates), e não de
    duas Poisson independentes. Amostrar Poisson cru compararia dois modelos
    diferentes e produziria uma divergência sistemática nos empates que nada
    tem a ver com erro numérico. Com a amostragem correta, a divergência que
    sobra é apenas ruído de amostragem (~1/√n).

    ``seed=None`` gera amostras diferentes a cada chamada.
    """
    n = max(1, int(n))
    if matriz is None:
        matriz = construir_matriz(lh, la)

    m = np.asarray(matriz, dtype=float)
    flat = m.ravel()
    soma = flat.sum()
    if soma <= 0:
        raise ValueError("Matriz de placares inválida: soma de probabilidades zero.")
    flat = flat / soma

    rng = np.random.default_rng(seed)
    indices = rng.choice(flat.size, size=n, p=flat)
    gh, ga = np.divmod(indices, m.shape[1])

    wins_h = int(np.count_nonzero(gh > ga))
    draws = int(np.count_nonzero(gh == ga))
    wins_a = n - wins_h - draws

    unicos, contagens = np.unique(indices, return_counts=True)
    ordem = np.argsort(contagens)[::-1][:8]
    top_h, top_a = np.divmod(unicos[ordem], m.shape[1])

    return {
        "simulacoes": n,
        "prob_home": wins_h / n,
        "prob_draw": draws / n,
        "prob_away": wins_a / n,
        "top_scores": [
            ScoreProbability(home=int(h), away=int(a), prob=int(c) / n)
            for h, a, c in zip(top_h, top_a, contagens[ordem])
        ],
    }


# ──────────────────────────────────────────
# Entrada pública
# ──────────────────────────────────────────

def _stat(stats: Dict, chave: str, padrao: float) -> float:
    """Lê um fator estatístico, tolerando chave ausente ou valor inválido."""
    try:
        valor = float(stats.get(chave, padrao))
    except (TypeError, ValueError):
        return padrao
    if not math.isfinite(valor) or valor <= 0:
        return padrao
    return valor


def analisar_partida(
    home_team: str,
    away_team: str,
    stats_home: Dict,
    stats_away: Dict,
    competition: str = "Brasileirão Série A",
    context: str = "normal",
    context_factor: float = 1.0,
    usar_monte_carlo: bool = False,
    mc_simulations: int = 10_000,
    mc_seed: Optional[int] = MC_SEED,
) -> MatchAnalysis:
    """
    Ponto de entrada principal.

    stats_home / stats_away podem conter:
      - forca_ataque    (float, normalizado pela média da liga; padrão 1.0)
      - fraqueza_defesa (float, normalizado pela média da liga; padrão 1.0)
      - home_boost      (float, vantagem de jogar em casa; padrão 1.15)

    Chaves ausentes ou inválidas caem no padrão em vez de levantar KeyError.
    """
    lh, la = calcular_lambda(
        atk_home=_stat(stats_home, "forca_ataque", 1.0),
        def_home=_stat(stats_home, "fraqueza_defesa", 1.0),
        atk_away=_stat(stats_away, "forca_ataque", 1.0),
        def_away=_stat(stats_away, "fraqueza_defesa", 1.0),
        home_boost=_stat(stats_home, "home_boost", DEFAULT_HOME_BOOST),
        context_factor=float(context_factor),
    )

    matriz = construir_matriz(lh, la, usar_dixon_coles=True)
    ph, pd, pa = extrair_probabilidades(matriz)
    top = extrair_top_scores(matriz)
    xp_h, xp_a = calcular_xpoints(ph, pd, pa)
    btts = calcular_btts(matriz)
    over25 = calcular_over(matriz, 2.5)

    analysis = MatchAnalysis(
        home_team=home_team,
        away_team=away_team,
        competition=competition,
        context=context,
        lambda_home=lh,
        lambda_away=la,
        prob_home=round(ph, 4),
        prob_draw=round(pd, 4),
        prob_away=round(pa, 4),
        top_scores=top,
        xpoints_home=xp_h,
        xpoints_away=xp_a,
        total_goals_expected=round(lh + la, 2),
        btts_prob=round(btts, 4),
        over_2_5_prob=round(over25, 4),
        score_matrix=matriz.tolist(),
    )

    if usar_monte_carlo:
        mc = monte_carlo(lh, la, n=mc_simulations, matriz=matriz, seed=mc_seed)
        analysis.mc_prob_home = round(mc["prob_home"], 4)
        analysis.mc_prob_draw = round(mc["prob_draw"], 4)
        analysis.mc_prob_away = round(mc["prob_away"], 4)
        analysis.mc_simulations = mc["simulacoes"]

    return analysis
