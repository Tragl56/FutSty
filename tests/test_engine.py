"""Testes do motor estatístico."""

from __future__ import annotations

import math

import numpy as np
import pytest

from model.data import FALLBACK_STATS
from model.engine import (
    DRAW_CORRECTION,
    MAX_GOALS,
    MAX_LAMBDA,
    MIN_LAMBDA,
    RHO,
    analisar_partida,
    calcular_btts,
    calcular_lambda,
    calcular_over,
    calcular_xpoints,
    construir_matriz,
    extrair_probabilidades,
    extrair_top_scores,
    monte_carlo,
    rho_efetivo,
    tamanho_matriz,
)


# ── Lambdas ────────────────────────────────

def test_lambda_vantagem_de_casa():
    """Times idênticos: o mandante tem λ maior por causa do home boost."""
    lh, la = calcular_lambda(1.0, 1.0, 1.0, 1.0)
    assert lh > la


def test_lambda_respeita_os_limites():
    lh, la = calcular_lambda(99.0, 99.0, 99.0, 99.0)
    assert lh == la == MAX_LAMBDA

    lh, la = calcular_lambda(0.0001, 0.0001, 0.0001, 0.0001)
    assert lh >= MIN_LAMBDA and la >= MIN_LAMBDA


def test_lambda_cresce_com_ataque():
    fraco, _ = calcular_lambda(0.8, 1.0, 1.0, 1.0)
    forte, _ = calcular_lambda(1.8, 1.0, 1.0, 1.0)
    assert forte > fraco


def test_context_factor_reduz_gols():
    normal = calcular_lambda(1.4, 0.9, 1.2, 1.0, context_factor=1.0)
    decisivo = calcular_lambda(1.4, 0.9, 1.2, 1.0, context_factor=0.90)
    assert decisivo[0] < normal[0]
    assert decisivo[1] < normal[1]


# ── Matriz ─────────────────────────────────

@pytest.mark.parametrize("lh,la", [(0.5, 0.5), (1.5, 1.15), (2.8, 1.9), (6.0, 6.0)])
def test_matriz_e_distribuicao_valida(lh, la):
    m = construir_matriz(lh, la)
    assert m.ndim == 2 and m.shape[0] == m.shape[1]
    assert (m >= 0).all(), "matriz não pode conter probabilidade negativa"
    assert math.isclose(m.sum(), 1.0, rel_tol=1e-9)


def test_dixon_coles_nao_gera_celula_negativa_com_lambda_alto():
    """
    Regressão: com ρ fixo e λ altos, τ(0,0) = 1 - λh·λa·ρ ficava negativo
    e P(0×0) virava um número negativo.
    """
    m = construir_matriz(5.0, 5.0, usar_dixon_coles=True)
    assert m[0, 0] >= 0.0
    assert (m >= 0).all()


def test_rho_efetivo_dentro_dos_limites_teoricos():
    for lh, la in [(0.5, 0.4), (1.5, 1.2), (4.0, 3.5), (6.0, 6.0)]:
        r = rho_efetivo(lh, la, RHO)
        assert r <= 1.0
        assert r <= 1.0 / (lh * la) + 1e-12
        assert 1 - lh * la * r >= -1e-12   # τ(0,0) não-negativo
        assert 1 - r >= 0                  # τ(1,1) não-negativo


def test_rho_efetivo_nao_altera_valor_ja_valido():
    assert rho_efetivo(1.5, 1.15, RHO) == pytest.approx(RHO)


def test_dixon_coles_sinal_de_rho_define_a_direcao():
    """
    Documenta o sinal de ρ, que é contraintuitivo.

    Com os τ do artigo original, ρ NEGATIVO infla 0-0 e 1-1 (o efeito que o
    README descreve) e ρ POSITIVO faz o contrário. O projeto usa ρ = +0.12.
    """
    sem = construir_matriz(1.5, 1.15, usar_dixon_coles=False, draw_correction=1.0)
    positivo = construir_matriz(1.5, 1.15, rho=0.12, draw_correction=1.0)
    negativo = construir_matriz(1.5, 1.15, rho=-0.12, draw_correction=1.0)

    # ρ < 0 infla os empates de placar baixo.
    assert negativo[0, 0] > sem[0, 0]
    assert negativo[1, 1] > sem[1, 1]
    assert negativo[1, 0] < sem[1, 0]

    # ρ > 0 inverte exatamente esse efeito.
    assert positivo[0, 0] < sem[0, 0]
    assert positivo[1, 1] < sem[1, 1]
    assert positivo[1, 0] > sem[1, 0]


