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
| **Matriz de resultados** | Heatmap de todos os placares possíveis |
| **xPoints** | Pontos esperados — 3×P(W) + 1×P(D) |
| **BTTS** | Probabilidade de ambos os times marcarem |
| **Over 2.5** | Probabilidade de mais de 2 gols na partida |
| **Monte Carlo** | Validação cruzada com 10.000 simulações |

Todas essas métricas saem de **uma única** matriz de placares, corrigida e
normalizada uma só vez. Ou seja: o número que aparece no heatmap é o mesmo
que alimenta as barras de probabilidade, o BTTS e o Monte Carlo.

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
Os λ são limitados a `[0.05, 6.0]` para evitar matrizes degeneradas e outliers.

O tamanho da matriz é adaptativo (μ + 5σ, mínimo 9×9, máximo 16×16), de modo
que a truncagem descarte menos de 1% da massa de probabilidade mesmo com λ alto.

### Correção Dixon-Coles
Poisson trata os dois placares como independentes. A correção Dixon-Coles
aplica um fator τ nos quatro placares baixos:

```
τ(0,0) = 1 - λh × λa × ρ
τ(0,1) = 1 + λh × ρ
τ(1,0) = 1 + λa × ρ
τ(1,1) = 1 - ρ
```

**Atenção ao sinal de ρ** — ele é contraintuitivo:

| ρ | Efeito |
|---|--------|
| **ρ < 0** | Infla 0-0 e 1-1, reduz 1-0 e 0-1. É o sinal estimado por Dixon & Coles (1997) para dados reais (ρ̂ ≈ -0.13) e corresponde a "Poisson subestima empates de placar baixo". |
| **ρ > 0** | Faz exatamente o contrário: reduz 0-0 e 1-1, aumenta 1-0 e 0-1. |

O projeto usa **ρ = +0.12**, ou seja, hoje o modelo *reduz* 0-0 e 1-1.
Se a intenção era inflar empates de placar baixo, troque `RHO` para `-0.12`
em `model/engine.py`. O valor atual foi mantido para não alterar previsões
já calibradas — a decisão é sua.

Para qualquer λ, ρ é automaticamente limitado a
`max(-1/λh, -1/λa) ≤ ρ ≤ min(1, 1/(λh·λa))`, a faixa em que τ continua
gerando probabilidades não-negativas.

### Correção de empates
Um fator `DRAW_CORRECTION = 1.10` é aplicado à **diagonal da matriz** (e não
apenas ao resultado 1X2), antes da normalização final. Isso mantém placares,
BTTS, Over 2.5 e Monte Carlo coerentes com as probabilidades publicadas.

### xPoints
Métrica moderna de performance esperada:
```
xP_home = P(home) × 3 + P(draw) × 1
xP_away = P(away) × 3 + P(draw) × 1
```

### Monte Carlo
10.000 partidas amostradas **da matriz corrigida** — não de duas Poisson
independentes. Amostrar Poisson cru compararia dois modelos diferentes e
produziria uma divergência sistemática nos empates que nada tem a ver com
erro numérico. Com a amostragem correta, o que sobra é apenas ruído de
amostragem (~1/√n), tipicamente < 0.5pp com 10k simulações.

Use `mc_seed=None` para amostragem verdadeiramente aleatória; o padrão é
uma seed fixa, para resultados reprodutíveis.

---

## 🏗️ Arquitetura

```
futebol-elite/
│
├── config.py               # Configuração central — único lugar que lê o ambiente
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
├── tests/                  # Suíte pytest (motor, dados, API, CLI, worker)
│
├── data/                   # Cache local + resultados JSON
├── scripts/
│   └── setup.sh            # Setup rápido
│
├── main.py                 # CLI unificada
├── requirements.txt
├── requirements-dev.txt
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

# 2. Setup automático (cria venv, instala tudo e roda os testes)
chmod +x scripts/setup.sh && ./scripts/setup.sh

# 3. Ative o ambiente
source .venv/bin/activate

# 4. Inicie
python main.py --api         # API em http://localhost:8000
python main.py --dashboard   # Dashboard em http://localhost:8501
python main.py --bot         # Worker automático
```

As chaves de API são **opcionais** — sem elas o sistema roda 100% offline
com os dados históricos calibrados.

### Opção 2 — Docker (produção)

