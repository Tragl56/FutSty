"""
backend/main.py — API REST com FastAPI

Endpoints:
  GET  /                     → health check
  GET  /times                → lista times disponíveis
  GET  /contextos            → contextos de jogo e seus fatores
  GET  /stats/{time}         → estatísticas de um time
  POST /analisar             → analisa uma partida
  POST /analisar/rodada      → analisa todos os jogos de uma rodada
  GET  /previsoes            → histórico de previsões
  GET  /tabela/{campeonato}  → tabela de classificação
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import (
    CAMPEONATO_ID_PADRAO,
    CORS_ALLOW_CREDENTIALS,
    CORS_ORIGINS,
    VERSION,
    configurar_logging,
)
from backend.database import engine, get_db
from backend.models import Base, PrevisaoORM
from model.data import CONTEXT_DESCRIPTIONS, CONTEXT_FACTORS, DataFetcher, resolver_time
from model.engine import MatchAnalysis, analisar_partida

configurar_logging()
log = logging.getLogger(__name__)

MODELO = "Poisson + Dixon-Coles + Monte Carlo"

# Teto de partidas analisadas numa rodada — evita que uma resposta da API
# externa com centenas de jogos trave a requisição.
MAX_JOGOS_RODADA = 50


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    log.info("Futebol Elite API %s pronta.", VERSION)
    yield


app = FastAPI(
    title="Futebol Elite API",
    description="Sistema de análise estatística de futebol brasileiro",
    version=VERSION,
    lifespan=lifespan,
)

# `allow_origins=["*"]` combinado com `allow_credentials=True` é rejeitado
# pelos navegadores. config.py só habilita credenciais quando há uma lista
# explícita de origens em CORS_ORIGINS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=["*"],
    allow_headers=["*"],
)

fetcher = DataFetcher()


# ──────────────────────────────────────────
# Schemas Pydantic
# ──────────────────────────────────────────

class PartidaRequest(BaseModel):
    home_team: str = Field(min_length=1, max_length=80)
    away_team: str = Field(min_length=1, max_length=80)
    competition: str = Field(default="Brasileirão Série A", max_length=80)
    context: str = "normal"
    usar_monte_carlo: bool = False
    mc_simulations: int = Field(default=10_000, ge=100, le=500_000)


class RodadaRequest(BaseModel):
    campeonato_id: int = Field(default=CAMPEONATO_ID_PADRAO, ge=1)
    context: str = "normal"
    usar_monte_carlo: bool = False


class ScoreOut(BaseModel):
    home: int
    away: int
    prob: float
    label: str


class PartidaResponse(BaseModel):
    home_team: str
    away_team: str
    competition: str
    context: str
    lambda_home: float
    lambda_away: float
    prob_home: float
    prob_draw: float
    prob_away: float
    xpoints_home: float
    xpoints_away: float
    total_goals_expected: float
    btts_prob: float
    over_2_5_prob: float
    top_scores: List[ScoreOut]
    mc_prob_home: Optional[float] = None
    mc_prob_draw: Optional[float] = None
    mc_prob_away: Optional[float] = None
    mc_simulations: int = 0
    gerado_em: str


class RodadaResponse(BaseModel):
    partidas: int
    resultados: List[PartidaResponse]


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

def _agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolver_ou_erro(nome: str, papel: str) -> str:
    """Traduz o nome do time ou devolve 400 com a lista de opções."""
    canonico = resolver_time(nome)
    if canonico is None:
        raise HTTPException(
            status_code=400,
            detail=f"Time {papel} '{nome}' não encontrado. Consulte GET /times.",
        )
    return canonico


def _validar_contexto(context: str) -> float:
    if context not in CONTEXT_FACTORS:
        raise HTTPException(
            status_code=400,
            detail=f"Contexto inválido. Use um de: {list(CONTEXT_FACTORS)}",
        )
    return CONTEXT_FACTORS[context]


def _analysis_to_response(analysis: MatchAnalysis) -> PartidaResponse:
    return PartidaResponse(
        home_team=analysis.home_team,
        away_team=analysis.away_team,
        competition=analysis.competition,
        context=analysis.context,
        lambda_home=analysis.lambda_home,
        lambda_away=analysis.lambda_away,
        prob_home=analysis.prob_home,
        prob_draw=analysis.prob_draw,
        prob_away=analysis.prob_away,
        xpoints_home=analysis.xpoints_home,
        xpoints_away=analysis.xpoints_away,
        total_goals_expected=analysis.total_goals_expected,
        btts_prob=analysis.btts_prob,
        over_2_5_prob=analysis.over_2_5_prob,
        top_scores=[ScoreOut(**s.to_dict()) for s in analysis.top_scores[:8]],
        mc_prob_home=analysis.mc_prob_home,
        mc_prob_draw=analysis.mc_prob_draw,
        mc_prob_away=analysis.mc_prob_away,
        mc_simulations=analysis.mc_simulations,
        gerado_em=_agora_iso(),
    )


def _nova_previsao(analysis: MatchAnalysis) -> PrevisaoORM:
    """Monta a linha do histórico. O commit fica a cargo do chamador."""
    return PrevisaoORM(
        time_casa=analysis.home_team,
        time_fora=analysis.away_team,
        competicao=analysis.competition,
        contexto=analysis.context,
        lambda_home=analysis.lambda_home,
        lambda_away=analysis.lambda_away,
        prob_casa=analysis.prob_home,
        prob_empate=analysis.prob_draw,
        prob_fora=analysis.prob_away,
        xpoints_casa=analysis.xpoints_home,
        xpoints_fora=analysis.xpoints_away,
        gols_esperados=analysis.total_goals_expected,
        btts=analysis.btts_prob,
        over_25=analysis.over_2_5_prob,
        placar_mais_provavel=analysis.top_scores[0].label if analysis.top_scores else "-",
    )


# ──────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────

@app.get("/")
def health():
    return {
        "status": "online",
        "versao": VERSION,
        "timestamp": _agora_iso(),
        "modelo": MODELO,
    }


@app.get("/times")
def listar_times():
    times = fetcher.listar_times()
    return {"times": times, "total": len(times)}


@app.get("/contextos")
def listar_contextos():
    return [
        {"id": k, "fator": v, "descricao": CONTEXT_DESCRIPTIONS.get(k, "")}
        for k, v in CONTEXT_FACTORS.items()
    ]


@app.get("/stats/{time_nome}")
def stats_time(time_nome: str):
    canonico = resolver_time(time_nome)
    if canonico is None:
        raise HTTPException(
            status_code=404,
            detail=f"Time '{time_nome}' não encontrado. Consulte GET /times.",
        )
    return {"time": canonico, "stats": fetcher.get_time_stats_formatado(canonico)}


@app.post("/analisar", response_model=PartidaResponse)
def analisar(req: PartidaRequest, db: Session = Depends(get_db)):
    home = _resolver_ou_erro(req.home_team, "mandante")
    away = _resolver_ou_erro(req.away_team, "visitante")
    if home == away:
        raise HTTPException(400, "Selecione times diferentes")
    cf = _validar_contexto(req.context)

    analysis = analisar_partida(
        home_team=home,
        away_team=away,
        stats_home=fetcher.get_team_stats(home),
        stats_away=fetcher.get_team_stats(away),
        competition=req.competition,
        context=req.context,
        context_factor=cf,
        usar_monte_carlo=req.usar_monte_carlo,
        mc_simulations=req.mc_simulations,
    )

    db.add(_nova_previsao(analysis))
    db.commit()

    return _analysis_to_response(analysis)


@app.post("/analisar/rodada", response_model=RodadaResponse)
def analisar_rodada(req: RodadaRequest, db: Session = Depends(get_db)):
    cf = _validar_contexto(req.context)

    jogos = fetcher.get_proximos_jogos(req.campeonato_id)
    if not jogos:
        raise HTTPException(404, "Nenhum jogo encontrado para esta rodada")

    resultados: List[PartidaResponse] = []
    for jogo in jogos[:MAX_JOGOS_RODADA]:
        home, away = jogo.get("home", ""), jogo.get("away", "")
        if not home or not away or home == away:
            continue

        analysis = analisar_partida(
            home_team=home,
            away_team=away,
            stats_home=fetcher.get_team_stats(home),
            stats_away=fetcher.get_team_stats(away),
            context=req.context,
            context_factor=cf,
            usar_monte_carlo=req.usar_monte_carlo,
        )

        db.add(_nova_previsao(analysis))
        resultados.append(_analysis_to_response(analysis))

    # Um único commit para a rodada inteira, em vez de um por partida.
    db.commit()

    return RodadaResponse(partidas=len(resultados), resultados=resultados)


@app.get("/previsoes")
def historico_previsoes(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    time: Optional[str] = None,
    db: Session = Depends(get_db),
):
    q = db.query(PrevisaoORM)
    if time:
        canonico = resolver_time(time) or time
        q = q.filter(
            (PrevisaoORM.time_casa == canonico) | (PrevisaoORM.time_fora == canonico)
        )

    total = q.count()
    rows = (
        q.order_by(PrevisaoORM.criado_em.desc(), PrevisaoORM.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "previsoes": [r.to_dict() for r in rows],
    }


@app.get("/tabela/{campeonato_id}")
def tabela(campeonato_id: int = CAMPEONATO_ID_PADRAO):
    return {"campeonato_id": campeonato_id, "tabela": fetcher.get_tabela(campeonato_id)}
