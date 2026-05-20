"""数据管理"""

from datetime import datetime

import streamlit as st

from duant.core.config import load_config
from duant.core.event import Market, TimeFrame
from duant.data.parquet_store import ParquetStore
from duant.data.sqlite_store import SqliteStore


@st.cache_resource
def get_stores():
    config = load_config()
    return ParquetStore(config.data.data_path), SqliteStore(config.data.db_path), config


def render():
    st.title("数据管理")

    parquet, sqlite, config = get_stores()

    # === 数据下载 ===
    st.subheader("数据下载")
    with st.form("download_form"):
        col1, col2 = st.columns(2)
        with col1:
            dl_symbol = st.text_input("标的代码", value="000001.SZ")
            dl_market = st.selectbox("市场", ["a_stock", "crypto"], index=0)
        with col2:
            dl_timeframe = st.selectbox("K线周期", ["1d", "1h", "15m", "5m", "1m"], index=0)
            dl_start = st.date_input("开始日期", value=datetime(2024, 1, 1))

        dl_end = st.date_input("结束日期", value=datetime.now(), key="dl_end")
        submitted = st.form_submit_button("下载")

        if submitted:
            try:
                from duant.data.fetcher import DataFetcher
                fetcher = DataFetcher(tushare_token=config.data.tushare_token)
                df = fetcher.fetch_bars(
                    dl_symbol, Market(dl_market), TimeFrame(dl_timeframe),
                    datetime.combine(dl_start, datetime.min.time()),
                    datetime.combine(dl_end, datetime.max.time()),
                )
                if not df.empty:
                    parquet.save(df, dl_symbol, Market(dl_market), TimeFrame(dl_timeframe))
                    st.success(f"下载完成: {len(df)} 条数据")
                else:
                    st.warning("无数据返回")
            except Exception as e:
                st.error(f"下载失败: {e}")

    # === 已有数据概览 ===
    st.subheader("已有数据")
    for market_name in ["a_stock", "crypto"]:
        market = Market(market_name)
        for tf_name in ["1d", "1h", "15m", "5m", "1m"]:
            try:
                symbols = parquet.list_symbols(market, TimeFrame(tf_name))
                if symbols:
                    for sym in symbols:
                        last_date = parquet.get_last_date(sym, market, TimeFrame(tf_name))
                        st.write(f"  {sym} | {market_name} | {tf_name} | 最新日期: {last_date.strftime('%Y-%m-%d') if last_date else '-'}")
            except Exception:
                pass

    # === 数据同步状态 ===
    st.subheader("数据同步状态")
    with sqlite._conn() as conn:
        rows = conn.execute("SELECT * FROM data_sync ORDER BY updated_at DESC").fetchall()
    if rows:
        sync_data = []
        for r in rows:
            sync_data.append({
                "标的": r["symbol"],
                "市场": r["market"],
                "周期": r["timeframe"],
                "最新日期": r["last_date"],
                "行数": r["row_count"],
                "更新时间": r["updated_at"],
            })
        st.dataframe(sync_data, use_container_width=True, hide_index=True)
    else:
        st.info("暂无同步记录")


render()
