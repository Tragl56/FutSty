"""
backend/models.py — Modelos ORM do banco de dados.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, Index, Integer, String

from backend.database import Base

def agora_utc() -> datetime:
    """
    UTC ingênuo, equivalente ao antigo ``datetime.utcnow()``.

    ``utcnow()`` está depreciado a partir do Python 3.12; esta função mantém
    exatamente a mesma semântica de armazenamento (naive UTC) sem o aviso.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)

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

    # Probabilidades (Poisson + Dixon-Coles)
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

    criado_em      = Column(DateTime, default=agora_utc, index=True)

    # O histórico é sempre lido como "últimas N previsões", com filtro
    # opcional por time — este índice cobre exatamente esse acesso.
    __table_args__ = (
        Index("ix_previsoes_times_data", "time_casa", "time_fora", "criado_em"),
    )

    @property
    def resultado_previsto(self) -> str:
        """'casa', 'empate' ou 'fora' — o resultado de maior probabilidade."""
        probs = {
            "casa": self.prob_casa or 0.0,
            "empate": self.prob_empate or 0.0,
            "fora": self.prob_fora or 0.0,
        }
        return max(probs, key=probs.get)

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
            "resultado_previsto":   self.resultado_previsto,
            "gols_real_casa":  self.gols_real_casa,
            "gols_real_fora":  self.gols_real_fora,
            "acertou_result":  self.acertou_result,
            "criado_em":       self.criado_em.isoformat() if self.criado_em else None,
        }
