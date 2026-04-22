"""
backend/models.py — Modelos ORM do banco de dados.
"""

from datetime import datetime
from sqlalchemy import Column, Integer, Float, String, DateTime, Boolean

from backend.database import Base


class PrevisaoORM(Base):
    __tablename__ = "previsoes"

    id             = Column(Integer, primary_key=True, index=True)
    time_casa      = Column(String, nullable=False, index=True)
    time_fora      = Column(String, nullable=False, index=True)
    competicao     = Column(String, default="Brasileirão Série A")
    contexto       = Column(String, default="normal")

    # Lambdas
    lambda_home    = Column(Float)
    lambda_away    = Column(Float)

    # Probabilidades (Poisson)
    prob_casa      = Column(Float)
    prob_empate    = Column(Float)
    prob_fora      = Column(Float)

    # Métricas avançadas
    xpoints_casa   = Column(Float)
    xpoints_fora   = Column(Float)
    gols_esperados = Column(Float)
    btts           = Column(Float)    # Both Teams To Score
    over_25        = Column(Float)    # Over 2.5 gols
    placar_mais_provavel = Column(String)

    # Resultado real (para validação posterior)
    gols_real_casa = Column(Integer, nullable=True)
    gols_real_fora = Column(Integer, nullable=True)
    acertou_result = Column(Boolean, nullable=True)

    criado_em      = Column(DateTime, default=datetime.utcnow, index=True)

    def to_dict(self) -> dict:
        return {
            "id":              self.id,
            "time_casa":       self.time_casa,
            "time_fora":       self.time_fora,
            "competicao":      self.competicao,
            "contexto":        self.contexto,
            "lambda_home":     self.lambda_home,
            "lambda_away":     self.lambda_away,
            "prob_casa":       self.prob_casa,
            "prob_empate":     self.prob_empate,
            "prob_fora":       self.prob_fora,
            "xpoints_casa":    self.xpoints_casa,
            "xpoints_fora":    self.xpoints_fora,
            "gols_esperados":  self.gols_esperados,
            "btts":            self.btts,
            "over_25":         self.over_25,
            "placar_mais_provavel": self.placar_mais_provavel,
            "criado_em":       self.criado_em.isoformat() if self.criado_em else None,
        }
