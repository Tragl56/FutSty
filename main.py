"""
main.py — Ponto de entrada unificado do Futebol Elite.

Uso:
  python main.py                          → modo interativo (terminal)
  python main.py --api                    → inicia API REST (FastAPI)
  python main.py --dashboard              → inicia dashboard (Streamlit)
  python main.py --bot                    → inicia bot automático
  python main.py --once                   → analisa rodada atual e sai
  python main.py --partida "Fla vs Pal"  → analisa partida específica
  python main.py --listar                 → lista times disponíveis
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from model.data import DataFetcher, CONTEXT_FACTORS
from model.engine import analisar_partida


# ──────────────────────────────────────────
# Modo interativo (terminal)
# ──────────────────────────────────────────

def modo_interativo():
    fetcher = DataFetcher()
    times = fetcher.listar_times()

    print("\n" + "="*55)
    print("  ⚽  FUTEBOL ELITE — Sistema de Análise Estatística")
    print("="*55)
    print(f"\n  {len(times)} times disponíveis:")
    for i, t in enumerate(times, 1):
        print(f"  {i:2}. {t}")

    print("\n  Contextos: " + "  |  ".join(CONTEXT_FACTORS.keys()))
    print("\n--- Configurar Partida ---")

    home = input("  Mandante  : ").strip()
    away = input("  Visitante : ").strip()
    context = input("  Contexto [normal]: ").strip() or "normal"
    mc_input = input("  Monte Carlo? (s/N): ").strip().lower()
    usar_mc = mc_input in ("s", "sim", "y", "yes")

    if home not in times:
        print(f"\n[ERRO] Time '{home}' não encontrado.")
        return
    if away not in times:
        print(f"\n[ERRO] Time '{away}' não encontrado.")
        return
    if home == away:
        print("\n[ERRO] Selecione times diferentes.")
        return

    stats_home = fetcher.get_team_stats(home)
    stats_away = fetcher.get_team_stats(away)
    cf = CONTEXT_FACTORS.get(context, 1.0)

    resultado = analisar_partida(
        home_team=home,
        away_team=away,
        stats_home=stats_home,
        stats_away=stats_away,
        context=context,
        context_factor=cf,
        usar_monte_carlo=usar_mc,
        mc_simulations=10_000,
    )

    print(resultado.summary())


# ──────────────────────────────────────────
# Análise rápida de partida via argumento
# ──────────────────────────────────────────

def analisar_partida_cli(partida_str: str):
    """Parse 'TimeA vs TimeB' ou 'TimeA × TimeB'"""
    for sep in [" vs ", " × ", " x ", " X "]:
        if sep in partida_str:
            parts = partida_str.split(sep)
            home, away = parts[0].strip(), parts[1].strip()
            break
    else:
        print("[ERRO] Formato inválido. Use: 'Flamengo vs Palmeiras'")
        return

    fetcher = DataFetcher()
    times = fetcher.listar_times()

    if home not in times:
        print(f"[ERRO] Time '{home}' não encontrado")
        return
    if away not in times:
        print(f"[ERRO] Time '{away}' não encontrado")
        return

    stats_home = fetcher.get_team_stats(home)
    stats_away = fetcher.get_team_stats(away)

    resultado = analisar_partida(
        home_team=home,
        away_team=away,
        stats_home=stats_home,
        stats_away=stats_away,
        usar_monte_carlo=True,
    )

    print(resultado.summary())


# ──────────────────────────────────────────
# CLI
# ──────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="⚽ Futebol Elite — Sistema de Análise Estatística",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--api",       action="store_true",  help="Inicia API REST (FastAPI + uvicorn)")
    parser.add_argument("--dashboard", action="store_true",  help="Inicia dashboard (Streamlit)")
    parser.add_argument("--bot",       action="store_true",  help="Inicia bot automático")
    parser.add_argument("--once",      action="store_true",  help="Analisa rodada atual e sai")
    parser.add_argument("--partida",   type=str,             help="Ex: 'Flamengo vs Palmeiras'")
    parser.add_argument("--listar",    action="store_true",  help="Lista times disponíveis")
    parser.add_argument("--port",      type=int, default=8000, help="Porta da API (padrão: 8000)")
    args = parser.parse_args()

    if args.listar:
        fetcher = DataFetcher()
        times = fetcher.listar_times()
        print(f"\n{len(times)} times disponíveis:\n")
        for t in times:
            s = fetcher.get_time_stats_formatado(t)
            print(f"  {t:<22}  {s['nivel']}")

    elif args.partida:
        analisar_partida_cli(args.partida)

    elif args.api:
        print(f"🚀 Iniciando API em http://0.0.0.0:{args.port}")
        subprocess.run([
            "uvicorn", "backend.main:app",
            "--host", "0.0.0.0",
            "--port", str(args.port),
            "--reload",
        ])

    elif args.dashboard:
        print("🖥️  Iniciando Dashboard Streamlit...")
        subprocess.run(["streamlit", "run", "dashboard/app.py"])

    elif args.bot:
        from bot.scheduler import rodar_loop
        rodar_loop()

    elif args.once:
        from bot.scheduler import analisar_rodada
        analisar_rodada()

    else:
        modo_interativo()
