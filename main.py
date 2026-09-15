"""
main.py — Ponto de entrada unificado do Futebol Elite.

Uso:
  python main.py                            → modo interativo (terminal)
  python main.py --api                      → inicia API REST (FastAPI)
  python main.py --dashboard                → inicia dashboard (Streamlit)
  python main.py --bot                      → inicia bot automático
  python main.py --once                     → analisa rodada atual e sai
  python main.py --partida "Fla vs Pal"     → analisa partida específica
  python main.py --listar                   → lista times disponíveis
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import API_HOST, API_PORT, APP_NAME, VERSION
from model.data import CONTEXT_FACTORS, DataFetcher, resolver_time
from model.engine import analisar_partida

SEPARADORES = (" vs ", " x ", " × ", " X ", " VS ", " v ")


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

def _resolver(nome: str, papel: str) -> Optional[str]:
    """Resolve o nome do time, imprimindo uma dica útil quando falha."""
    canonico = resolver_time(nome)
    if canonico is None:
        print(f"\n[ERRO] Time {papel} '{nome}' não encontrado.")
        print("       Use --listar para ver os times disponíveis.")
    return canonico


def _analisar_e_imprimir(
    home: str,
    away: str,
    context: str = "normal",
    usar_monte_carlo: bool = False,
) -> int:
    if home == away:
        print("\n[ERRO] Selecione times diferentes.")
        return 1
    if context not in CONTEXT_FACTORS:
        print(f"\n[ERRO] Contexto inválido. Use: {', '.join(CONTEXT_FACTORS)}")
        return 1

    fetcher = DataFetcher()
    resultado = analisar_partida(
        home_team=home,
        away_team=away,
        stats_home=fetcher.get_team_stats(home),
        stats_away=fetcher.get_team_stats(away),
        context=context,
        context_factor=CONTEXT_FACTORS[context],
        usar_monte_carlo=usar_monte_carlo,
    )
    print(resultado.summary())
    return 0


def separar_partida(texto: str) -> Optional[Tuple[str, str]]:
    """
    Divide 'TimeA vs TimeB' nos dois nomes.

    Divide apenas na primeira ocorrência do separador, para não quebrar
    nomes compostos, e aceita vs / x / × / v.
    """
    for sep in SEPARADORES:
        if sep in texto:
            home, _, away = texto.partition(sep)
            home, away = home.strip(), away.strip()
            if home and away:
                return home, away
    return None


# ──────────────────────────────────────────
# Modo interativo (terminal)
# ──────────────────────────────────────────

def modo_interativo() -> int:
    fetcher = DataFetcher()
    times = fetcher.listar_times()

    print("\n" + "=" * 55)
    print(f"  ⚽  {APP_NAME.upper()} — Sistema de Análise Estatística  v{VERSION}")
    print("=" * 55)
    print(f"\n  {len(times)} times disponíveis:")
    for i, t in enumerate(times, 1):
        print(f"  {i:2}. {t}")

    print("\n  Contextos: " + "  |  ".join(CONTEXT_FACTORS))
    print("  (nomes aceitam acentos e caixa livres — 'sao paulo' funciona)")
    print("\n--- Configurar Partida ---")

    try:
        home_input = input("  Mandante  : ").strip()
        away_input = input("  Visitante : ").strip()
        context = input("  Contexto [normal]: ").strip() or "normal"
        usar_mc = input("  Monte Carlo? (s/N): ").strip().lower() in ("s", "sim", "y", "yes")
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        return 130

    home = _resolver(home_input, "mandante")
    away = _resolver(away_input, "visitante")
    if not home or not away:
        return 1

    return _analisar_e_imprimir(home, away, context, usar_mc)


# ──────────────────────────────────────────
# Análise rápida de partida via argumento
# ──────────────────────────────────────────

def analisar_partida_cli(
    partida_str: str,
    context: str = "normal",
    usar_monte_carlo: bool = True,
) -> int:
    par = separar_partida(partida_str)
    if par is None:
        print("[ERRO] Formato inválido. Use: 'Flamengo vs Palmeiras'")
        return 1

    home = _resolver(par[0], "mandante")
    away = _resolver(par[1], "visitante")
    if not home or not away:
        return 1

    return _analisar_e_imprimir(home, away, context, usar_monte_carlo)


# ──────────────────────────────────────────
# Serviços
# ──────────────────────────────────────────

def _rodar(comando: List[str], descricao: str) -> int:
    """
    Executa um serviço externo.

    Usa `sys.executable -m ...` em vez do binário solto no PATH: assim o
    serviço sobe com o mesmo interpretador/venv que rodou este script.
    """
    print(descricao)
    try:
        return subprocess.run(comando, check=False).returncode
    except FileNotFoundError:
        print(f"[ERRO] Não foi possível executar: {' '.join(comando)}")
        print("       Instale as dependências com: pip install -r requirements.txt")
        return 127
    except KeyboardInterrupt:
        return 130


def iniciar_api(host: str, port: int, reload: bool) -> int:
    comando = [
        sys.executable, "-m", "uvicorn", "backend.main:app",
        "--host", host, "--port", str(port),
    ]
    if reload:
        comando.append("--reload")
    return _rodar(comando, f"🚀 Iniciando API em http://{host}:{port} (docs em /docs)")


def iniciar_dashboard() -> int:
    return _rodar(
        [sys.executable, "-m", "streamlit", "run", str(ROOT / "dashboard" / "app.py")],
        "🖥️  Iniciando Dashboard Streamlit...",
    )


# ──────────────────────────────────────────
# CLI
# ──────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=f"⚽ {APP_NAME} — Sistema de Análise Estatística",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--api",       action="store_true", help="Inicia API REST (FastAPI + uvicorn)")
    modo.add_argument("--dashboard", action="store_true", help="Inicia dashboard (Streamlit)")
    modo.add_argument("--bot",       action="store_true", help="Inicia bot automático")
    modo.add_argument("--once",      action="store_true", help="Analisa rodada atual e sai")
    modo.add_argument("--partida",   type=str,            help="Ex: 'Flamengo vs Palmeiras'")
    modo.add_argument("--listar",    action="store_true", help="Lista times disponíveis")

    parser.add_argument("--context", default="normal", choices=sorted(CONTEXT_FACTORS),
                        help="Contexto da partida (padrão: normal)")
    parser.add_argument("--monte-carlo", dest="monte_carlo", action="store_true",
                        help="Ativa a simulação Monte Carlo")
    parser.add_argument("--host", default=API_HOST, help=f"Host da API (padrão: {API_HOST})")
    parser.add_argument("--port", type=int, default=API_PORT,
                        help=f"Porta da API (padrão: {API_PORT})")
    parser.add_argument("--no-reload", action="store_true",
                        help="Desativa o auto-reload da API (use em produção)")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    args = parser.parse_args(argv)

    if args.listar:
        fetcher = DataFetcher()
        times = fetcher.listar_times()
        print(f"\n{len(times)} times disponíveis:\n")
        for t in times:
            print(f"  {t:<22}  {fetcher.get_time_stats_formatado(t)['nivel']}")
        return 0

    if args.partida:
        return analisar_partida_cli(args.partida, args.context, args.monte_carlo or True)

    if args.api:
        return iniciar_api(args.host, args.port, reload=not args.no_reload)

    if args.dashboard:
        return iniciar_dashboard()

    if args.bot:
        from bot.scheduler import rodar_loop
        rodar_loop(context=args.context, usar_monte_carlo=args.monte_carlo)
        return 0

    if args.once:
        from bot.scheduler import analisar_rodada
        return 0 if analisar_rodada(
            context=args.context, usar_monte_carlo=args.monte_carlo
        ) else 1

    return modo_interativo()


def _main_seguro() -> int:
    """
    Envolve main() tratando BrokenPipeError.

    Sem isso, `python main.py --listar | head` termina com um traceback feio
    quando o `head` fecha o pipe antes do fim da listagem.
    """
    try:
        return main()
    except BrokenPipeError:
        try:
            sys.stdout.close()
        finally:
            return 0
    except KeyboardInterrupt:
        print("\nCancelado.")
        return 130


if __name__ == "__main__":
    raise SystemExit(_main_seguro())
