"""持仓监控"""

import streamlit as st
import plotly.graph_objects as go

from duant.core.config import load_config
from duant.data.sqlite_store import SqliteStore


@st.cache_resource
def get_store() -> SqliteStore:
    config = load_config()
    return SqliteStore(config.data.db_path)


def render():
    st.title("持仓监控")

    store = get_store()
    positions = store.get_latest_positions()
    equity_df = store.get_equity_curve("backtest")

    total_value = 0
    if not equity_df.empty:
        total_value = equity_df.iloc[-1]["total_value"]

    if not positions:
        st.info("暂无持仓")
        return

    # 持仓表格
    pos_data = []
    for p in positions:
        pnl_pct = (p.current_price - p.avg_price) / p.avg_price if p.avg_price > 0 else 0
        pos_data.append({
            "标的": p.symbol,
            "市场": p.market.value,
            "数量": p.quantity,
            "均价": round(p.avg_price, 2),
            "现价": round(p.current_price, 2),
            "市值": round(p.market_value, 2),
            "盈亏": round(p.unrealized_pnl, 2),
            "盈亏%": f"{pnl_pct:.2%}",
            "占比": f"{p.market_value / total_value:.1%}" if total_value > 0 else "0%",
        })

    st.dataframe(pos_data, use_container_width=True, hide_index=True)

    # 仓位占比饼图
    st.subheader("仓位占比")
    labels = [p.symbol for p in positions]
    values = [p.market_value for p in positions]
    cash_amount = total_value - sum(values) if total_value > 0 else 0
    if cash_amount > 0:
        labels.append("现金")
        values.append(cash_amount)

    fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.4)])
    fig.update_layout(height=400, margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)

    # 盈亏柱状图
    st.subheader("个股盈亏")
    symbols = [p.symbol for p in positions]
    pnls = [p.unrealized_pnl for p in positions]
    colors = ["#4CAF50" if p >= 0 else "#F44336" for p in pnls]

    fig2 = go.Figure(data=[go.Bar(x=symbols, y=pnls, marker_color=colors)])
    fig2.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
    fig2.add_hline(y=0, line_dash="dash", line_color="gray")
    st.plotly_chart(fig2, use_container_width=True)


render()
