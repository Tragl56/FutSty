"""
backend/database.py — Configuração do banco de dados.

Suporta SQLite (dev/local) e PostgreSQL (produção).
Configure via variável de ambiente DATABASE_URL.

Exemplos:
  SQLite (padrão):    sqlite:///./futebol_elite.db
  PostgreSQL:         postgresql://user:pass@localhost:5432/futebol_elite
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Detecta automaticamente: PostgreSQL em produção, SQLite em desenvolvimento
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./futebol_elite.db"
)

# Ajuste necessário para PostgreSQL em algumas plataformas (Heroku, Railway)
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,   # verifica conexão antes de usar
    echo=False,           # True para debug de queries SQL
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()
