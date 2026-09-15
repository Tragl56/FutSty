"""Testes da API REST."""

from __future__ import annotations

import pytest

from config import VERSION
from model.data import CONTEXT_FACTORS


# ── Health e metadados ─────────────────────

def test_health(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "online"
    assert body["versao"] == VERSION


def test_listar_times(client):
    body = client.get("/times").json()
    assert body["total"] == len(body["times"]) == 25
    assert "Flamengo" in body["times"]


def test_listar_contextos(client):
    contextos = client.get("/contextos").json()
    assert {c["id"] for c in contextos} == set(CONTEXT_FACTORS)
    assert all(c["descricao"] for c in contextos)


# ── Stats ──────────────────────────────────

def test_stats_de_time_conhecido(client):
    body = client.get("/stats/Flamengo").json()
    assert body["time"] == "Flamengo"
    assert body["stats"]["forca_ataque"] > 0


def test_stats_aceita_variantes_de_nome(client):
    assert client.get("/stats/cr flamengo").json()["time"] == "Flamengo"
    assert client.get("/stats/atletico-mg").json()["time"] == "Atlético-MG"


def test_stats_de_time_desconhecido_da_404(client):
    """
    Regressão: get_time_stats_formatado nunca devolvia vazio, então o 404
    era código morto e times inexistentes recebiam stats neutros calados.
    """
    r = client.get("/stats/Real Madrid")
    assert r.status_code == 404
    assert "não encontrado" in r.json()["detail"]


# ── Análise ────────────────────────────────

def test_analisar_partida(client):
    r = client.post("/analisar", json={
        "home_team": "Flamengo", "away_team": "Palmeiras",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["prob_home"] + body["prob_draw"] + body["prob_away"] == pytest.approx(1.0, abs=1e-3)
    assert 0 <= body["btts_prob"] <= 1
    assert 0 <= body["over_2_5_prob"] <= 1
    assert body["total_goals_expected"] == pytest.approx(
        body["lambda_home"] + body["lambda_away"], abs=0.01
    )
    assert len(body["top_scores"]) == 8
    assert body["top_scores"][0]["label"]
    assert body["mc_simulations"] == 0


def test_analisar_normaliza_o_nome_dos_times(client):
    body = client.post("/analisar", json={
        "home_team": "cr flamengo", "away_team": "SE Palmeiras",
    }).json()
    assert body["home_team"] == "Flamengo"
    assert body["away_team"] == "Palmeiras"


def test_analisar_com_monte_carlo(client):
    body = client.post("/analisar", json={
        "home_team": "Flamengo", "away_team": "Santos",
        "usar_monte_carlo": True, "mc_simulations": 20_000,
    }).json()
    assert body["mc_simulations"] == 20_000
    assert body["mc_prob_home"] == pytest.approx(body["prob_home"], abs=0.02)


def test_contexto_altera_os_gols_esperados(client):
    normal = client.post("/analisar", json={
        "home_team": "Flamengo", "away_team": "Santos", "context": "normal",
    }).json()
    decisivo = client.post("/analisar", json={
        "home_team": "Flamengo", "away_team": "Santos", "context": "decisivo",
    }).json()
    assert decisivo["total_goals_expected"] < normal["total_goals_expected"]


@pytest.mark.parametrize("payload,status", [
    ({"home_team": "Flamengo", "away_team": "Flamengo"}, 400),
    ({"home_team": "Real Madrid", "away_team": "Flamengo"}, 400),
    ({"home_team": "Flamengo", "away_team": "Real Madrid"}, 400),
    ({"home_team": "Flamengo", "away_team": "Santos", "context": "inexistente"}, 400),
    ({"home_team": "Flamengo"}, 422),
    ({"home_team": "", "away_team": "Santos"}, 422),
    ({"home_team": "Flamengo", "away_team": "Santos", "mc_simulations": 1}, 422),
    ({"home_team": "Flamengo", "away_team": "Santos", "mc_simulations": 10**9}, 422),
])
def test_payloads_invalidos(client, payload, status):
    assert client.post("/analisar", json=payload).status_code == status


def test_erro_de_validacao_nao_grava_no_historico(client):
    antes = client.get("/previsoes").json()["total"]
    client.post("/analisar", json={"home_team": "Flamengo", "away_team": "Flamengo"})
    assert client.get("/previsoes").json()["total"] == antes


# ── Rodada ─────────────────────────────────

def test_analisar_rodada(client):
    body = client.post("/analisar/rodada", json={}).json()
    assert body["partidas"] == len(body["resultados"]) > 0
    for r in body["resultados"]:
        assert r["prob_home"] + r["prob_draw"] + r["prob_away"] == pytest.approx(1.0, abs=1e-3)


def test_rodada_com_contexto_invalido_da_400(client):
    assert client.post("/analisar/rodada", json={"context": "xyz"}).status_code == 400


# ── Histórico ──────────────────────────────

def test_historico_persiste_a_analise(client):
    antes = client.get("/previsoes").json()["total"]
    client.post("/analisar", json={"home_team": "Grêmio", "away_team": "Internacional"})
    depois = client.get("/previsoes").json()
    assert depois["total"] == antes + 1
    assert depois["previsoes"][0]["time_casa"] == "Grêmio"
    assert depois["previsoes"][0]["resultado_previsto"] in ("casa", "empate", "fora")


def test_historico_filtra_por_time(client):
    client.post("/analisar", json={"home_team": "Cuiabá", "away_team": "Coritiba"})
    body = client.get("/previsoes?time=Cuiabá").json()
    assert body["total"] >= 1
    for p in body["previsoes"]:
        assert "Cuiabá" in (p["time_casa"], p["time_fora"])


def test_historico_filtra_por_nome_alternativo(client):
    client.post("/analisar", json={"home_team": "Vasco", "away_team": "Bahia"})
    assert client.get("/previsoes?time=CR Vasco da Gama").json()["total"] >= 1


def test_historico_pagina(client):
    for _ in range(3):
        client.post("/analisar", json={"home_team": "Santos", "away_team": "Bahia"})
    pagina1 = client.get("/previsoes?limit=2&offset=0").json()
    pagina2 = client.get("/previsoes?limit=2&offset=2").json()
    assert len(pagina1["previsoes"]) == 2
    ids1 = {p["id"] for p in pagina1["previsoes"]}
    ids2 = {p["id"] for p in pagina2["previsoes"]}
    assert not (ids1 & ids2), "páginas não podem repetir registros"


@pytest.mark.parametrize("query", ["limit=0", "limit=999", "offset=-1"])
def test_historico_rejeita_paginacao_invalida(client, query):
    assert client.get(f"/previsoes?{query}").status_code == 422


# ── Tabela ─────────────────────────────────

def test_tabela_sem_api_externa(client):
    body = client.get("/tabela/10").json()
    assert body["campeonato_id"] == 10
    assert body["tabela"] == []
