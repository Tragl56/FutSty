"""Testes da camada de dados: resolução de nomes, cache e normalização."""

from __future__ import annotations

import pytest

from model.data import (
    CONTEXT_DESCRIPTIONS,
    CONTEXT_FACTORS,
    DEMO_MATCHES,
    FALLBACK_STATS,
    STATS_PADRAO,
    DataFetcher,
    normalizar_nome,
    resolver_time,
)


# ── Resolução de nomes ─────────────────────

@pytest.mark.parametrize("entrada,esperado", [
    ("Flamengo", "Flamengo"),
    ("flamengo", "Flamengo"),
    ("  FLAMENGO  ", "Flamengo"),
    ("CR Flamengo", "Flamengo"),
    ("Atlético-MG", "Atlético-MG"),
    ("atletico-mg", "Atlético-MG"),
    ("Atletico MG", "Atlético-MG"),
    ("Clube Atlético Mineiro", "Atlético-MG"),
    ("SE Palmeiras", "Palmeiras"),
    ("Grêmio FBPA", "Grêmio"),
    ("gremio", "Grêmio"),
    ("São Paulo FC", "São Paulo"),
    ("sao paulo", "São Paulo"),
    ("RB Bragantino", "Bragantino"),
    ("CR Vasco da Gama", "Vasco"),
    ("América FC", "América-MG"),
    ("SC Recife", "Sport"),
    ("EC Bahia", "Bahia"),
    ("Avaí FC", "Avaí"),
    ("Ceará SC", "Ceará"),
])
def test_resolver_time_aceita_variantes(entrada, esperado):
    assert resolver_time(entrada) == esperado


def test_atletico_e_athletico_nao_se_confundem():
    """
    'Atlético-PR' é o nome antigo do Athletico-PR; 'Atlético Mineiro' é
    outro clube. Os dois precisam cair no time certo.
    """
    assert resolver_time("Atlético-PR") == "Athletico-PR"
    assert resolver_time("Athletico Paranaense") == "Athletico-PR"
    assert resolver_time("Atlético Mineiro") == "Atlético-MG"


@pytest.mark.parametrize("entrada", ["", "   ", None, "Real Madrid", "Atlético", "xyz123"])
def test_resolver_time_rejeita_desconhecido_ou_ambiguo(entrada):
    assert resolver_time(entrada) is None


def test_todo_time_do_fallback_se_resolve():
    for nome in FALLBACK_STATS:
        assert resolver_time(nome) == nome


def test_normalizar_nome_remove_acento_e_pontuacao():
    assert normalizar_nome("Atlético-MG") == "atleticomg"
    assert normalizar_nome("São Paulo") == "saopaulo"
    assert normalizar_nome("") == ""


# ── Estatísticas ───────────────────────────

def test_get_team_stats_aceita_variantes(fetcher):
    assert fetcher.get_team_stats("CR Flamengo") == FALLBACK_STATS["Flamengo"]
    assert fetcher.get_team_stats("flamengo") == FALLBACK_STATS["Flamengo"]


def test_get_team_stats_nao_deixa_mutar_o_fallback(fetcher):
    stats = fetcher.get_team_stats("Flamengo")
    stats["forca_ataque"] = 99
    assert FALLBACK_STATS["Flamengo"]["forca_ataque"] != 99


def test_time_desconhecido_recebe_stats_neutros(fetcher):
    assert fetcher.get_team_stats("Real Madrid") == STATS_PADRAO


def test_time_conhecido(fetcher):
    assert fetcher.time_conhecido("sao paulo")
    assert not fetcher.time_conhecido("Real Madrid")


def test_stats_formatado_traz_nivel_e_nome_canonico(fetcher):
    s = fetcher.get_time_stats_formatado("cr flamengo")
    assert s["nome"] == "Flamengo"
    assert "⭐" in s["nivel"]


# ── Cache ──────────────────────────────────

def test_cache_nao_muta_o_dicionario_original(fetcher):
    """Regressão: _write_cache injetava '_cached_at' no dict do chamador."""
    original = {"forca_ataque": 1.5}
    fetcher._write_cache("k", original)
    assert original == {"forca_ataque": 1.5}


def test_cache_round_trip(fetcher):
    fetcher._write_cache("k", {"a": 1})
    assert fetcher._sem_metadados(fetcher._read_cache("k")) == {"a": 1}


def test_cache_expira(tmp_path):
    f = DataFetcher(cache_dir=tmp_path, cache_ttl_hours=0)
    f._write_cache("k", {"a": 1})
    assert f._read_cache("k") is None


