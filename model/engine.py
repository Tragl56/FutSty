"""
engine.py — Motor Estatístico Avançado

Implementa:
  - Modelo de Poisson bivariado para previsão de placares
  - Correção Dixon-Coles para baixa contagem de gols (0-0, 0-1, 1-0, 1-1)
  - xPoints (pontos esperados por partida)
  - Simulação Monte Carlo para validação cruzada
  - Rating ELO simples para força dinâmica dos times

Médias de referência — Brasileirão Série A (histórico 2019-2024):
  Mandante: 1.50 gols/jogo  |  Visitante: 1.15 gols/jogo
"""

import numpy as np
from scipy.stats import poisson
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional
from collections import Counter

# ──────────────────────────────────────────
# Constantes calibradas para o Brasileirão
# ──────────────────────────────────────────
LEAGUE_HOME_AVG: float = 1.50
LEAGUE_AWAY_AVG: float = 1.15
MAX_GOALS: int = 8          # matriz 9×9 cobre >99% dos resultados reais
DRAW_CORRECTION: float = 1.10  # Poisson subestima empates no futebol

# Parâmetro Dixon-Coles ρ — controla correlação nos placares baixos
# Valores maiores = mais empates 0-0 corrigidos. Calibrado para Brasil ≈ 0.12
RHO: float = 0.12


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


@dataclass
class MatchAnalysis:
    home_team: str
    away_team: str
    competition: str
    context: str

    # Lambdas
    lambda_home: float
    lambda_away: float

    # Probabilidades analíticas (Poisson)
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

    def summary(self) -> str:
        lines = [
            f"\n{'='*52}",
            f"  ⚽  {self.home_team}  ×  {self.away_team}",
            f"  {self.competition}  |  Contexto: {self.context}",
            f"{'='*52}",
            f"  Probabilidades (Poisson):",
            f"    {self.home_team:<22} {self.prob_home:.1%}",
            f"    {'Empate':<22} {self.prob_draw:.1%}",
            f"    {self.away_team:<22} {self.prob_away:.1%}",
            f"\n  Gols esperados (λ):",
            f"    {self.home_team}: {self.lambda_home:.2f}   |   {self.away_team}: {self.lambda_away:.2f}",
            f"    Total esperado: {self.total_goals_expected:.2f}",
            f"\n  Métricas extras:",
            f"    Ambos marcam (BTTS): {self.btts_prob:.1%}",
            f"    Over 2.5 gols:       {self.over_2_5_prob:.1%}",
            f"\n  Placares mais prováveis:",
        ]
        for s in self.top_scores[:6]:
            lines.append(f"    {s.label:<8}  {s.prob:.1%}")

        lines.append(f"\n  xPoints:  {self.home_team} {self.xpoints_home:.2f}  |  {self.away_team} {self.xpoints_away:.2f}")

        if self.mc_simulations > 0:
            lines += [
                f"\n  Monte Carlo ({self.mc_simulations:,} simulações):",
                f"    {self.home_team}: {self.mc_prob_home:.1%}  |  Empate: {self.mc_prob_draw:.1%}  |  {self.away_team}: {self.mc_prob_away:.1%}",
            ]

        lines.append(f"{'='*52}\n")
        return "\n".join(lines)


# ──────────────────────────────────────────
# Correção Dixon-Coles
# ──────────────────────────────────────────

def _dixon_coles_tau(home_goals: int, away_goals: int, lh: float, la: float, rho: float) -> float:
    """
    Fator de correção para placares 0-0, 1-0, 0-1, 1-1.
    Para outros placares, retorna 1.0 (sem ajuste).
    """
    if home_goals == 0 and away_goals == 0:
        return 1 - lh * la * rho
    elif home_goals == 0 and away_goals == 1:
        return 1 + lh * rho
    elif home_goals == 1 and away_goals == 0:
        return 1 + la * rho
    elif home_goals == 1 and away_goals == 1:
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
    home_boost: float = 1.15,
    context_factor: float = 1.0,
) -> Tuple[float, float]:
    """
    Calcula λ para mandante e visitante.

    λ_home = atk_home × def_away × HOME_AVG × home_boost × context
    λ_away = atk_away × def_home × AWAY_AVG × context

    Limita em 6.0 para evitar outliers em fallbacks extremos.
    """
    lh = atk_home * def_away * LEAGUE_HOME_AVG * home_boost * context_factor
    la = atk_away * def_home * LEAGUE_AWAY_AVG * context_factor
    return round(min(lh, 6.0), 3), round(min(la, 6.0), 3)