```bash
# Configure as variáveis de ambiente (opcional)
cp .env.example .env

# Suba todos os serviços
docker compose up --build

# Serviços disponíveis:
#   http://localhost:8000       → API REST
#   http://localhost:8000/docs  → Swagger UI
#   http://localhost:8501       → Dashboard Streamlit
```

---

## 🧪 Testes

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest                      # suíte completa
pytest tests/test_engine.py # só o motor estatístico
pytest -v                   # detalhado
```

A suíte cobre o motor (normalização, limites de λ e ρ, coerência entre
matriz e 1X2, convergência do Monte Carlo), a camada de dados (resolução de
nomes, cache, normalização das APIs), todos os endpoints da API, a CLI e o
worker. Os testes usam banco e cache temporários — nada toca seus dados locais.

---

## 📡 API REST — Endpoints

### `GET /`
Health check com versão e timestamp.

### `GET /times`
Lista todos os times disponíveis.

### `GET /contextos`
Lista os contextos de jogo com fator multiplicador.

### `GET /stats/{time_nome}`
Estatísticas normalizadas de um time. Retorna **404** se o time não existir.

### `POST /analisar`
Analisa uma partida. Payload:
```json
{
  "home_team": "Flamengo",
  "away_team": "Palmeiras",
  "competition": "Brasileirão Série A",
  "context": "normal",
  "usar_monte_carlo": false,
  "mc_simulations": 10000
}
```

Resposta inclui probabilidades, lambdas, xPoints, BTTS, Over 2.5 e top placares.

### `POST /analisar/rodada`
Analisa todos os jogos da rodada atual via API de dados.

### `GET /previsoes?limit=50&offset=0&time=Flamengo`
Histórico paginado de previsões, com filtro opcional por time.

### `GET /tabela/{campeonato_id}`
Tabela de classificação do campeonato.

---

## 🎲 CLI — Linha de Comando

```bash
# Análise interativa no terminal
python main.py

# Analisar partida específica (aceita vs / x / × / v)
python main.py --partida "Flamengo vs Palmeiras"
python main.py --partida "sao paulo x corinthians" --context classico

# Listar todos os times com nível
python main.py --listar

# Analisar rodada atual e salvar JSON
python main.py --once --monte-carlo

# Iniciar bot com análise diária
python main.py --bot
```

### Nomes de times tolerantes
Acento, caixa e grafia das APIs são resolvidos automaticamente:

```
"flamengo", "CR Flamengo", "FLAMENGO"          → Flamengo
"atletico-mg", "Clube Atlético Mineiro"        → Atlético-MG
"Atlético-PR", "CA Paranaense"                 → Athletico-PR
"sao paulo", "São Paulo FC"                    → São Paulo
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

## 🔧 Configuração

Todas as variáveis de ambiente são lidas em `config.py`, que carrega o `.env`
automaticamente. Veja `.env.example` para a lista completa. As principais:

| Variável | Padrão | Para quê |
|----------|--------|----------|
| `DATABASE_URL` | `sqlite:///./futebol_elite.db` | Banco (SQLite ou PostgreSQL) |
| `API_BASE_URL` | `http://127.0.0.1:8000` | Como dashboard e bot acham a API |
| `API_FUTEBOL_KEY` | — | Chave da API Futebol |
| `FOOTBALL_DATA_KEY` | — | Chave do Football-Data.org |
| `CACHE_TTL_HOURS` | `6` | Validade do cache local |
| `CORS_ORIGINS` | `*` | Origens permitidas na API |
| `BOT_SCHEDULE_TIMES` | `09:00,18:00` | Horários da análise automática |
| `BOT_KEEP_RESULTS` | `30` | Quantos JSONs de rodada manter |
| `LOG_LEVEL` | `INFO` | Verbosidade dos logs |

> No Docker Compose, `API_BASE_URL` precisa ser `http://api:8000` — containers
> não enxergam `127.0.0.1` uns dos outros. O compose já faz isso por você.

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
CORS_ORIGINS=https://seu-dominio.com
ENV=production
```

### Heroku
```bash
heroku create futebol-elite
heroku addons:create heroku-postgresql:mini
heroku config:set API_FUTEBOL_KEY=seu_token
git push heroku main
```

`DATABASE_URL` no esquema legado `postgres://` é convertido automaticamente.

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
