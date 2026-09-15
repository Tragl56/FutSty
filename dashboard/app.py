"""
dashboard/app.py — Dashboard interativo de análise de futebol.

Combina:
  - Visual rico com Plotly
  - Integração com a API REST FastAPI (persistência do histórico)
  - Monte Carlo, Dixon-Coles, xPoints, BTTS, Over 2.5
  - Exportação JSON

Rodar:
  streamlit run dashboard/app.py
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import API_BASE_URL, APP_NAME, DATA_DIR, VERSION
from model.data import (
    CONTEXT_DESCRIPTIONS,
    CONTEXT_FACTORS,
    FALLBACK_STATS,
    DataFetcher,
)
from model.engine import analisar_partida

VERDE, VERMELHO, CINZA, LARANJA = "#00C853", "#F44336", "#78909C", "#FF9800"
TRANSPARENTE = "rgba(0,0,0,0)"

# ──────────────────────────────────────────
# Config da página
# ──────────────────────────────────────────
st.set_page_config(
    page_title=f"{APP_NAME} — Análise BR",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  [data-testid="stMetricValue"] { font-size: 2.2rem !important; font-weight: 700; }
  .block-container { padding-top: 1rem; }
</style>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────
# Estado & dados
# ──────────────────────────────────────────
@st.cache_resource
def get_fetcher() -> DataFetcher:
    return DataFetcher()


fetcher = get_fetcher()
times_lista = fetcher.listar_times()


def indice_padrao(times: List[str], preferido: str, alternativa: int = 0) -> int:
    """
    Índice do time preferido, ou uma posição válida qualquer.

    `list.index()` direto levantava ValueError e derrubava o dashboard
    inteiro caso FALLBACK_STATS mudasse e o time sumisse da lista.
    """
    try:
        return times.index(preferido)
    except ValueError:
        return min(alternativa, max(len(times) - 1, 0))


def api_get(caminho: str, timeout: float = 3.0) -> Optional[dict]:
    """GET na API local. Devolve None quando a API está fora do ar."""
    try:
        resp = requests.get(f"{API_BASE_URL}{caminho}", timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


def api_post(caminho: str, payload: dict, timeout: float = 5.0) -> Optional[dict]:
    """POST na API local. Devolve None quando a API está fora do ar."""
    try:
        resp = requests.post(f"{API_BASE_URL}{caminho}", json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


# ──────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────
with st.sidebar:
    st.title(f"⚽ {APP_NAME}")
    st.caption(f"Modelo Poisson + Dixon-Coles · v{VERSION}")
    st.divider()

    st.subheader("⚔️ Configurar Partida")
    home_team = st.selectbox(
        "🏠 Mandante", times_lista, index=indice_padrao(times_lista, "Flamengo", 0)
    )
    away_team = st.selectbox(
        "✈️ Visitante", times_lista, index=indice_padrao(times_lista, "Palmeiras", 1)
    )

    st.divider()
    competicao = st.selectbox("🏆 Competição", [
        "Brasileirão Série A",
        "Brasileirão Série B",
        "Copa do Brasil",
        "Copa Libertadores",
        "Supercopa do Brasil",
        "Amistoso",
    ])

    contextos = list(CONTEXT_FACTORS)
    context = st.selectbox(
        "🎯 Contexto",
        contextos,
        format_func=lambda k: f"{k}  —  {CONTEXT_DESCRIPTIONS.get(k, '')}",
    )

    st.divider()
    usar_mc = st.checkbox("🎲 Simulação Monte Carlo (10k)", value=False)
    mostrar_matriz = st.checkbox("🔲 Mostrar matriz de resultados", value=True)

    st.divider()
    analisar = st.button("🔍 Analisar Partida", width="stretch", type="primary")

    st.divider()
    page = st.radio("📋 Navegação", ["Análise", "Times", "Histórico"], label_visibility="collapsed")

# ──────────────────────────────────────────
# Página: Times
# ──────────────────────────────────────────
if page == "Times":
    st.title("📊 Estatísticas dos Times")
    st.caption("Dados históricos calibrados — Brasileirão Série A (2019-2024)")

    df_times = pd.DataFrame([
        {
            "Time": t,
            "Força Ataque": d["forca_ataque"],
            "Fragilidade Defesa": d["fraqueza_defesa"],
            "Home Boost": d["home_boost"],
            "ELO": d.get("elo", 1500),
        }
        for t, d in sorted(FALLBACK_STATS.items(), key=lambda x: -x[1]["forca_ataque"])
    ])

    col1, col2 = st.columns(2)

    with col1:
        fig = px.bar(
            df_times.head(10), x="Time", y="Força Ataque",
            title="Top 10 — Força de Ataque",
            color="Força Ataque",
            color_continuous_scale="Greens",
            text="Força Ataque",
        )
        fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")
        fig.update_layout(height=380, showlegend=False, xaxis_tickangle=-30)
        st.plotly_chart(fig, width="stretch")

    with col2:
        fig2 = px.bar(
            df_times.sort_values("Fragilidade Defesa").head(10),
            x="Time", y="Fragilidade Defesa",
            title="Top 10 — Melhores Defesas (menor = melhor)",
            color="Fragilidade Defesa",
            color_continuous_scale="Reds_r",
            text="Fragilidade Defesa",
        )
        fig2.update_traces(texttemplate="%{text:.2f}", textposition="outside")
        fig2.update_layout(height=380, showlegend=False, xaxis_tickangle=-30)
        st.plotly_chart(fig2, width="stretch")

    fig3 = px.scatter(
        df_times,
        x="Força Ataque", y="Fragilidade Defesa",
        text="Time",
        title="Mapa Ataque × Defesa  (canto inferior direito = melhores times)",
        color="ELO",
        color_continuous_scale="Plasma",
        size="ELO",
        size_max=20,
    )
    fig3.update_traces(textposition="top center")
    fig3.update_layout(height=500)
    fig3.add_hline(y=1.0, line_dash="dot", line_color="gray", annotation_text="Média Defesa")
    fig3.add_vline(x=1.0, line_dash="dot", line_color="gray", annotation_text="Média Ataque")
    st.plotly_chart(fig3, width="stretch")

    st.dataframe(df_times, width="stretch", hide_index=True)
    st.stop()

# ──────────────────────────────────────────
# Página: Histórico
# ──────────────────────────────────────────
if page == "Histórico":
    st.title("📜 Histórico de Análises")

    dados = api_get("/previsoes?limit=100")
    previsoes = (dados or {}).get("previsoes", [])

    if previsoes:
        df_h = pd.DataFrame(previsoes)
        if "criado_em" in df_h:
            df_h["criado_em"] = pd.to_datetime(
                df_h["criado_em"], errors="coerce"
            ).dt.strftime("%d/%m %H:%M")

        cols_show = ["time_casa", "time_fora", "competicao", "prob_casa", "prob_empate",
                     "prob_fora", "placar_mais_provavel", "gols_esperados", "criado_em"]
        df_show = df_h[[c for c in cols_show if c in df_h.columns]]

        st.metric("Total de análises", dados.get("total", len(df_show)))
        st.dataframe(df_show, width="stretch", hide_index=True)
    elif dados is not None:
        st.info("Nenhuma análise registrada ainda. Gere uma análise na aba principal.")
    else:
        st.warning(
            f"API offline em {API_BASE_URL}. "
            "Inicie com `python main.py --api` para habilitar o histórico persistente."
        )

        arquivos = sorted(DATA_DIR.glob("resultados_*.json"), reverse=True)
        if arquivos:
            try:
                hist = json.loads(arquivos[0].read_text(encoding="utf-8"))
                st.caption(f"Exibindo arquivo local: {arquivos[0].name}")
                st.dataframe(pd.DataFrame(hist), width="stretch", hide_index=True)
            except (OSError, ValueError) as e:
                st.error(f"Não foi possível ler {arquivos[0].name}: {e}")

    st.stop()

# ──────────────────────────────────────────
# Página: Análise (principal)
# ──────────────────────────────────────────
if not analisar:
    st.title(f"⚽ {APP_NAME} — Análise Estatística")
    st.markdown("""
    Sistema de previsão probabilística para o futebol brasileiro, baseado em:

    | Modelo | Descrição |
    |--------|-----------|
    | **Poisson Bivariado** | Distribui probabilidade de gols independentemente por time |
    | **Dixon-Coles** | Corrige subrepresentação de placares baixos (0-0, 1-0, 0-1, 1-1) |
    | **xPoints** | Pontos esperados por partida — 3×P(W) + 1×P(D) |
    | **Monte Carlo** | Validação cruzada com 10.000 simulações |
    | **BTTS / Over 2.5** | Métricas de volume de gols |

    **Como usar:** Selecione os times na barra lateral e clique em **Analisar Partida**.
    """)

    with st.expander("📋 Times disponíveis"):
        st.dataframe(
            pd.DataFrame([
                {"Time": t, "Nível": fetcher.get_time_stats_formatado(t)["nivel"]}
                for t in times_lista
            ]),
            width="stretch",
            hide_index=True,
        )
    st.stop()

# ──────────────────────────────────────────
# Execução da análise
# ──────────────────────────────────────────
if home_team == away_team:
    st.error("⚠️ Selecione times diferentes.")
    st.stop()

with st.spinner("Calculando probabilidades..."):
    cf = CONTEXT_FACTORS.get(context, 1.0)
    resultado = analisar_partida(
        home_team=home_team,
        away_team=away_team,
        stats_home=fetcher.get_team_stats(home_team),
        stats_away=fetcher.get_team_stats(away_team),
        competition=competicao,
        context=context,
        context_factor=cf,
        usar_monte_carlo=usar_mc,
        mc_simulations=10_000,
    )

# O cálculo acima é local (instantâneo e funciona offline); a API é chamada
# apenas para gravar a previsão no histórico persistente.
persistido = api_post("/analisar", {
    "home_team": home_team,
    "away_team": away_team,
    "competition": competicao,
    "context": context,
    "usar_monte_carlo": usar_mc,
}) is not None

# ──────────────────────────────────────────
# Header do jogo
# ──────────────────────────────────────────
st.markdown(f"# {home_team}  ×  {away_team}")
st.caption(
    f"🏆 {competicao}  ·  🎯 Contexto: {context} (fator {cf:.2f})"
    f"  ·  🕐 {datetime.now():%d/%m/%Y %H:%M}"
    f"  ·  {'💾 salvo no histórico' if persistido else '⚠️ API offline — não salvo'}"
)
st.divider()

# ──────────────────────────────────────────
# Probabilidades principais
# ──────────────────────────────────────────
st.subheader("📊 Probabilidades")
c1, c2, c3 = st.columns(3)

is_home_fav = resultado.prob_home > resultado.prob_away
c1.metric(f"🏠 {home_team}", f"{resultado.prob_home:.1%}", delta="Favorito" if is_home_fav else None)
c2.metric("🤝 Empate",       f"{resultado.prob_draw:.1%}")
c3.metric(f"✈️ {away_team}", f"{resultado.prob_away:.1%}", delta="Favorito" if not is_home_fav else None)

probs = [resultado.prob_home, resultado.prob_draw, resultado.prob_away]
fig_prob = go.Figure(go.Bar(
    x=probs,
    y=[home_team, "Empate", away_team],
    orientation="h",
    marker_color=[VERDE, CINZA, VERMELHO],
    text=[f"{v:.1%}" for v in probs],
    textposition="auto",
    textfont=dict(size=14, color="white"),
))
fig_prob.update_layout(
    height=160,
    margin=dict(l=0, r=0, t=8, b=0),
    showlegend=False,
    xaxis=dict(showticklabels=False, range=[0, 1]),
    paper_bgcolor=TRANSPARENTE,
    plot_bgcolor=TRANSPARENTE,
)
st.plotly_chart(fig_prob, width="stretch")

st.divider()

# ──────────────────────────────────────────
# Métricas avançadas
# ──────────────────────────────────────────
st.subheader("📈 Métricas Avançadas")
m1, m2, m3, m4 = st.columns(4)
m1.metric("⚽ Gols Esperados (λ total)", f"{resultado.total_goals_expected:.2f}")
m2.metric("🎯 BTTS (ambos marcam)",      f"{resultado.btts_prob:.1%}")
m3.metric("📈 Over 2.5 gols",            f"{resultado.over_2_5_prob:.1%}")
m4.metric("🏠 λ Casa / ✈️ Fora",         f"{resultado.lambda_home:.2f} / {resultado.lambda_away:.2f}")

st.divider()

# ──────────────────────────────────────────
# λ e xPoints lado a lado
# ──────────────────────────────────────────
col_l, col_x = st.columns(2)


def barra_dupla(titulo: str, coluna: str, valores: List[float], y_range=None):
    df = pd.DataFrame({"Time": [home_team, away_team], coluna: valores})
    fig = px.bar(
        df, x="Time", y=coluna,
        color="Time",
        color_discrete_sequence=[VERDE, VERMELHO],
        text=coluna, height=260,
    )
    fig.update_traces(texttemplate="%{text:.2f}", textposition="outside")
    fig.update_layout(
        showlegend=False,
        margin=dict(t=10, b=10, l=0, r=0),
        yaxis=dict(range=y_range) if y_range else None,
        paper_bgcolor=TRANSPARENTE,
        plot_bgcolor=TRANSPARENTE,
    )
    st.subheader(titulo)
    st.plotly_chart(fig, width="stretch")


with col_l:
    barra_dupla("Gols Esperados (λ)", "λ", [resultado.lambda_home, resultado.lambda_away])

with col_x:
    barra_dupla(
        "xPoints (Pontos Esperados)", "xPoints",
        [resultado.xpoints_home, resultado.xpoints_away],
        y_range=[0, 3.2],
    )

st.divider()

# ──────────────────────────────────────────
# Placares mais prováveis + Matriz
# ──────────────────────────────────────────
col_s, col_m = st.columns([1, 2])

with col_s:
    st.subheader("🏅 Placares Mais Prováveis")
    scores_df = pd.DataFrame([
        {"Placar": s.label, "Prob (%)": round(s.prob * 100, 2)}
        for s in resultado.top_scores[:10]
    ])

    def destacar_primeiro(row):
        estilo = "background-color: #1b5e20; font-weight:bold" if row.name == 0 else ""
        return [estilo] * len(row)

    st.dataframe(
        scores_df.style.apply(destacar_primeiro, axis=1),
        width="stretch",
        hide_index=True,
        height=360,
    )

with col_m:
    if mostrar_matriz:
        st.subheader("🔲 Matriz de Resultados (%)")
        matriz = np.array(resultado.score_matrix)
        lado = min(7, matriz.shape[0])
        mx = matriz[:lado, :lado] * 100
        fig_h = px.imshow(
            mx,
            labels=dict(x=f"Gols {away_team}", y=f"Gols {home_team}", color="Prob (%)"),
            x=[str(i) for i in range(lado)],
            y=[str(i) for i in range(lado)],
            color_continuous_scale="YlGn",
            text_auto=".1f",
            aspect="auto",
            height=360,
        )
        fig_h.update_layout(margin=dict(t=20, b=10, l=0, r=0), paper_bgcolor=TRANSPARENTE)
        st.plotly_chart(fig_h, width="stretch")
        st.caption(
            f"Cada célula = P(placar). Diagonal = empates. "
            f"Triângulo inferior = vitória do mandante. "
            f"Exibindo 0–{lado - 1} gols de uma matriz {matriz.shape[0]}×{matriz.shape[1]}."
        )

st.divider()

# ──────────────────────────────────────────
# Monte Carlo
# ──────────────────────────────────────────
if usar_mc and resultado.mc_simulations > 0:
    st.subheader(f"🎲 Simulação Monte Carlo ({resultado.mc_simulations:,} partidas)")

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric(f"🏠 {home_team}", f"{resultado.mc_prob_home:.1%}")
    mc2.metric("🤝 Empate",       f"{resultado.mc_prob_draw:.1%}")
    mc3.metric(f"✈️ {away_team}", f"{resultado.mc_prob_away:.1%}")

    df_comp = pd.DataFrame({
        "Resultado":   [home_team, "Empate", away_team],
        "Poisson":     probs,
        "Monte Carlo": [resultado.mc_prob_home, resultado.mc_prob_draw, resultado.mc_prob_away],
    })
    fig_comp = px.bar(
        df_comp.melt(id_vars="Resultado", var_name="Modelo", value_name="Probabilidade"),
        x="Resultado", y="Probabilidade", color="Modelo",
        barmode="group",
        color_discrete_map={"Poisson": VERDE, "Monte Carlo": LARANJA},
        text_auto=".1%",
        height=300,
        title="Comparação: Poisson vs Monte Carlo",
    )
    fig_comp.update_layout(paper_bgcolor=TRANSPARENTE, plot_bgcolor=TRANSPARENTE)
    st.plotly_chart(fig_comp, width="stretch")
    st.caption(
        f"Divergência máxima Poisson × MC: {resultado.mc_max_divergencia:.1f}pp — "
        "as duas curvas descrevem a mesma distribuição, então o que sobra é "
        "apenas ruído de amostragem (~1/√n)."
    )
    st.divider()

# ──────────────────────────────────────────
# Exportar
# ──────────────────────────────────────────
st.subheader("⬇️ Exportar Análise")
export_data = {
    "versao_modelo":  VERSION,
    "partida":        f"{home_team} × {away_team}",
    "competicao":     competicao,
    "contexto":       context,
    "fator_contexto": cf,
    "lambda_home":    resultado.lambda_home,
    "lambda_away":    resultado.lambda_away,
    "probabilidades": {
        "casa":   resultado.prob_home,
        "empate": resultado.prob_draw,
        "fora":   resultado.prob_away,
    },
    "metricas": {
        "gols_esperados": resultado.total_goals_expected,
        "btts":           resultado.btts_prob,
        "over_25":        resultado.over_2_5_prob,
        "xpoints_home":   resultado.xpoints_home,
        "xpoints_away":   resultado.xpoints_away,
    },
    "top_scores": [{"placar": s.label, "prob": s.prob} for s in resultado.top_scores[:8]],
    "monte_carlo": {
        "simulacoes": resultado.mc_simulations,
        "prob_home":  resultado.mc_prob_home,
        "prob_draw":  resultado.mc_prob_draw,
        "prob_away":  resultado.mc_prob_away,
    } if resultado.mc_simulations > 0 else None,
    "gerado_em": datetime.now().isoformat(),
}


def nome_arquivo(time_a: str, time_b: str) -> str:
    """Nome de arquivo ASCII-safe, sem acento nem espaço."""
    from model.data import normalizar_nome
    return f"analise_{normalizar_nome(time_a)}_vs_{normalizar_nome(time_b)}.json"


st.download_button(
    "📥 Baixar JSON",
    data=json.dumps(export_data, ensure_ascii=False, indent=2),
    file_name=nome_arquivo(home_team, away_team),
    mime="application/json",
    width="stretch",
)
