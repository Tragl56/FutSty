"""
config.py — Configuração central do Futebol Elite.

Único lugar que lê o ambiente. Importar este módulo carrega o arquivo `.env`
automaticamente (se existir), o que antes era prometido no `.env.example` mas
nunca acontecia: variáveis como API_HOST, API_PORT e CACHE_TTL_HOURS ficavam
documentadas e ignoradas.

Todas as constantes têm padrão seguro, então o projeto continua rodando
100% offline sem nenhum `.env`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent

# Carrega .env sem quebrar se python-dotenv não estiver instalado.
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover - dependência opcional
    pass


# ──────────────────────────────────────────
# Leitores tolerantes de ambiente
# ──────────────────────────────────────────

def env_str(nome: str, padrao: str = "") -> str:
    valor = os.getenv(nome)
    return valor.strip() if valor and valor.strip() else padrao


def env_opt(nome: str) -> Optional[str]:
    """Como env_str, mas devolve None em vez de string vazia."""
    return env_str(nome) or None


def env_int(nome: str, padrao: int) -> int:
    try:
        return int(env_str(nome, str(padrao)))
    except ValueError:
        logging.getLogger(__name__).warning(
            "%s inválido (%r); usando padrão %s", nome, os.getenv(nome), padrao
        )
        return padrao


def env_float(nome: str, padrao: float) -> float:
    try:
        return float(env_str(nome, str(padrao)))
    except ValueError:
        logging.getLogger(__name__).warning(
            "%s inválido (%r); usando padrão %s", nome, os.getenv(nome), padrao
        )
        return padrao


def env_bool(nome: str, padrao: bool = False) -> bool:
    return env_str(nome, str(padrao)).lower() in ("1", "true", "yes", "sim", "on")


def env_list(nome: str, padrao: List[str]) -> List[str]:
    bruto = env_str(nome)
    if not bruto:
        return list(padrao)
    return [item.strip() for item in bruto.split(",") if item.strip()]


# ──────────────────────────────────────────
# Identidade
# ──────────────────────────────────────────
VERSION: str = "2.1.0"
APP_NAME: str = "Futebol Elite"
ENV: str = env_str("ENV", "development")
IS_PRODUCTION: bool = ENV.lower() in ("production", "prod")

# ──────────────────────────────────────────
# Caminhos
# ──────────────────────────────────────────
DATA_DIR: Path = Path(env_str("DATA_DIR", str(ROOT / "data")))

# ──────────────────────────────────────────
# APIs de dados externas
# ──────────────────────────────────────────
API_FUTEBOL_KEY: Optional[str] = env_opt("API_FUTEBOL_KEY")
FOOTBALL_DATA_KEY: Optional[str] = env_opt("FOOTBALL_DATA_KEY")
HTTP_TIMEOUT: float = env_float("HTTP_TIMEOUT", 10.0)
HTTP_RETRIES: int = env_int("HTTP_RETRIES", 2)
CACHE_TTL_HOURS: float = env_float("CACHE_TTL_HOURS", 6.0)
CAMPEONATO_ID_PADRAO: int = env_int("CAMPEONATO_ID", 10)

# Chaves de exemplo não valem como chave de verdade.
_PLACEHOLDERS = {"seu_token_aqui", "your_token_here", "changeme", "todo"}
if API_FUTEBOL_KEY and API_FUTEBOL_KEY.lower() in _PLACEHOLDERS:
    API_FUTEBOL_KEY = None
if FOOTBALL_DATA_KEY and FOOTBALL_DATA_KEY.lower() in _PLACEHOLDERS:
    FOOTBALL_DATA_KEY = None

# ──────────────────────────────────────────
# Banco de dados
# ──────────────────────────────────────────
DATABASE_URL: str = env_str("DATABASE_URL", f"sqlite:///{ROOT / 'futebol_elite.db'}")
# Heroku/Railway ainda entregam o esquema legado `postgres://`.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
DB_ECHO: bool = env_bool("DB_ECHO", False)

# ──────────────────────────────────────────
# API REST
# ──────────────────────────────────────────
API_HOST: str = env_str("API_HOST", "0.0.0.0")
API_PORT: int = env_int("API_PORT", 8000)

# URL usada pelo dashboard e pelo bot para falar com a API.
# No Docker Compose os containers não enxergam 127.0.0.1 uns dos outros —
# por isso o compose define API_BASE_URL=http://api:8000.
API_BASE_URL: str = env_str("API_BASE_URL", f"http://127.0.0.1:{API_PORT}").rstrip("/")

# `*` com allow_credentials=True é rejeitado pelos navegadores; em produção
# defina CORS_ORIGINS com a lista de origens permitidas.
CORS_ORIGINS: List[str] = env_list("CORS_ORIGINS", ["*"])
CORS_ALLOW_CREDENTIALS: bool = env_bool("CORS_ALLOW_CREDENTIALS", False) and CORS_ORIGINS != ["*"]

# ──────────────────────────────────────────
# Bot / agendador
# ──────────────────────────────────────────
BOT_SCHEDULE_TIMES: List[str] = env_list("BOT_SCHEDULE_TIMES", ["09:00", "18:00"])
BOT_RUN_ON_START: bool = env_bool("BOT_RUN_ON_START", True)
BOT_POLL_SECONDS: int = env_int("BOT_POLL_SECONDS", 30)
BOT_KEEP_RESULTS: int = env_int("BOT_KEEP_RESULTS", 30)

# ──────────────────────────────────────────
# Logging
# ──────────────────────────────────────────
LOG_LEVEL: str = env_str("LOG_LEVEL", "INFO").upper()

_log_configurado = False


def configurar_logging(level: Optional[str] = None) -> None:
    """Configura o logging raiz uma única vez, de forma idempotente."""
    global _log_configurado
    if _log_configurado:
        return
    logging.basicConfig(
        level=getattr(logging, (level or LOG_LEVEL), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    _log_configurado = True
