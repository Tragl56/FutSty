# ─────────────────────────────────────────────────────────
# Futebol Elite — Dockerfile
# Build multistage: menor imagem final (~200MB)
# ─────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

WORKDIR /app

# Dependências de sistema mínimas
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
  && rm -rf /var/lib/apt/lists/*

# Instalar dependências Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código
COPY . .

# Criar diretório de dados
RUN mkdir -p /app/data

# Usuário não-root para segurança
RUN useradd -m appuser && chown -R appuser /app
USER appuser

# Expor portas (API e Dashboard)
EXPOSE 8000 8501

# Healthcheck da API
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import requests; requests.get('http://localhost:8000/', timeout=5)" || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
