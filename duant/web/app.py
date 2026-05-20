"""Streamlit 应用入口"""

import streamlit as st

st.set_page_config(
    page_title="duant - 量化交易系统",
    page_icon="📊",
    layout="wide",
)

pg = st.navigation([
    st.Page("pages/dashboard.py", title="仪表盘", icon="📊"),
    st.Page("pages/backtest.py", title="回测中心", icon="🔬"),
    st.Page("pages/strategy.py", title="策略管理", icon="🧠"),
    st.Page("pages/position.py", title="持仓监控", icon="💰"),
    st.Page("pages/trades.py", title="交易记录", icon="📋"),
    st.Page("pages/data.py", title="数据管理", icon="🗄️"),
    st.Page("pages/risk.py", title="风控配置", icon="🛡️"),
    st.Page("pages/settings.py", title="系统设置", icon="⚙️"),
])

pg.run()
