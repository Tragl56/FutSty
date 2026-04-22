"""
dashboard/app.py — Dashboard interativo de análise de futebol.

Combina:
  - Visual rico com Plotly (proj2)
  - Integração com API REST FastAPI (proj1)
  - Monte Carlo, Dixon-Coles, xPoints, BTTS, Over 2.5
  - Exportação JSON

Rodar:
  streamlit run dashboard/app.py
"""

import json
import sys
import requests
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from model.data import DataFetcher, CONTEXT_FACTORS, CONTEXT_DESCRIPTIONS, FALLBACK_STATS
from model.engine import analisar_partida

# ──────────────────────────────────────────
# Config da página
# ──────────────────────────────────────────
st.set_page_config(
    page_title="Futebol Elite — Análise BR",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  [data-testid="stMetricValue"] { font-size: 2.2rem !important; font-weight: 700; }
  .block-container { padding-top: 1rem; }
  .metric-hero { text-align: center; padding: 1rem 0; }
  .verde  { color: #00C853; }
  .vermelho { color: #F44336; }
  .cinza  { color: #9E9E9E; }
  div[data-testid="metric-container"] { background: #1a1a2e; border-radius: 10px; padding: 12px; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────
# Estado & dados
# ──────────────────────────────────────────
@st.cache_resource
def get_fetcher():
    return DataFetcher()

fetcher = get_fetcher()
times_lista = fetcher.listar_times()

# ──────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/football2.png", width=60)
    st.title("Futebol Elite")
    st.caption("Modelo Poisson + Dixon-Coles")
    st.divider()

    st.subheader("⚔️ Configurar Partida")
    home_team = st.selectbox("🏠 Mandante", times_lista, index=times_lista.index("Flamengo"))
    away_team = st.selectbox("✈️ Visitante", times_lista, index=times_lista.index("Palmeiras"))

    st.divider()
    competicao = st.selectbox("🏆 Competição", [
        "Brasileirão Série A",
        "Brasileirão Série B",
        "Copa do Brasil",
        "Copa Libertadores",
        "Supercopa do Brasil",
        "Amistoso",
    ])

    context_labels = {k: f"{k}  —  {CONTEXT_DESCRIPTIONS[k]}" for k in CONTEXT_FACTORS}
    context_sel = st.selectbox("🎯 Contexto", list(context_labels.values()))
    context = [k for k, v in context_labels.items() if v == context_sel][0]

    st.divider()
    usar_mc = st.checkbox("🎲 Simulação Monte Carlo (10k)", value=False)
    mostrar_matriz = st.checkbox("🔲 Mostrar matriz de resultados", value=True)

    st.divider()
    analisar = st.button("🔍 Analisar Partida", use_container_width=True, type="primary")

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
        st.plotly_chart(fig, use_container_width=True)

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
        st.plotly_chart(fig2, use_container_width=True)

    fig3 = px.scatter(
        df_times,
        x="Força Ataque", y="Fragilidade Defesa",
        text="Time",
        title="Mapa Ataque × Defesa",
        color="ELO",
        color_continuous_scale="Plasma",
        size="ELO",
        size_max=20,
    )
    fig3.update_traces(textposition="top center")
    fig3.update_layout(height=500)
    # Linhas de média
    fig3.add_hline(y=1.0, line_dash="dot", line_color="gray", annotation_text="Média Defesa")
    fig3.add_vline(x=1.0, line_dash="dot", line_color="gray", annotation_text="Média Ataque")
    st.plotly_chart(fig3, use_container_width=True)

    st.dataframe(df_times, use_container_width=True, hide_index=True)
    st.stop()

# ──────────────────────────────────────────
# Página: Histórico
# ──────────────────────────────────────────
if page == "Histórico":
    st.title("📜 Histórico de Análises")

    try:
        resp = requests.get("http://127.0.0.1:8000/previsoes?limit=100", timeout=3)
        data = resp.json()
        previsoes = data.get("previsoes", [])

        if previsoes:
            df_h = pd.DataFrame(previsoes)
            df_h["criado_em"] = pd.to_datetime(df_h["criado_em"]).dt.strftime("%d/%m %H:%M")

            cols_show = ["time_casa", "time_fora", "competicao", "prob_casa", "prob_empate",
                         "prob_fora", "placar_mais_provavel", "gols_esperados", "criado_em"]
            df_show = df_h[[c for c in cols_show if c in df_h.columns]]

            st.metric("Total de análises", len(df_show))
            st.dataframe(df_show, use_container_width=True, hide_index=True)
        else:
            st.info("Nenhuma análise registrada ainda. Gere uma análise na aba principal.")
    except Exception:
        st.warning("API offline. Execute `uvicorn backend.main:app` para habilitar histórico persistente.")

        data_files = sorted(Path(ROOT / "data").glob("resultados_*.json"), reverse=True)
        if data_files:
            with open(data_files[0]) as f:
                hist = json.load(f)
            st.caption(f"Exibindo arquivo: {data_files[0].name}")
            st.dataframe(pd.DataFrame(hist), use_container_width=True, hide_index=True)

    st.stop()

# ──────────────────────────────────────────
# Página: Análise (principal)
# ──────────────────────────────────────────
if not analisar:
    st.title("⚽ Futebol Elite — Análise Estatística")
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
        times_df = pd.DataFrame([
            {"Time": t, "Nível": fetcher.get_time_stats_formatado(t)["nivel"]}
            for t in times_lista
        ])
        st.dataframe(times_df, use_container_width=True, hide_index=True)
    st.stop()

# ──────────────────────────────────────────
# Execução da análise
# ──────────────────────────────────────────
if home_team == away_team:
    st.error("⚠️ Selecione times diferentes.")
    st.stop()

with st.spinner("Calculando probabilidades..."):
    stats_home = fetcher.get_team_stats(home_team)
    stats_away = fetcher.get_team_stats(away_team)
    cf = CONTEXT_FACTORS.get(context, 1.0)

    resultado = analisar_partida(
        home_team=home_team,
        away_team=away_team,
        stats_home=stats_home,
        stats_away=stats_away,
        competition=competicao,
        context=context,
        context_factor=cf,
        usar_monte_carlo=usar_mc,
        mc_simulations=10_000,
    )

# Tenta persistir na API
try:
    requests.post("http://127.0.0.1:8000/analisar", json={
        "home_team": home_team,
        "away_team": away_team,
        "competition": competicao,
        "context": context,
        "usar_monte_carlo": usar_mc,
    }, timeout=2)
except Exception:
    pass

# ──────────────────────────────────────────
# Header do jogo
# ──────────────────────────────────────────
st.markdown(f"# {home_team}  ×  {away_team}")
st.caption(f"🏆 {competicao}  ·  🎯 Contexto: {context}  ·  🕐 {datetime.now():%d/%m/%Y %H:%M}")
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

# Barra horizontal de probabilidades
fig_prob = go.Figure(go.Bar(
    x=[resultado.prob_home, resultado.prob_draw, resultado.prob_away],
    y=[home_team, "Empate", away_team],
    orientation="h",
    marker_color=["#00C853", "#78909C", "#F44336"],
    text=[f"{v:.1%}" for v in [resultado.prob_home, resultado.prob_draw, resultado.prob_away]],
    textposition="auto",
    textfont=dict(size=14, color="white"),
))
fig_prob.update_layout(
    height=160,
    margin=dict(l=0, r=0, t=8, b=0),
    showlegend=False,
    xaxis=dict(showticklabels=False, range=[0, 1]),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
)
st.plotly_chart(fig_prob, use_container_width=True)

st.divider()

# ──────────────────────────────────────────
# Métricas avançadas
# ──────────────────────────────────────────
st.subheader("📈 Métricas Avançadas")
m1, m2, m3, m4 = st.columns(4)
m1.metric("⚽ Gols Esperados (λ total)",   f"{resultado.total_goals_expected:.2f}")
m2.metric("🎯 BTTS (ambos marcam)",         f"{resultado.btts_prob:.1%}")
m3.metric("📈 Over 2.5 gols",               f"{resultado.over_2_5_prob:.1%}")
m4.metric("🏠 λ Casa / ✈️ Fora",            f"{resultado.lambda_home:.2f} / {resultado.lambda_away:.2f}")

st.divider()

# ──────────────────────────────────────────
# λ e xPoints lado a lado
# ──────────────────────────────────────────
col_l, col_x = st.columns(2)

with col_l:
    st.subheader("Gols Esperados (λ)")
    df_lmb = pd.DataFrame({
        "Time": [home_team, away_team],
        "λ":    [resultado.lambda_home, resultado.lambda_away],
    })
    fig_l = px.bar(
        df_lmb, x="Time", y="λ",
        color="Time",
        color_discrete_sequence=["#00C853", "#F44336"],
        text="λ", height=260,
    )
    fig_l.update_traces(texttemplate="%{text:.2f}", textposition="outside")
    fig_l.update_layout(showlegend=False, margin=dict(t=10, b=10, l=0, r=0),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_l, use_container_width=True)

with col_x:
    st.subheader("xPoints (Pontos Esperados)")
    df_xp = pd.DataFrame({
        "Time":    [home_team, away_team],
        "xPoints": [resultado.xpoints_home, resultado.xpoints_away],
    })
    fig_x = px.bar(
        df_xp, x="Time", y="xPoints",
        color="Time",
        color_discrete_sequence=["#00C853", "#F44336"],
        text="xPoints", height=260,
    )
    fig_x.update_traces(texttemplate="%{text:.2f}", textposition="outside")
    fig_x.update_layout(showlegend=False, margin=dict(t=10, b=10, l=0, r=0),
                        yaxis=dict(range=[0, 3.2]),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_x, use_container_width=True)

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
    # Destaque para o mais provável
    def highlight_top(row):
        if row.name == 0:
            return ["background-color: #1b5e20; font-weight:bold"] * len(row)
        return [""] * len(row)
    st.dataframe(
        scores_df.style.apply(highlight_top, axis=1),
        use_container_width=True,
        hide_index=True,
        height=360,
    )

with col_m:
    if mostrar_matriz:
        st.subheader("🔲 Matriz de Resultados (%)")
        mx = np.array(resultado.score_matrix)[:7, :7] * 100
        fig_h = px.imshow(
            mx,
            labels=dict(
                x=f"Gols {away_team}",
                y=f"Gols {home_team}",
                color="Prob (%)",
            ),
            x=[str(i) for i in range(7)],
            y=[str(i) for i in range(7)],
            color_continuous_scale="YlGn",
            text_auto=".1f",
            aspect="auto",
            height=360,
        )
        fig_h.update_layout(
            margin=dict(t=20, b=10, l=0, r=0),
            paper_bgcolor="rgba(0,0,0,0)",
        )
        st.plotly_chart(fig_h, use_container_width=True)
        st.caption("Cada célula = P(placar). Diagonal = empates. Triângulo inferior = vitória do mandante.")

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

    # Comparação Poisson × Monte Carlo
    diff_h = abs(resultado.prob_home - resultado.mc_prob_home) * 100
    diff_d = abs(resultado.prob_draw - resultado.mc_prob_draw) * 100
    diff_a = abs(resultado.prob_away - resultado.mc_prob_away) * 100

    df_comp = pd.DataFrame({
        "Resultado":   [home_team, "Empate", away_team],
        "Poisson":     [resultado.prob_home, resultado.prob_draw, resultado.prob_away],
        "Monte Carlo": [resultado.mc_prob_home, resultado.mc_prob_draw, resultado.mc_prob_away],
    })
    fig_comp = px.bar(
        df_comp.melt(id_vars="Resultado", var_name="Modelo", value_name="Probabilidade"),
        x="Resultado", y="Probabilidade", color="Modelo",
        barmode="group",
        color_discrete_map={"Poisson": "#00C853", "Monte Carlo": "#FF9800"},
        text_auto=".1%",
        height=300,
        title="Comparação: Poisson vs Monte Carlo",
    )
    fig_comp.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig_comp, use_container_width=True)
    st.caption(f"Divergência máxima Poisson × MC: {max(diff_h, diff_d, diff_a):.1f}pp")
    st.divider()

# ──────────────────────────────────────────
# Exportar
# ──────────────────────────────────────────
st.subheader("⬇️ Exportar Análise")
export_data = {
    "partida":          f"{home_team} × {away_team}",
    "competicao":       competicao,
    "contexto":         context,
    "fator_contexto":   cf,
    "lambda_home":      resultado.lambda_home,
    "lambda_away":      resultado.lambda_away,
    "probabilidades": {
        "casa":    resultado.prob_home,
        "empate":  resultado.prob_draw,
        "fora":    resultado.prob_away,
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
        "simulacoes":  resultado.mc_simulations,
        "prob_home":   resultado.mc_prob_home,
        "prob_draw":   resultado.mc_prob_draw,
        "prob_away":   resultado.mc_prob_away,
    } if resultado.mc_simulations > 0 else None,
    "gerado_em": datetime.now().isoformat(),
}

safe_home = home_team.lower().replace(" ", "_").replace("-", "")
safe_away = away_team.lower().replace(" ", "_").replace("-", "")

st.download_button(
    "📥 Baixar JSON",
    data=json.dumps(export_data, ensure_ascii=False, indent=2),
    file_name=f"analise_{safe_home}_vs_{safe_away}.json",
    mime="application/json",
    use_container_width=True,
)
