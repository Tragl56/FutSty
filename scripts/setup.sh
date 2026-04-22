#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
# scripts/setup.sh — Configuração rápida para desenvolvimento local
# Uso: chmod +x scripts/setup.sh && ./scripts/setup.sh
# ─────────────────────────────────────────────────────────

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}"
echo "  ⚽  Futebol Elite — Setup"
echo "======================================${NC}"

# ── Python version check ────────────────
python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "${GREEN}✓ Python ${python_version} detectado${NC}"

# ── Virtual environment ─────────────────
if [ ! -d ".venv" ]; then
    echo -e "\n${YELLOW}Criando ambiente virtual...${NC}"
    python3 -m venv .venv
    echo -e "${GREEN}✓ .venv criado${NC}"
fi

source .venv/bin/activate
echo -e "${GREEN}✓ Ambiente virtual ativado${NC}"

# ── Instalar dependências ───────────────
echo -e "\n${YELLOW}Instalando dependências...${NC}"
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo -e "${GREEN}✓ Dependências instaladas${NC}"

# ── .env ───────────────────────────────
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo -e "${GREEN}✓ .env criado a partir de .env.example${NC}"
    echo -e "${YELLOW}  → Edite .env com suas chaves de API${NC}"
else
    echo -e "${GREEN}✓ .env já existe${NC}"
fi

# ── Diretório de dados ──────────────────
mkdir -p data
echo -e "${GREEN}✓ Diretório data/ criado${NC}"

# ── Teste rápido do motor ───────────────
echo -e "\n${YELLOW}Testando motor estatístico...${NC}"
python3 -c "
import sys; sys.path.insert(0, '.')
from model.engine import analisar_partida
from model.data import FALLBACK_STATS

r = analisar_partida(
    'Flamengo', 'Palmeiras',
    FALLBACK_STATS['Flamengo'],
    FALLBACK_STATS['Palmeiras'],
)
print(r.summary())
print('Motor OK ✓')
"
echo -e "${GREEN}✓ Motor estatístico funcionando${NC}"

echo -e "\n${BLUE}======================================${NC}"
echo -e "${GREEN}  Setup concluído! Como iniciar:${NC}"
echo ""
echo -e "  ${YELLOW}# API REST:${NC}"
echo "  source .venv/bin/activate"
echo "  python main.py --api"
echo ""
echo -e "  ${YELLOW}# Dashboard:${NC}"
echo "  source .venv/bin/activate"
echo "  python main.py --dashboard"
echo ""
echo -e "  ${YELLOW}# Bot automático:${NC}"
echo "  source .venv/bin/activate"
echo "  python main.py --bot"
echo ""
echo -e "  ${YELLOW}# Docker (todos os serviços):${NC}"
echo "  docker compose up --build"
echo -e "${BLUE}======================================${NC}"