def test_cache_path_e_estavel_entre_instancias(tmp_path):
    """
    Regressão: o nome do arquivo usava hash(), que é aleatorizado por
    processo — o cache nunca acertava entre execuções.
    """
    a = DataFetcher(cache_dir=tmp_path)._cache_path("stats_Foo/Bar")
    b = DataFetcher(cache_dir=tmp_path)._cache_path("stats_Foo/Bar")
    assert a == b


def test_cache_corrompido_nao_quebra(fetcher):
    fetcher._cache_path("ruim").write_text("{ isso não é json", encoding="utf-8")
    assert fetcher._read_cache("ruim") is None


def test_cache_nao_deixa_arquivo_temporario(fetcher):
    fetcher._write_cache("k", {"a": 1})
    assert not list(fetcher.cache_dir.glob("*.tmp"))


# ── Fontes externas ────────────────────────

def test_sem_chave_de_api_cai_no_demo(fetcher):
    assert fetcher.get_proximos_jogos() == DEMO_MATCHES


def test_cache_vazio_nao_impede_o_fallback(fetcher):
    """Regressão: um cache com lista vazia bloqueava o fallback do demo."""
    fetcher._write_cache("proximos_10", {"jogos": []})
    assert fetcher.get_proximos_jogos(10) == DEMO_MATCHES


def test_tabela_vazia_sem_api(fetcher):
    assert fetcher.get_tabela() == []


def test_normalizacao_da_api_usa_a_mesma_escala_de_ataque_e_defesa():
    """
    Regressão: ataque era dividido por LEAGUE_HOME_AVG e defesa por
    LEAGUE_AWAY_AVG, colocando os dois em escalas diferentes. Um time
    exatamente na média da liga precisa dar 1.0 nos dois fatores.
    """
    from model.engine import LEAGUE_AWAY_AVG, LEAGUE_HOME_AVG

    media = (LEAGUE_HOME_AVG + LEAGUE_AWAY_AVG) / 2
    stats = DataFetcher._normalizar_api_futebol(
        {"gols_marcados": media * 10, "gols_sofridos": media * 10, "jogos": 10}
    )
    assert stats["forca_ataque"] == pytest.approx(1.0, abs=0.01)
    assert stats["fraqueza_defesa"] == pytest.approx(1.0, abs=0.01)


def test_normalizacao_da_api_tolera_lixo():
    stats = DataFetcher._normalizar_api_futebol(
        {"gols_marcados": "abc", "gols_sofridos": None, "jogos": 0}
    )
    assert stats["forca_ataque"] > 0 and stats["fraqueza_defesa"] > 0


def test_extrair_fd_matches_traduz_nomes_longos():
    """
    Regressão: nomes do Football-Data ('CR Flamengo') não batiam com
    FALLBACK_STATS, então toda a fonte secundária virava stats neutros.
    """
    jogos = DataFetcher._extrair_fd_matches({"matches": [{
        "homeTeam": {"name": "CR Flamengo"},
        "awayTeam": {"name": "SE Palmeiras"},
        "utcDate": "2025-05-10T21:00:00Z",
        "matchday": 3,
    }]})
    assert jogos == [{"home": "Flamengo", "away": "Palmeiras",
                      "data": "2025-05-10", "rodada": 3}]


def test_extrair_proximos_ignora_partidas_incompletas():
    jogos = DataFetcher._extrair_proximos({"rodadas": [{"rodada": 1, "partidas": [
        {"status": "agendado", "time_mandante": {"nome_popular": "Flamengo"},
         "time_visitante": {"nome_popular": "Santos"}},
        {"status": "agendado", "time_mandante": None, "time_visitante": None},
        {"status": "finalizado", "time_mandante": {"nome_popular": "Vasco"},
         "time_visitante": {"nome_popular": "Bahia"}},
    ]}]})
    assert len(jogos) == 1
    assert jogos[0]["home"] == "Flamengo"


def test_extratores_toleram_payload_vazio():
    assert DataFetcher._extrair_fd_matches({}) == []
    assert DataFetcher._extrair_proximos({}) == []


# ── Contextos ──────────────────────────────

def test_contextos_tem_descricao_e_fator_valido():
    assert set(CONTEXT_FACTORS) == set(CONTEXT_DESCRIPTIONS)
    assert CONTEXT_FACTORS["normal"] == 1.0
    for nome, fator in CONTEXT_FACTORS.items():
        assert 0 < fator <= 1.0, f"fator de {nome} fora da faixa"
