"""系统设置"""

import streamlit as st

from duant.core.config import load_config


def render():
    st.title("系统设置")

    config = load_config()

    # === 券商/交易所配置 ===
    st.subheader("交易网关")
    trade = config.trade

    gateway = st.selectbox(
        "网关模式",
        ["qmt", "simulate", "crypto"],
        index=["qmt", "simulate", "crypto"].index(trade.gateway),
    )

    if gateway == "qmt":
        with st.expander("QMT 配置"):
            st.text_input("QMT 路径", value=trade.qmt.path, key="qmt_path")
            st.text_input("资金账号", value=trade.qmt.account_id, key="qmt_account")
    elif gateway == "simulate":
        with st.expander("模拟登录配置"):
            st.selectbox("券商", ["ths", "yjb", "yh"], index=0, key="sim_broker")
            st.checkbox("下单前确认", value=trade.simulate.confirm, key="sim_confirm")
    elif gateway == "crypto":
        with st.expander("加密货币配置"):
            st.selectbox("交易所", ["binance", "okx", "bybit"], index=0, key="crypto_exchange")
            st.text_input("API Key", type="password", key="crypto_api_key")
            st.text_input("Secret", type="password", key="crypto_secret")

    # === 安全配置 ===
    st.subheader("安全配置")
    col1, col2 = st.columns(2)
    with col1:
        st.checkbox("实盘模式", value=trade.live_mode, key="live_mode")
    with col2:
        st.checkbox("大额订单确认", value=trade.confirm_large_order, key="confirm_large")

    st.number_input("大额订单比例(%)", value=trade.large_order_pct * 100, step=5.0, format="%.0f", key="large_order_pct") / 100

    # === 通知配置 ===
    st.subheader("通知配置")
    notify = config.notify
    if notify.webhooks:
        for i, wh in enumerate(notify.webhooks):
            st.write(f"Webhook {i + 1}: {wh.get('type', 'unknown')} - {wh.get('url', '')}")
    else:
        st.info("暂未配置 Webhook 通知")

    st.text_input("企业微信 Webhook URL", key="wecom_url")
    st.text_input("Telegram Bot URL", key="telegram_url")

    # === 日志配置 ===
    st.subheader("日志配置")
    log = config.log
    col1, col2 = st.columns(2)
    with col1:
        st.selectbox("日志级别", ["DEBUG", "INFO", "WARNING", "ERROR"], index=["DEBUG", "INFO", "WARNING", "ERROR"].index(log.level), key="log_level")
    with col2:
        st.text_input("日志路径", value=log.path, key="log_path")

    # === 保存按钮 ===
    st.divider()
    if st.button("保存配置", type="primary"):
        st.info("配置保存功能需要写入 config/default.yaml，请手动编辑配置文件")


render()