def test_dixon_coles_preserva_a_normalizacao():
    for rho in (-0.12, 0.0, 0.12):
        assert construir_matriz(1.5, 1.15, rho=rho).sum() == pytest.approx(1.0)


def test_tamanho_matriz_cresce_com_lambda():
    assert tamanho_matriz(1.5, 1.15) == MAX_GOALS
    assert tamanho_matriz(6.0, 6.0) > MAX_GOALS


def test_matriz_cobre_quase_toda_a_massa_mesmo_com_lambda_alto():
    """A truncagem deve deixar de fora bem menos de 1% da probabilidade."""
    from scipy.stats import poisson

    n = tamanho_matriz(6.0, 6.0)
    perdido = 1 - poisson.cdf(n, 6.0)
    assert perdido < 0.01


# ── Probabilidades 1X2 ─────────────────────

def test_probabilidades_somam_um():
    m = construir_matriz(1.8, 1.2)
    ph, pd, pa = extrair_probabilidades(m)
    assert math.isclose(ph + pd + pa, 1.0, rel_tol=1e-9)
    assert all(0 <= p <= 1 for p in (ph, pd, pa))


def test_prob_empate_bate_com_a_diagonal_da_matriz():
    """
    Regressão: a correção de empates era aplicada só ao 1X2, então o
    heatmap e as barras de probabilidade descreviam distribuições
    diferentes. Agora a diagonal da matriz é a fonte única da verdade.
    """
    m = construir_matriz(1.7, 1.3)
    _, pd, _ = extrair_probabilidades(m)
    assert pd == pytest.approx(float(np.trace(m)), rel=1e-9)


def test_correcao_de_empate_aumenta_a_probabilidade_de_empate():
    sem = construir_matriz(1.5, 1.5, draw_correction=1.0)
    com = construir_matriz(1.5, 1.5, draw_correction=DRAW_CORRECTION)
    assert extrair_probabilidades(com)[1] > extrair_probabilidades(sem)[1]


def test_time_mais_forte_tem_mais_chance():
    m = construir_matriz(2.5, 0.7)
    ph, _, pa = extrair_probabilidades(m)
    assert ph > pa


def test_simetria_com_lambdas_iguais():
    m = construir_matriz(1.4, 1.4)
    ph, _, pa = extrair_probabilidades(m)
    assert ph == pytest.approx(pa, abs=1e-9)


def test_matriz_degenerada_nao_quebra():
    ph, pd, pa = extrair_probabilidades(np.zeros((3, 3)))
    assert math.isclose(ph + pd + pa, 1.0)


# ── Métricas derivadas ─────────────────────

def test_top_scores_ordenado_e_consistente():
    m = construir_matriz(1.6, 1.1)
    top = extrair_top_scores(m, n=10)
    assert len(top) == 10
    assert [s.prob for s in top] == sorted((s.prob for s in top), reverse=True)
    for s in top:
        assert s.prob == pytest.approx(m[s.home][s.away])
    assert top[0].label == f"{top[0].home}×{top[0].away}"


def test_top_scores_limita_ao_tamanho_da_matriz():
    m = construir_matriz(1.5, 1.2)
    assert len(extrair_top_scores(m, n=10_000)) == m.size


def test_btts_entre_zero_e_um_e_cresce_com_gols():
    baixo = calcular_btts(construir_matriz(0.6, 0.5))
    alto = calcular_btts(construir_matriz(2.6, 2.4))
    assert 0 <= baixo <= 1 and 0 <= alto <= 1
    assert alto > baixo


def test_over_e_monotonico_na_linha():
    m = construir_matriz(1.9, 1.4)
    assert calcular_over(m, 0.5) > calcular_over(m, 2.5) > calcular_over(m, 4.5)


def test_over25_igual_a_soma_direta_das_celulas():
    m = construir_matriz(1.7, 1.3)
    esperado = sum(
        m[h][a]
        for h in range(m.shape[0])
        for a in range(m.shape[1])
        if h + a >= 3
    )
    assert calcular_over(m, 2.5) == pytest.approx(esperado)


