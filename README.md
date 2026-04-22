# ⚽ Futebol Elite — Sistema de Análise Estatística

> Plataforma completa de previsão probabilística para o futebol brasileiro,
> combinando Poisson bivariado, correção Dixon-Coles, xPoints e Monte Carlo
> em uma stack moderna: FastAPI + PostgreSQL + Streamlit.

---

## 🎯 O que o sistema faz

Para cada partida analisada, o sistema entrega:

| Métrica | Descrição |
|--------|-----------|
| **P(casa / empate / fora)** | Probabilidades calculadas pelo modelo Poisson |
| **λ (lambda)** | Gols esperados por time |
| **Placar mais provável** | Top 10 placares com percentual |
| **Matriz de resultados** | Heatmap 7×7 de todos os placares possíveis |
| **xPoints** | Pontos esperados — 3×P(W) + 1×P(D) |
| **BTTS** | Probabilidade de ambos os times marcarem |
| **Over 2.5** | Probabilidade de mais de 2 gols na partida |
| **Monte Carlo** | Validação cruzada com 10.000 simulações |

---

## 🔬 Modelos Estatísticos

### Poisson Bivariado
O número de gols de cada time é modelado como variável aleatória independente
com distribuição de Poisson. O parâmetro λ é calculado como:

```
λ_home = atk_home × def_away × LEAGUE_HOME_AVG × home_boost × context_factor
λ_away = atk_away × def_home × LEAGUE_AWAY_AVG × context_factor
```

Onde `atk` e `def` são fatores normalizados pela média da liga (1.0 = médio).

### Correção Dixon-Coles
Poisson subestima a frequência de placares baixos no futebol. A correção
Dixon-Coles aplica um fator τ nos placares 0-0, 1-0, 0-1 e 1-1:

```
τ(0,0) = 1 - λh × λa × ρ
τ(0,1) = 1 + λh × ρ
τ(1,0) = 1 + λa × ρ
τ(1,1) = 1 - ρ
```

O parâmetro `ρ = 0.12` é calibrado para o Brasileirão.

### xPoints
Métrica moderna de performance esperada:
```
xP_home = P(home) × 3 + P(draw) × 1
xP_away = P(away) × 3 + P(draw) × 1
```

### Monte Carlo
10.000 partidas simuladas via distribuição de Poisson com NumPy. Serve como
validação cruzada do modelo analítico — divergências > 2pp indicam edge cases.

---

## 🏗️ Arquitetura

```
futebol-elite/
│
├── model/                  # Motor estatístico
│   ├── engine.py           # Poisson + Dixon-Coles + Monte Carlo
│   └── data.py             # Dados: API Futebol, Football-Data.org, fallback
│
├── backend/                # API REST
│   ├── main.py             # FastAPI endpoints
│   ├── database.py         # SQLAlchemy (SQLite/PostgreSQL)
│   └── models.py           # ORM models
│
├── dashboard/
│   └── app.py              # Streamlit dashboard
│
├── bot/
│   └── scheduler.py        # Worker automático
│
├── data/                   # Cache local + resultados JSON
├── scripts/
│   └── setup.sh            # Setup rápido
│
├── main.py                 # CLI unificada
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## 🚀 Início Rápido

### Opção 1 — Local (recomendado para desenvolvimento)

```bash
# 1. Clone e entre no diretório
git clone https://github.com/seu-user/futebol-elite.git
cd futebol-elite

# 2. Setup automático
chmod +x scripts/setup.sh && ./scripts/setup.sh

# 3. Configure as chaves de API (opcional — funciona sem elas)
cp .env.example .env
# edite .env com seu editor favorito

# 4. Ative o ambiente
source .venv/bin/activate

# 5. Inicie
python main.py --api         # API em http://localhost:8000
python main.py --dashboard   # Dashboard em http://localhost:8501
python main.py --bot         # Worker automático
```

### Opção 2 — Docker (produção)

```bash
# Configure as variáveis de ambiente
cp .env.example .env

# Suba todos os serviços
docker compose up --build

