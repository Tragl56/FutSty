"""
backend/main.py — API REST com FastAPI

Endpoints:
  GET  /                     → health check
  GET  /times                → lista times disponíveis
  GET  /previsoes            → histórico de previsões
  POST /analisar             → analisa uma partida
  POST /analisar/rodada      → analisa todos os jogos de uma rodada
  GET  /tabela/{campeonato}  → tabela de classificação
  GET  /stats/{time}         → estatísticas de um time
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.database import engine, SessionLocal
from backend.models import Base, PrevisaoORM
from model.engine import analisar_partida, MatchAnalysis
from model.data import DataFetcher, CONTEXT_FACTORS, CONTEXT_DESCRIPTIONS

# Inicializa tabelas
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Futebol Elite API",
    description="Sistema de análise estatística de futebol brasileiro",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

fetcher = DataFetcher(
    api_futebol_key=os.getenv("API_FUTEBOL_KEY"),
    football_data_key=os.getenv("FOOTBALL_DATA_KEY"),
)


# ──────────────────────────────────────────
# Schemas Pydantic
# ──────────────────────────────────────────

class PartidaRequest(BaseModel):
    home_team: str
    away_team: str
    competition: str = "Brasileirão Série A"
    context: str = "normal"
    usar_monte_carlo: bool = False
    mc_simulations: int = 10_000


class RodadaRequest(BaseModel):
    campeonato_id: int = 10
    context: str = "normal"
    usar_monte_carlo: bool = False


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
    top_scores: list
    mc_prob_home: Optional[float] = None
    mc_prob_draw: Optional[float] = None
    mc_prob_away: Optional[float] = None
    mc_simulations: int = 0
    gerado_em: str


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

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
        top_scores=[{"home": s.home, "away": s.away, "prob": s.prob} for s in analysis.top_scores[:8]],
        mc_prob_home=analysis.mc_prob_home,
        mc_prob_draw=analysis.mc_prob_draw,
        mc_prob_away=analysis.mc_prob_away,
        mc_simulations=analysis.mc_simulations,
        gerado_em=datetime.now().isoformat(),
    )


def _salvar_previsao(db, analysis: MatchAnalysis):
    row = PrevisaoORM(
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
        placar_mais_provavel=f"{analysis.top_scores[0].label}" if analysis.top_scores else "-",
    )
    db.add(row)
    db.commit()
    return row


# ──────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────

@app.get("/")
def health():
    return {
        "status": "online",
        "versao": "2.0.0",
        "timestamp": datetime.now().isoformat(),
        "modelo": "Poisson + Dixon-Coles + Monte Carlo",
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
    stats = fetcher.get_time_stats_formatado(time_nome)
    if not stats:
        raise HTTPException(status_code=404, detail=f"Time '{time_nome}' não encontrado")
    return {"time": time_nome, "stats": stats}


@app.post("/analisar", response_model=PartidaResponse)
def analisar(req: PartidaRequest):
    times = fetcher.listar_times()
    if req.home_team not in times:
        raise HTTPException(400, f"Time '{req.home_team}' não encontrado")
    if req.away_team not in times:
        raise HTTPException(400, f"Time '{req.away_team}' não encontrado")
    if req.home_team == req.away_team:
        raise HTTPException(400, "Selecione times diferentes")
    if req.context not in CONTEXT_FACTORS:
        raise HTTPException(400, f"Contexto inválido. Use: {list(CONTEXT_FACTORS.keys())}")

    stats_home = fetcher.get_team_stats(req.home_team)
    stats_away = fetcher.get_team_stats(req.away_team)
    cf = CONTEXT_FACTORS[req.context]

    analysis = analisar_partida(
        home_team=req.home_team,
        away_team=req.away_team,
        stats_home=stats_home,
        stats_away=stats_away,
        competition=req.competition,
        context=req.context,
        context_factor=cf,
        usar_monte_carlo=req.usar_monte_carlo,
        mc_simulations=req.mc_simulations,
    )

    db = SessionLocal()
    try:
        _salvar_previsao(db, analysis)
    finally:
        db.close()

    return _analysis_to_response(analysis)


@app.post("/analisar/rodada")
def analisar_rodada(req: RodadaRequest):
    jogos = fetcher.get_proximos_jogos(req.campeonato_id)
    if not jogos:
        raise HTTPException(404, "Nenhum jogo encontrado para esta rodada")

    resultados = []
    cf = CONTEXT_FACTORS.get(req.context, 1.0)
    db = SessionLocal()

    try:
        for jogo in jogos:
            home, away = jogo.get("home", ""), jogo.get("away", "")
            if not home or not away:
                continue

            stats_home = fetcher.get_team_stats(home)
            stats_away = fetcher.get_team_stats(away)

            analysis = analisar_partida(
                home_team=home,
                away_team=away,
                stats_home=stats_home,
                stats_away=stats_away,
                context=req.context,
                context_factor=cf,
                usar_monte_carlo=req.usar_monte_carlo,
            )

            _salvar_previsao(db, analysis)
            resultados.append(_analysis_to_response(analysis))
    finally:
        db.close()

    return {"partidas": len(resultados), "resultados": resultados}


@app.get("/previsoes")
def historico_previsoes(
    limit: int = Query(default=50, ge=1, le=200),
    time: Optional[str] = None,
):
    db = SessionLocal()
    try:
        q = db.query(PrevisaoORM).order_by(PrevisaoORM.criado_em.desc())
        if time:
            q = q.filter(
                (PrevisaoORM.time_casa == time) | (PrevisaoORM.time_fora == time)
            )
        rows = q.limit(limit).all()
        return {"total": len(rows), "previsoes": [r.to_dict() for r in rows]}
    finally:
        db.close()


@app.get("/tabela/{campeonato_id}")
def tabela(campeonato_id: int = 10):
    dados = fetcher.get_tabela(campeonato_id)
    return {"campeonato_id": campeonato_id, "tabela": dados}
