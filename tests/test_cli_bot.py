"""Testes da CLI (main.py) e do worker (bot/scheduler.py)."""

from __future__ import annotations

import json

import pytest

import main as cli
from bot import scheduler


# ── Parsing de partida ─────────────────────

@pytest.mark.parametrize("texto,esperado", [
    ("Flamengo vs Palmeiras", ("Flamengo", "Palmeiras")),
    ("Atlético-MG x Cruzeiro", ("Atlético-MG", "Cruzeiro")),
    ("Grêmio × Internacional", ("Grêmio", "Internacional")),
    ("Vasco v Santos", ("Vasco", "Santos")),
    ("  Bahia vs Sport  ", ("Bahia", "Sport")),
])
def test_separar_partida(texto, esperado):
    assert cli.separar_partida(texto) == esperado


@pytest.mark.parametrize("texto", ["Flamengo", "", "vs", "Flamengo vs "])
def test_separar_partida_invalida(texto):
    assert cli.separar_partida(texto) is None


def test_separar_partida_divide_so_no_primeiro_separador():
    assert cli.separar_partida("A vs B vs C") == ("A", "B vs C")


# ── Códigos de saída da CLI ────────────────

def test_listar_retorna_zero(capsys):
    assert cli.main(["--listar"]) == 0
    assert "times disponíveis" in capsys.readouterr().out


def test_partida_valida_retorna_zero(capsys):
    assert cli.main(["--partida", "sao paulo vs CR Flamengo"]) == 0
    assert "São Paulo" in capsys.readouterr().out


def test_partida_com_time_inexistente_retorna_um(capsys):
    assert cli.main(["--partida", "Barcelona vs Flamengo"]) == 1
    assert "não encontrado" in capsys.readouterr().out


def test_partida_com_formato_invalido_retorna_um(capsys):
    assert cli.main(["--partida", "lixo"]) == 1
    assert "Formato inválido" in capsys.readouterr().out


def test_partida_com_times_iguais_retorna_um(capsys):
    assert cli.main(["--partida", "Flamengo vs flamengo"]) == 1
    assert "times diferentes" in capsys.readouterr().out


def test_contexto_invalido_e_rejeitado_pelo_argparse():
    with pytest.raises(SystemExit):
        cli.main(["--partida", "Flamengo vs Santos", "--context", "inexistente"])


def test_modos_sao_mutuamente_exclusivos():
    with pytest.raises(SystemExit):
        cli.main(["--api", "--dashboard"])


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    assert "Futebol Elite" in capsys.readouterr().out


# ── Worker ─────────────────────────────────

def test_analisar_rodada_gera_resultados(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "RESULTS_DIR", tmp_path)
    resultados = scheduler.analisar_rodada(verbose=False)

    assert len(resultados) > 0
    arquivos = list(tmp_path.glob("resultados_*.json"))
    assert len(arquivos) == 1

    salvo = json.loads(arquivos[0].read_text(encoding="utf-8"))
    assert len(salvo) == len(resultados)
    for r in salvo:
        assert r["prob_home"] + r["prob_draw"] + r["prob_away"] == pytest.approx(1.0, abs=1e-3)
        assert r["placar_top"]


def test_salvar_resultados_e_atomico(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "RESULTS_DIR", tmp_path)
    scheduler.salvar_resultados([{"home": "A", "away": "B"}])
    assert not list(tmp_path.glob("*.tmp")), "arquivo temporário não pode sobrar"


def test_limpar_resultados_antigos(tmp_path, monkeypatch):
    """Sem limpeza, o worker acumula arquivos indefinidamente no volume."""
    monkeypatch.setattr(scheduler, "RESULTS_DIR", tmp_path)
    for i in range(10):
        arq = tmp_path / f"resultados_2025-01-{i + 1:02d}_1200.json"
        arq.write_text("[]", encoding="utf-8")

    assert scheduler.limpar_resultados_antigos(manter=3) == 7
    assert len(list(tmp_path.glob("resultados_*.json"))) == 3


def test_limpar_resultados_desativado(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "RESULTS_DIR", tmp_path)
    (tmp_path / "resultados_2025-01-01_1200.json").write_text("[]", encoding="utf-8")
    assert scheduler.limpar_resultados_antigos(manter=0) == 0
    assert len(list(tmp_path.glob("resultados_*.json"))) == 1


def test_job_agendado_nao_propaga_excecao(monkeypatch):
    """
    Regressão: uma falha no job derrubava o loop inteiro do worker e
    cancelava todos os agendamentos seguintes.
    """
    def explode(**kwargs):
        raise RuntimeError("falha simulada de rede")

    monkeypatch.setattr(scheduler, "analisar_rodada", explode)
    scheduler.job_agendado(10, "normal", False)   # não pode levantar


def test_analisar_via_api_cai_para_offline(monkeypatch, tmp_path):
    monkeypatch.setattr(scheduler, "RESULTS_DIR", tmp_path)
    resultado = scheduler.analisar_via_api(base_url="http://127.0.0.1:59999")
    assert resultado["origem"] == "offline"
    assert resultado["partidas"] > 0


def test_bot_cli_list(capsys):
    assert scheduler.main(["--list"]) == 0
    assert "Próximos" in capsys.readouterr().out


def test_bot_cli_once(tmp_path, monkeypatch):
    monkeypatch.setattr(scheduler, "RESULTS_DIR", tmp_path)
    assert scheduler.main(["--once", "--quiet"]) == 0
