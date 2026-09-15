"""
bot/scheduler.py — Worker automático de análise de futebol.

Modos:
  python bot/scheduler.py             → loop contínuo (horários de BOT_SCHEDULE_TIMES)
  python bot/scheduler.py --once      → roda uma vez e sai
  python bot/scheduler.py --via-api   → dispara via API REST
  python bot/scheduler.py --list      → lista próximos jogos sem analisar

Para produção, prefira: cron + systemd  ou  Celery + Redis + Beat.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import schedule  # noqa: E402

from config import (  # noqa: E402
    API_BASE_URL,
    BOT_KEEP_RESULTS,
    BOT_POLL_SECONDS,
    BOT_RUN_ON_START,
    BOT_SCHEDULE_TIMES,
    CAMPEONATO_ID_PADRAO,
    DATA_DIR,
    configurar_logging,
)
from model.data import CONTEXT_FACTORS, DataFetcher  # noqa: E402
from model.engine import analisar_partida  # noqa: E402

configurar_logging()
log = logging.getLogger("bot")

RESULTS_DIR = DATA_DIR
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────
# Análise direta (sem API)
# ──────────────────────────────────────────

def analisar_rodada(
    campeonato_id: int = CAMPEONATO_ID_PADRAO,
    context: str = "normal",
    usar_monte_carlo: bool = False,
    verbose: bool = True,
) -> List[dict]:
    log.info("Iniciando análise da rodada (campeonato=%s, contexto=%s)", campeonato_id, context)

    fetcher = DataFetcher()
    jogos = fetcher.get_proximos_jogos(campeonato_id)
    cf = CONTEXT_FACTORS.get(context, 1.0)
    resultados = []

    for jogo in jogos:
        home = jogo.get("home", "")
        away = jogo.get("away", "")
        if not home or not away or home == away:
            continue

        r = analisar_partida(
            home_team=home,
            away_team=away,
            stats_home=fetcher.get_team_stats(home),
            stats_away=fetcher.get_team_stats(away),
            context=context,
            context_factor=cf,
            usar_monte_carlo=usar_monte_carlo,
        )

        if verbose:
            print(r.summary())

        resultados.append({
            "home":           home,
            "away":           away,
            "rodada":         jogo.get("rodada", 0),
            "data":           jogo.get("data", ""),
            "lambda_home":    r.lambda_home,
            "lambda_away":    r.lambda_away,
            "prob_home":      r.prob_home,
            "prob_draw":      r.prob_draw,
            "prob_away":      r.prob_away,
            "xpoints_home":   r.xpoints_home,
            "xpoints_away":   r.xpoints_away,
            "gols_esperados": r.total_goals_expected,
            "btts":           r.btts_prob,
            "over_25":        r.over_2_5_prob,
            "placar_top":     r.top_scores[0].label if r.top_scores else "-",
            "gerado_em":      datetime.now().isoformat(),
        })

    if resultados:
        destino = salvar_resultados(resultados)
        log.info("%d partidas salvas em %s", len(resultados), destino.name)
        limpar_resultados_antigos()
    else:
        log.warning("Nenhuma partida analisada — nada foi salvo.")

    return resultados


def salvar_resultados(resultados: List[dict]) -> Path:
    """Grava o JSON da rodada de forma atômica (tmp + rename)."""
    destino = RESULTS_DIR / f"resultados_{datetime.now():%Y-%m-%d_%H%M}.json"
    temp = destino.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temp, destino)
    return destino


def limpar_resultados_antigos(manter: int = BOT_KEEP_RESULTS) -> int:
    """
    Mantém apenas os N arquivos de resultado mais recentes.

    Sem isso, um worker rodando 2× por dia acumula arquivos indefinidamente
    no volume de dados.
    """
    if manter <= 0:
        return 0
    arquivos = sorted(
        RESULTS_DIR.glob("resultados_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removidos = 0
    for antigo in arquivos[manter:]:
        try:
            antigo.unlink()
            removidos += 1
        except OSError as e:
            log.debug("Não foi possível remover %s: %s", antigo.name, e)
    if removidos:
        log.info("%d arquivo(s) antigo(s) removido(s).", removidos)
    return removidos


# ──────────────────────────────────────────
# Disparo via API REST
# ──────────────────────────────────────────

def analisar_via_api(
    campeonato_id: int = CAMPEONATO_ID_PADRAO,
    context: str = "normal",
    base_url: str = API_BASE_URL,
) -> dict:
    """
    Dispara a análise pela API (que persiste no banco).

    A URL vem de API_BASE_URL — no Docker Compose os containers não enxergam
    127.0.0.1 uns dos outros, então lá o valor é http://api:8000.
    """
    try:
        resp = requests.post(
            f"{base_url}/analisar/rodada",
            json={"campeonato_id": campeonato_id, "context": context},
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        log.info("%s partidas geradas via API (%s)", data.get("partidas", 0), base_url)
        return data
    except (requests.RequestException, ValueError) as e:
        log.warning("API indisponível em %s (%s) — rodando offline.", base_url, e)
        return {
            "partidas": len(analisar_rodada(campeonato_id=campeonato_id, context=context)),
            "origem": "offline",
        }


# ──────────────────────────────────────────
# Jobs agendados
# ──────────────────────────────────────────

def job_agendado(campeonato_id: int, context: str, usar_monte_carlo: bool) -> None:
    """
    Executa uma análise agendada.

    Engole exceções de propósito: uma falha de rede ou de disco não pode
    derrubar o loop do worker e cancelar todos os agendamentos seguintes.
    """
    try:
        analisar_rodada(
            campeonato_id=campeonato_id,
            context=context,
            usar_monte_carlo=usar_monte_carlo,
            verbose=False,
        )
    except Exception:
        log.exception("Job agendado falhou — o worker continua ativo.")


def rodar_loop(
    campeonato_id: int = CAMPEONATO_ID_PADRAO,
    context: str = "normal",
    usar_monte_carlo: bool = False,
    horarios: Optional[List[str]] = None,
) -> None:
    horarios = horarios or BOT_SCHEDULE_TIMES

    for horario in horarios:
        try:
            schedule.every().day.at(horario).do(
                job_agendado, campeonato_id, context, usar_monte_carlo
            )
        except (schedule.ScheduleValueError, ValueError):
            log.error("Horário inválido em BOT_SCHEDULE_TIMES: %r (use HH:MM)", horario)

    if not schedule.get_jobs():
        log.error("Nenhum horário válido configurado — encerrando.")
        return

    log.info("Bot iniciado. Análise diária às %s. Ctrl+C para encerrar.", ", ".join(horarios))

    if BOT_RUN_ON_START:
        job_agendado(campeonato_id, context, usar_monte_carlo)

    try:
        while True:
            schedule.run_pending()
            time.sleep(BOT_POLL_SECONDS)
    except KeyboardInterrupt:
        log.info("Bot encerrado pelo usuário.")


# ──────────────────────────────────────────
# CLI
# ──────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Bot de análise de futebol")
    parser.add_argument("--once",        action="store_true",  help="Roda uma vez e sai")
    parser.add_argument("--via-api",     action="store_true",  help="Dispara via API REST")
    parser.add_argument("--list",        action="store_true",  help="Lista próximos jogos")
    parser.add_argument("--monte-carlo", action="store_true",  help="Ativa Monte Carlo")
    parser.add_argument("--quiet",       action="store_true",  help="Não imprime cada análise")
    parser.add_argument("--context",     default="normal", choices=sorted(CONTEXT_FACTORS),
                        help="Contexto da partida")
    parser.add_argument("--campeonato",  type=int, default=CAMPEONATO_ID_PADRAO,
                        help="ID do campeonato")
    args = parser.parse_args(argv)

    if args.list:
        jogos = DataFetcher().get_proximos_jogos(args.campeonato)
        print(f"\nPróximos {len(jogos)} jogos:")
        for j in jogos:
            print(f"  Rodada {str(j.get('rodada', '-')):>2}  {j['home']:<22} × {j['away']}")
        return 0

    if args.via_api:
        analisar_via_api(args.campeonato, args.context)
        return 0

    if args.once:
        resultados = analisar_rodada(
            campeonato_id=args.campeonato,
            context=args.context,
            usar_monte_carlo=args.monte_carlo,
            verbose=not args.quiet,
        )
        return 0 if resultados else 1

    rodar_loop(
        campeonato_id=args.campeonato,
        context=args.context,
        usar_monte_carlo=args.monte_carlo,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
