"""回测中心"""

import io
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from duant.core.config import load_config
from duant.core.event import Market, TimeFrame
from duant.backtest.engine import BacktestEngine
from duant.backtest.report import BacktestResult
from duant.strategy.loader import StrategyLoader
from pathlib import Path


@st.cache_resource
def get_config():
    return load_config()


@st.cache_data
def list_strategies() -> list[str]:
    config = get_config()
    project_root = Path.cwd()
    loader = StrategyLoader(
        yaml_dir=project_root / "config" / "strategies",
        python_dir=project_root / "strategies",
    )
    return list(loader.list_strategies().keys())


def render():
    st.title("回测中心")

    config = get_config()

    # === 配置区 ===
    with st.form("backtest_config"):
        col1, col2, col3 = st.columns(3)

        with col1:
            strategies = list_strategies()
            strategy = st.selectbox("策略", strategies if strategies else ["ma_cross"])

        with col2:
            symbol = st.text_input("标的代码", value="000001.SZ")

        with col3:
            timeframe = st.selectbox("K线周期", ["1d", "1h", "15m", "5m", "1m"], index=0)

        col4, col5, col6 = st.columns(3)

        with col4:
            default_start = (datetime.now() - timedelta(days=365 * 3)).strftime("%Y-%m-%d")
            start = st.date_input("开始日期", value=datetime.strptime(default_start, "%Y-%m-%d"))

        with col5:
            end = st.date_input("结束日期", value=datetime.now())

        with col6:
            cash = st.number_input("初始资金", value=1_000_000, min_value=10_000, step=100_000)

        market = st.selectbox("市场", ["a_stock", "crypto"], index=0)

        submitted = st.form_submit_button("运行回测", type="primary")

    if submitted:
        _run_backtest(strategy, symbol, timeframe, start, end, cash, market, config)


def _run_backtest(strategy_name, symbol, timeframe, start, end, cash, market, config):
    with st.spinner("回测运行中..."):
        try:
            project_root = Path.cwd()
            loader = StrategyLoader(
                yaml_dir=project_root / "config" / "strategies",
                python_dir=project_root / "strategies",
            )
            strategy = loader.load(strategy_name)

            bt_config = config.backtest
            bt_config.initial_cash = cash

            engine = BacktestEngine(bt_config, data_path=config.data.data_path)
            result = engine.run(
                strategy=strategy,
                symbols=[symbol],
                start=datetime.combine(start, datetime.min.time()),
                end=datetime.combine(end, datetime.min.time()),
                market=Market(market),
                timeframe=TimeFrame(timeframe),
            )

            st.session_state["backtest_result"] = result
            st.success("回测完成!")

        except Exception as e:
            st.error(f"回测失败: {e}")
            return

    result = st.session_state.get("backtest_result")
    if result:
        _render_result(result, symbol)


def _render_result(result: BacktestResult, symbol: str):
    # === 指标卡 ===
    st.subheader("回测结果")
    m = result.metrics

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总收益率", f"{m.total_return:.2%}")
    with col2:
        st.metric("年化收益率", f"{m.annual_return:.2%}")
    with col3:
        st.metric("最大回撤", f"{m.max_drawdown:.2%}")
    with col4:
        st.metric("夏普比率", f"{m.sharpe_ratio:.2f}")

    col5, col6, col7 = st.columns(3)
    with col5:
        st.metric("胜率", f"{m.win_rate:.2%}")
    with col6:
        st.metric("盈亏比", f"{m.profit_loss_ratio:.2f}")
    with col7:
        st.metric("交易次数", f"{m.trade_count}")

    # === 收益曲线 ===
    st.subheader("收益与回撤曲线")
    equity = result.equity_curve
    if not equity.empty and len(equity) > 1:
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            row_heights=[0.7, 0.3],
            vertical_spacing=0.05,
        )

        # 总资产曲线
        fig.add_trace(
            go.Scatter(
                x=equity.index if "date" not in equity.columns else equity["date"],
                y=equity["total_value"] if "total_value" in equity.columns else equity.iloc[:, 0],
                name="总资产",
                line=dict(color="#2196F3", width=2),
            ),
            row=1, col=1,
        )

        # 回撤
        if "total_value" in equity.columns:
            values = equity["total_value"].values
        else:
            values = equity.iloc[:, 0].values

        peak = values[0]
        drawdowns = []
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak > 0 else 0
            drawdowns.append(-dd)

        x_vals = equity.index if "date" not in equity.columns else equity["date"]
        fig.add_trace(
            go.Scatter(
                x=x_vals,
                y=drawdowns,
                name="回撤",
                fill="tozeroy",
                line=dict(color="#F44336", width=1),
            ),
            row=2, col=1,
        )

        fig.update_layout(height=500, showlegend=True, margin=dict(l=20, r=20, t=20, b=20))
        fig.update_yaxes(title_text="资产", row=1, col=1)
        fig.update_yaxes(title_text="回撤", row=2, col=1, tickformat=".0%")

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("无净值数据")

    # === 交易明细 ===
    st.subheader("交易明细")
    if result.trades:
        trade_data = []
        for t in result.trades:
            trade_data.append({
                "时间": t.traded_at.strftime("%Y-%m-%d"),
                "标的": t.symbol,
                "方向": t.side.value,
                "价格": round(t.price, 2),
                "数量": t.amount,
                "手续费": round(t.commission, 2),
                "滑点": round(t.slippage, 2),
            })

        df_trades = pd.DataFrame(trade_data)
        st.dataframe(df_trades, use_container_width=True, hide_index=True)

        # 导出 CSV
        csv_buffer = io.StringIO()
        df_trades.to_csv(csv_buffer, index=False)
        st.download_button(
            label="导出 CSV",
            data=csv_buffer.getvalue(),
            file_name=f"backtest_trades_{symbol}_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )
    else:
        st.info("无交易记录")


render()