def construir_matriz(lh: float, la: float, usar_dixon_coles: bool = True) -> np.ndarray:
    """
    Constrói a matriz de probabilidades de placar com Poisson bivariado.
    Aplica correção Dixon-Coles nos placares baixos se ativado.
    """
    matriz = np.zeros((MAX_GOALS + 1, MAX_GOALS + 1))

    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            p = poisson.pmf(h, lh) * poisson.pmf(a, la)
            if usar_dixon_coles:
                p *= _dixon_coles_tau(h, a, lh, la, RHO)
            matriz[h][a] = p

    # Renormalizar após correção
    total = matriz.sum()
    if total > 0:
        matriz /= total

    return matriz


def extrair_probabilidades(matriz: np.ndarray) -> Tuple[float, float, float]:
    """
    Extrai P(home), P(draw), P(away) da matriz.
    Aplica leve correção de empate (Poisson sub-estima empates no futebol).
    """
    ph = float(np.sum(np.tril(matriz, -1)))
    pd = float(np.sum(np.diag(matriz))) * DRAW_CORRECTION
    pa = float(np.sum(np.triu(matriz, 1)))

    total = ph + pd + pa
    return ph / total, pd / total, pa / total


def extrair_top_scores(matriz: np.ndarray, n: int = 10) -> List[ScoreProbability]:
    """Retorna os N placares mais prováveis."""
    scores = []
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            scores.append(ScoreProbability(home=h, away=a, prob=float(matriz[h][a])))
    return sorted(scores, key=lambda x: x.prob, reverse=True)[:n]


def calcular_xpoints(ph: float, pd: float, pa: float) -> Tuple[float, float]:
    """xP = P(W)×3 + P(D)×1. Métrica moderna de performance esperada."""
    return round(ph * 3 + pd, 2), round(pa * 3 + pd, 2)


def calcular_btts(matriz: np.ndarray) -> float:
    """P(ambos marcam) = 1 - P(home=0) - P(away=0) + P(0×0)."""
    return float(1 - np.sum(matriz[0, :]) - np.sum(matriz[:, 0]) + matriz[0, 0])


def calcular_over25(matriz: np.ndarray) -> float:
    """P(total de gols > 2.5) = P(total >= 3)."""
    prob = 0.0
    for h in range(MAX_GOALS + 1):
        for a in range(MAX_GOALS + 1):
            if h + a >= 3:
                prob += matriz[h][a]
    return float(prob)


def monte_carlo(lh: float, la: float, n: int = 10_000) -> Dict:
    """
    Simulação Monte Carlo — valida o modelo analítico.
    Usa rng com seed fixo para reprodutibilidade.
    """
    rng = np.random.default_rng(seed=42)
    gh = rng.poisson(lh, n)
    ga = rng.poisson(la, n)

    wins_h = int(np.sum(gh > ga))
    draws   = int(np.sum(gh == ga))
    wins_a  = int(np.sum(gh < ga))

    counts = Counter(zip(gh.tolist(), ga.tolist()))
    top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:8]

    return {
        "simulacoes": n,
        "prob_home": wins_h / n,
        "prob_draw": draws  / n,
        "prob_away": wins_a / n,
        "top_scores": [
            ScoreProbability(home=s[0], away=s[1], prob=c / n)
            for s, c in top
        ],
    }


# ──────────────────────────────────────────
# Entrada pública
# ──────────────────────────────────────────

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
) -> MatchAnalysis:
    """
    Ponto de entrada principal.

    stats_home / stats_away devem conter:
      - forca_ataque    (float, normalizado pela média da liga)
      - fraqueza_defesa (float, normalizado pela média da liga)
      - home_boost      (float, vantagem de jogar em casa)
    """
    lh, la = calcular_lambda(
        atk_home=stats_home["forca_ataque"],
        def_home=stats_home["fraqueza_defesa"],
        atk_away=stats_away["forca_ataque"],
        def_away=stats_away["fraqueza_defesa"],
        home_boost=stats_home.get("home_boost", 1.15),
        context_factor=context_factor,
    )

    matriz = construir_matriz(lh, la, usar_dixon_coles=True)
    ph, pd, pa = extrair_probabilidades(matriz)
    top = extrair_top_scores(matriz)
    xp_h, xp_a = calcular_xpoints(ph, pd, pa)
    btts = calcular_btts(matriz)
    over25 = calcular_over25(matriz)

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
        mc = monte_carlo(lh, la, n=mc_simulations)
        analysis.mc_prob_home = round(mc["prob_home"], 4)
        analysis.mc_prob_draw = round(mc["prob_draw"], 4)
        analysis.mc_prob_away = round(mc["prob_away"], 4)
        analysis.mc_simulations = mc_simulations

    return analysis
