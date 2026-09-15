"""
Fixtures compartilhadas.

Cada teste roda contra um banco SQLite temporário e um diretório de cache
temporário — nada toca o banco ou o cache de desenvolvimento.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def _ambiente_isolado(tmp_path_factory):
    """Aponta banco e cache para um diretório temporário antes dos imports."""
    import os

    base = tmp_path_factory.mktemp("futsty")
    os.environ["DATABASE_URL"] = f"sqlite:///{base / 'test.db'}"
    os.environ["DATA_DIR"] = str(base / "data")
    os.environ["API_FUTEBOL_KEY"] = ""
    os.environ["FOOTBALL_DATA_KEY"] = ""
    yield base


@pytest.fixture
def fetcher(tmp_path):
    from model.data import DataFetcher

    return DataFetcher(cache_dir=tmp_path / "cache")


@pytest.fixture
def client():
    """TestClient com o lifespan ativo (cria as tabelas)."""
    from fastapi.testclient import TestClient

    from backend.main import app

    with TestClient(app) as c:
        yield c
