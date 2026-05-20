"""交易记录"""

import io
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd

from duant.core.config import load_config
from duant.data.sqlite_store import SqliteStore


@st.cache_resource
def get_store() -> SqliteStore:
    config = load_config()
    return SqliteStore(config.data.db_path)


def render():
    st.title("交易记录")

    store = get_store()

    # 筛选条件
    col1, col2, col3 = st.columns(3)
    with col1:
        default_start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        start_date = st.date_input("开始日期", value=datetime.strptime(default_start, "%Y-%m-%d"))
    with col2:
        end_date = st.date_input("结束日期", value=datetime.now())
    with col3:
        symbol_filter = st.text_input("标的代码", value="")

    trades = store.get_trades(
        symbol=symbol_filter if symbol_filter else None,
        start=datetime.combine(start_date, datetime.min.time()),
        end=datetime.combine(end_date, datetime.max.time()),
    )

    if not trades:
        st.info("暂无交易记录")
        return

    # 交易表格
    trade_data = []
    for t in trades:
        trade_data.append({
            "成交时间": t.traded_at.strftime("%Y-%m-%d %H:%M"),
            "标的": t.symbol,
            "市场": t.market.value,
            "方向": t.side.value,
            "价格": round(t.price, 2),
            "数量": t.amount,
            "成交额": round(t.price * t.amount, 2),
            "手续费": round(t.commission, 2),
            "滑点": round(t.slippage, 2),
        })

    df = pd.DataFrame(trade_data)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # 统计摘要
    st.subheader("统计摘要")
    total_count = len(trades)
    buy_count = sum(1 for t in trades if t.side.value == "buy")
    sell_count = total_count - buy_count
    total_commission = sum(t.commission for t in trades)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("总交易次数", total_count)
    with col2:
        st.metric("买入/卖出", f"{buy_count} / {sell_count}")
    with col3:
        st.metric("总手续费", f"¥{total_commission:,.2f}")

    # 导出 CSV
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    st.download_button(
        label="导出 CSV",
        data=csv_buffer.getvalue(),
        file_name=f"trades_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
    )


render()