# Serviços disponíveis:
#   http://localhost:8000       → API REST + docs interativos
#   http://localhost:8000/docs  → Swagger UI
#   http://localhost:8501       → Dashboard Streamlit
```

---

## 📡 API REST — Endpoints

### `GET /`
Health check com versão e timestamp.

### `GET /times`
Lista todos os times disponíveis.

### `GET /contextos`
Lista os contextos de jogo com fator multiplicador.

### `GET /stats/{time_nome}`
Estatísticas normalizadas de um time.

### `POST /analisar`
Analisa uma partida. Payload:
```json
{
  "home_team": "Flamengo",
  "away_team": "Palmeiras",
  "competition": "Brasileirão Série A",
  "context": "normal",
  "usar_monte_carlo": false
}
```

Resposta inclui probabilidades, lambdas, xPoints, BTTS, Over 2.5 e top placares.

### `POST /analisar/rodada`
Analisa todos os jogos da rodada atual via API de dados.

### `GET /previsoes?limit=50&time=Flamengo`
Histórico de previsões com filtro opcional por time.

### `GET /tabela/{campeonato_id}`
Tabela de classificação do campeonato.

---

## 🎲 CLI — Linha de Comando

```bash
# Análise interativa no terminal
python main.py

# Analisar partida específica
python main.py --partida "Flamengo vs Palmeiras"

# Listar todos os times com nível
python main.py --listar

# Analisar rodada atual e salvar JSON
python main.py --once

# Iniciar bot com análise diária (09:00 e 18:00)
python main.py --bot
```

---

## 🌐 Fontes de Dados

| Fonte | URL | Plano Gratuito |
|-------|-----|----------------|
| **API Futebol** | api-futebol.com.br | Sim (limitado) |
| **Football-Data.org** | football-data.org | Sim (Brasileirão BSA) |
| **Fallback local** | dados históricos calibrados | Sempre disponível |

O sistema funciona **100% offline** com os dados históricos calibrados embutidos,
cobrindo 25 times do Brasileirão Série A.

### Dados de fallback disponíveis
Flamengo, Palmeiras, Atlético-MG, Botafogo, Bragantino, Internacional,
São Paulo, Grêmio, Athletico-PR, Corinthians, Fortaleza, Cruzeiro,
Fluminense, Santos, Bahia, Vasco, Ceará, Goiás, América-MG, Sport,
Cuiabá, Coritiba, Juventude, Avaí, Chapecoense.

---

## ⚙️ Contextos de Jogo

O contexto aplica um fator multiplicador nos lambdas, simulando o impacto
tático de diferentes tipos de partida:

| Contexto | Fator | Uso |
|----------|-------|-----|
| `normal` | 1.00 | Rodada regular |
| `classico` | 0.95 | Derby estadual |
| `decisivo` | 0.90 | Mata-mata |
| `rebaixamento` | 0.87 | Luta contra Z4 |
| `titulo` | 0.93 | Disputa pelo título |
| `copa_brasil` | 0.92 | Copa do Brasil |
| `libertadores` | 0.88 | Copa Libertadores |

---

## 🗃️ Banco de Dados

O sistema suporta **SQLite** (dev) e **PostgreSQL** (produção).
Configure via variável `DATABASE_URL` no `.env`.

Tabela `previsoes` armazena:
- Times, competição, contexto
- Lambdas, probabilidades, xPoints
- BTTS, Over 2.5, placar mais provável
- Resultado real (para validação futura — backtesting)
- Timestamp de criação

---

## 🐳 Deploy em Produção

### Railway / Render / Fly.io
```bash
# Variáveis de ambiente necessárias:
DATABASE_URL=postgresql://...
API_FUTEBOL_KEY=...
FOOTBALL_DATA_KEY=...
```

### Heroku
```bash
heroku create futebol-elite
heroku addons:create heroku-postgresql:mini
heroku config:set API_FUTEBOL_KEY=seu_token
git push heroku main
```

---

## 📈 Roadmap

- [ ] ELO rating dinâmico atualizado após cada rodada
- [ ] Backtesting automático — comparar previsões com resultados reais
- [ ] Endpoint `/historico/precisao` — acurácia do modelo por período
- [ ] Suporte a Copa Libertadores e Sul-Americana
- [ ] Integração com Telegram Bot para alertas de jogos
- [ ] Interface mobile-first com React/Next.js
- [ ] API pública com rate limiting e autenticação JWT

---

## 📄 Licença

MIT — uso livre para fins educacionais e comerciais.

---

*Desenvolvido para análise estatística esportiva. Não tem finalidade de apostas.*
