"""仪表盘"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path

from duant.core.config import load_config
from duant.data.sqlite_store import SqliteStore
from duant.strategy.loader import StrategyLoader


@st.cache_resource
def get_store() -> SqliteStore:
    config = load_config()
    return SqliteStore(config.data.db_path)


def _list_strategies() -> list[str]:
    try:
        config = load_config()
        project_root = Path.cwd()
        loader = StrategyLoader(
            yaml_dir=project_root / "config" / "strategies",
            python_dir=project_root / "strategies",
        )
        return list(loader.list_strategies().keys())
    except Exception:
        return []


def render():
    st.title("仪表盘")

    store = get_store()

    # 获取最近净值数据
    equity_df = store.get_equity_curve("backtest")
    latest_positions = store.get_latest_positions()
    recent_trades = store.get_trades()
    risk_events = store.get_risk_events()

    # === 指标卡 ===
    col1, col2, col3, col4 = st.columns(4)

    if not equity_df.empty:
        latest = equity_df.iloc[-1]
        total_value = latest["total_value"]
        cash = latest["cash"]

        if len(equity_df) >= 2:
            prev = equity_df.iloc[-2]
            daily_pnl_pct = (latest["total_value"] - prev["total_value"]) / prev["total_value"] if prev["total_value"] > 0 else 0
        else:
            daily_pnl_pct = 0
    else:
        total_value = 0
        cash = 0
        daily_pnl_pct = 0

    with col1:
        st.metric("总资产", f"¥{total_value:,.0f}")
    with col2:
        delta_str = f"{daily_pnl_pct:+.2%}"
        st.metric("今日盈亏", delta_str, delta=f"{daily_pnl_pct:+.2%}")
    with col3:
        st.metric("持仓数", len(latest_positions))
    with col4:
        running_strategies = 0
        strategy_names = _list_strategies()
        for name in strategy_names:
            state = store.get_strategy_state(name)
            if state and state.get("status") == "running":
                running_strategies += 1
        st.metric("运行中策略", running_strategies)

    # === 收益曲线 ===
    st.subheader("收益曲线")
    if not equity_df.empty and len(equity_df) > 1:
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            row_heights=[0.7, 0.3],
            vertical_spacing=0.05,
        )

        fig.add_trace(
            go.Scatter(
                x=equity_df["date"],
                y=equity_df["total_value"],
                name="总资产",
                line=dict(color="#2196F3", width=2),
            ),
            row=1, col=1,
        )

        # 回撤曲线
        values = equity_df["total_value"].values
        peak = values[0]
        drawdowns = []
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            drawdowns.append(-dd)

        fig.add_trace(
            go.Scatter(
                x=equity_df["date"],
                y=drawdowns,
                name="回撤",
                fill="tozeroy",
                line=dict(color="#F44336", width=1),
            ),
            row=2, col=1,
        )

        fig.update_layout(
            height=500,
            showlegend=True,
            margin=dict(l=20, r=20, t=20, b=20),
        )
        fig.update_yaxes(title_text="资产", row=1, col=1)
        fig.update_yaxes(title_text="回撤", row=2, col=1, tickformat=".0%")

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("暂无净值数据，请先运行回测")

    # === 持仓概览 ===
    st.subheader("持仓概览")
    if latest_positions:
        pos_data = []
        for p in latest_positions:
            pos_data.append({
                "标的": p.symbol,
                "数量": p.quantity,
                "均价": f"¥{p.avg_price:.2f}",
                "现价": f"¥{p.current_price:.2f}",
                "市值": f"¥{p.market_value:,.0f}",
                "盈亏": f"¥{p.unrealized_pnl:,.0f}",
                "占比": f"{p.market_value / total_value:.1%}" if total_value > 0 else "0%",
            })
        st.dataframe(pos_data, use_container_width=True, hide_index=True)
    else:
        st.info("暂无持仓")

    # === 最近交易 ===
    st.subheader("最近交易")
    if recent_trades:
        trade_data = []
        for t in recent_trades[-10:]:
            trade_data.append({
                "时间": t.traded_at.strftime("%Y-%m-%d %H:%M"),
                "标的": t.symbol,
                "方向": t.side.value,
                "价格": f"¥{t.price:.2f}",
                "数量": t.amount,
                "手续费": f"¥{t.commission:.2f}",
            })
        st.dataframe(trade_data, use_container_width=True, hide_index=True)
    else:
        st.info("暂无交易记录")

    # === 风控事件 ===
    if risk_events:
        st.subheader("风控事件")
        event_data = []
        for e in risk_events[:10]:
            level_icon = "🔴" if e.level.value == "account" else "🟡"
            event_data.append({
                "": level_icon,
                "时间": e.created_at.strftime("%Y-%m-%d %H:%M"),
                "规则": e.rule_name,
                "动作": e.action.value,
                "标的": e.symbol or "-",
                "详情": e.detail,
            })
        st.dataframe(event_data, use_container_width=True, hide_index=True)


render()
