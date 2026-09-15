"""
backend/database.py — Configuração do banco de dados.

Suporta SQLite (dev/local) e PostgreSQL (produção).
Configure via variável de ambiente DATABASE_URL (lida em config.py).

Exemplos:
  SQLite (padrão):    sqlite:///./futebol_elite.db
  PostgreSQL:         postgresql://user:pass@localhost:5432/futebol_elite
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DATABASE_URL, DB_ECHO  # noqa: E402

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,   # verifica conexão antes de usar
    echo=DB_ECHO,         # DB_ECHO=true para debug de queries SQL
    future=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Iterator[Session]:
    """
    Dependência do FastAPI: entrega uma sessão e garante fechamento.

    Faz rollback em qualquer exceção — sem isso, uma falha no meio de um
    endpoint deixava a sessão suja e a conexão presa no pool.
    """
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
