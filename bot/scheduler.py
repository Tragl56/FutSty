"""
bot/scheduler.py — Worker automático de análise de futebol.

Modos:
  python bot/scheduler.py             → loop contínuo (análise diária 09:00 e 18:00)
  python bot/scheduler.py --once      → roda uma vez e sai
  python bot/scheduler.py --via-api   → dispara via API REST local
  python bot/scheduler.py --list      → lista próximos jogos sem analisar

Para produção, prefira: cron + systemd  ou  Celery + Redis + Beat.
"""

import argparse
import json
import sys
import time
import requests
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import schedule
from model.data import DataFetcher, CONTEXT_FACTORS
from model.engine import analisar_partida

RESULTS_DIR = ROOT / "data"
RESULTS_DIR.mkdir(exist_ok=True)

API_BASE = "http://127.0.0.1:8000"


# ──────────────────────────────────────────
# Análise direta (sem API)
# ──────────────────────────────────────────

def analisar_rodada(
    campeonato_id: int = 10,
    context: str = "normal",
    usar_monte_carlo: bool = False,
    verbose: bool = True,
) -> list:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"\n[{ts}] 🔄 Iniciando análise da rodada...")

    fetcher = DataFetcher()
    jogos = fetcher.get_proximos_jogos(campeonato_id)
    cf = CONTEXT_FACTORS.get(context, 1.0)
    resultados = []

    for jogo in jogos:
        home = jogo.get("home", "")
        away = jogo.get("away", "")
        if not home or not away:
            continue

        stats_home = fetcher.get_team_stats(home)
        stats_away = fetcher.get_team_stats(away)

        r = analisar_partida(
            home_team=home,
            away_team=away,
            stats_home=stats_home,
            stats_away=stats_away,
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

    fname = RESULTS_DIR / f"resultados_{datetime.now():%Y-%m-%d_%H%M}.json"
    fname.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[✅] {len(resultados)} partidas salvas em {fname.name}")
    return resultados


# ──────────────────────────────────────────
# Disparo via API REST
# ──────────────────────────────────────────

def analisar_via_api(campeonato_id: int = 10, context: str = "normal"):
    try:
        resp = requests.post(
            f"{API_BASE}/analisar/rodada",
            json={"campeonato_id": campeonato_id, "context": context},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        print(f"[API] {data.get('partidas', 0)} partidas geradas via API")
        return data
    except Exception as e:
        print(f"[API] Erro ao chamar API: {e} — rodando offline...")
        return analisar_rodada(campeonato_id=campeonato_id, context=context)


# ──────────────────────────────────────────
# Jobs agendados
# ──────────────────────────────────────────

def job_manha():
    print(f"\n☀️  [{datetime.now():%H:%M}] Job matinal iniciado")
    analisar_rodada()

def job_tarde():
    print(f"\n🌆  [{datetime.now():%H:%M}] Job vespertino iniciado")
    analisar_rodada()


def rodar_loop():
    print("🤖 Bot iniciado. Análise diária às 09:00 e 18:00.")
    print("   Pressione Ctrl+C para encerrar.\n")

    schedule.every().day.at("09:00").do(job_manha)
    schedule.every().day.at("18:00").do(job_tarde)

    # Análise imediata na inicialização
    analisar_rodada()

    while True:
        schedule.run_pending()
        time.sleep(30)


# ──────────────────────────────────────────
# CLI
# ──────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot de análise de futebol")
    parser.add_argument("--once",        action="store_true",  help="Roda uma vez e sai")
    parser.add_argument("--via-api",     action="store_true",  help="Dispara via API REST local")
    parser.add_argument("--list",        action="store_true",  help="Lista próximos jogos")
    parser.add_argument("--monte-carlo", action="store_true",  help="Ativa Monte Carlo")
    parser.add_argument("--context",     default="normal",     help="Contexto da partida")
    parser.add_argument("--campeonato",  type=int, default=10, help="ID do campeonato")
    args = parser.parse_args()

    if args.list:
        fetcher = DataFetcher()
        jogos = fetcher.get_proximos_jogos(args.campeonato)
        print(f"\nPróximos {len(jogos)} jogos:")
        for j in jogos:
            print(f"  Rodada {j.get('rodada','-'):2}  {j['home']:<22} × {j['away']}")

    elif args.via_api:
        analisar_via_api(args.campeonato, args.context)

    elif args.once:
        analisar_rodada(
            campeonato_id=args.campeonato,
            context=args.context,
            usar_monte_carlo=args.monte_carlo,
        )

    else:
        rodar_loop()
