#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# scripts/setup.sh — Configuração rápida para desenvolvimento local
# Uso: chmod +x scripts/setup.sh && ./scripts/setup.sh
# ─────────────────────────────────────────────────────────

set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

# Roda a partir da raiz do projeto, não importa de onde foi chamado.
cd "$(dirname "$0")/.."

echo -e "${BLUE}"
echo "  ⚽  Futebol Elite — Setup"
echo "======================================${NC}"

# ── Python version check ────────────────
if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}✗ python3 não encontrado. Instale Python 3.9+ e rode de novo.${NC}"
    exit 1
fi

python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" || {
    echo -e "${RED}✗ Python ${python_version} é antigo demais. Mínimo: 3.9${NC}"
    exit 1
}
echo -e "${GREEN}✓ Python ${python_version} detectado${NC}"

# ── Virtual environment ─────────────────
if [ ! -d ".venv" ]; then
    echo -e "\n${YELLOW}Criando ambiente virtual...${NC}"
    python3 -m venv .venv
    echo -e "${GREEN}✓ .venv criado${NC}"
fi

# shellcheck disable=SC1091
source .venv/bin/activate
echo -e "${GREEN}✓ Ambiente virtual ativado${NC}"

# ── Instalar dependências ───────────────
echo -e "\n${YELLOW}Instalando dependências...${NC}"
pip install --upgrade pip --quiet
pip install -r requirements.txt -r requirements-dev.txt --quiet
echo -e "${GREEN}✓ Dependências instaladas${NC}"

# ── .env ───────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${GREEN}✓ .env criado a partir de .env.example${NC}"
    echo -e "${YELLOW}  → Opcional: edite .env com suas chaves de API${NC}"
else
    echo -e "${GREEN}✓ .env já existe${NC}"
fi

# ── Diretório de dados ──────────────────
mkdir -p data
echo -e "${GREEN}✓ Diretório data/ pronto${NC}"

# ── Suíte de testes ─────────────────────
echo -e "\n${YELLOW}Rodando a suíte de testes...${NC}"
if python3 -m pytest -q; then
    echo -e "${GREEN}✓ Todos os testes passaram${NC}"
else
    echo -e "${RED}✗ A suíte de testes falhou — veja a saída acima${NC}"
    exit 1
fi

# ── Teste rápido do motor ───────────────
echo -e "\n${YELLOW}Amostra do motor estatístico:${NC}"
python3 main.py --partida "Flamengo vs Palmeiras"

echo -e "\n${BLUE}======================================${NC}"
echo -e "${GREEN}  Setup concluído! Como iniciar:${NC}"
echo ""
echo -e "  ${YELLOW}# Ative o ambiente (em cada novo terminal):${NC}"
echo "  source .venv/bin/activate"
echo ""
echo -e "  ${YELLOW}# API REST  →  http://localhost:8000/docs${NC}"
echo "  python main.py --api"
echo ""
echo -e "  ${YELLOW}# Dashboard →  http://localhost:8501${NC}"
echo "  python main.py --dashboard"
echo ""
echo -e "  ${YELLOW}# Bot automático:${NC}"
echo "  python main.py --bot"
echo ""
echo -e "  ${YELLOW}# Testes:${NC}"
echo "  pytest"
echo ""
echo -e "  ${YELLOW}# Docker (todos os serviços):${NC}"
echo "  docker compose up --build"
echo -e "${BLUE}======================================${NC}"