def test_xpoints_na_faixa_valida():
    xp_h, xp_a = calcular_xpoints(0.5, 0.25, 0.25)
    assert xp_h == pytest.approx(1.75)
    assert xp_a == pytest.approx(1.0)
    assert 0 <= xp_h <= 3 and 0 <= xp_a <= 3


# ── Monte Carlo ────────────────────────────

def test_monte_carlo_converge_para_o_modelo_analitico():
    """
    Regressão: o MC amostrava Poisson cru, ignorando Dixon-Coles e a
    correção de empates, o que gerava divergência sistemática nos empates.
    Amostrando a matriz corrigida, sobra só ruído de amostragem.
    """
    lh, la = 1.8, 1.2
    m = construir_matriz(lh, la)
    ph, pd, pa = extrair_probabilidades(m)
    mc = monte_carlo(lh, la, n=200_000, matriz=m, seed=7)

    assert mc["prob_home"] == pytest.approx(ph, abs=0.01)
    assert mc["prob_draw"] == pytest.approx(pd, abs=0.01)
    assert mc["prob_away"] == pytest.approx(pa, abs=0.01)


def test_monte_carlo_probabilidades_somam_um():
    mc = monte_carlo(1.5, 1.2, n=5_000)
    assert math.isclose(
        mc["prob_home"] + mc["prob_draw"] + mc["prob_away"], 1.0, rel_tol=1e-9
    )
    assert mc["simulacoes"] == 5_000


def test_monte_carlo_com_seed_e_reprodutivel():
    a = monte_carlo(1.5, 1.2, n=3_000, seed=123)
    b = monte_carlo(1.5, 1.2, n=3_000, seed=123)
    assert a["prob_home"] == b["prob_home"]


def test_monte_carlo_sem_seed_varia():
    amostras = {monte_carlo(1.5, 1.2, n=2_000, seed=None)["prob_home"] for _ in range(6)}
    assert len(amostras) > 1, "seed=None deveria produzir amostras diferentes"


def test_monte_carlo_rejeita_matriz_invalida():
    with pytest.raises(ValueError):
        monte_carlo(1.5, 1.2, n=100, matriz=np.zeros((3, 3)))


# ── Análise completa ───────────────────────

def test_analise_completa_e_coerente():
    r = analisar_partida(
        "Flamengo", "Palmeiras",
        FALLBACK_STATS["Flamengo"], FALLBACK_STATS["Palmeiras"],
        usar_monte_carlo=True, mc_simulations=20_000,
    )
    assert r.prob_home + r.prob_draw + r.prob_away == pytest.approx(1.0, abs=1e-3)
    assert r.total_goals_expected == pytest.approx(r.lambda_home + r.lambda_away, abs=0.01)
    assert r.mc_simulations == 20_000
    assert r.mc_max_divergencia < 2.0, "MC e Poisson devem descrever a mesma distribuição"
    assert len(r.top_scores) == 10
    assert r.summary()


def test_analise_sem_monte_carlo_nao_preenche_campos_mc():
    r = analisar_partida("A", "B", {}, {})
    assert r.mc_simulations == 0
    assert r.mc_prob_home is None
    assert r.mc_max_divergencia is None


def test_stats_incompletos_usam_padrao_em_vez_de_quebrar():
    """Antes levantava KeyError quando faltava 'forca_ataque'."""
    r = analisar_partida("A", "B", {}, {"forca_ataque": "texto ruim"})
    assert r.lambda_home > 0 and r.lambda_away > 0


def test_stats_com_valores_invalidos_sao_ignorados():
    for ruim in [0, -1, float("nan"), float("inf"), None]:
        r = analisar_partida("A", "B", {"forca_ataque": ruim}, {})
        assert MIN_LAMBDA <= r.lambda_home <= MAX_LAMBDA


def test_mandante_e_visitante_nao_sao_simetricos():
    ida = analisar_partida(
        "Flamengo", "Santos", FALLBACK_STATS["Flamengo"], FALLBACK_STATS["Santos"]
    )
    volta = analisar_partida(
        "Santos", "Flamengo", FALLBACK_STATS["Santos"], FALLBACK_STATS["Flamengo"]
    )
    assert ida.prob_home > volta.prob_away, "a vantagem de casa precisa aparecer"
