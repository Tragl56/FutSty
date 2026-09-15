# ─────────────────────────────────────────────────────────
# Futebol Elite — Dockerfile
#
# Build em dois estágios: as ferramentas de compilação (gcc, libpq-dev)
# ficam só no estágio `builder`. A imagem final leva apenas os pacotes
# Python já compilados e a runtime libpq5.
# ─────────────────────────────────────────────────────────

FROM python:3.11-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc \
      libpq-dev \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --prefix=/install -r requirements.txt


# ── Imagem final ─────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# libpq5 é a runtime do psycopg2 (sem os headers de compilação).
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 \
      curl \
  && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app
COPY . .

# Usuário não-root para segurança. O diretório de dados é criado e
# entregue a ele antes do USER, senão o volume monta como root.
RUN mkdir -p /app/data \
 && useradd --create-home --uid 1000 appuser \
 && chown -R appuser:appuser /app
USER appuser

# Expor portas (API e Dashboard)
EXPOSE 8000 8501

# curl é mais leve e confiável que subir o Python só para o healthcheck.
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/ || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
