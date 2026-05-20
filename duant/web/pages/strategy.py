"""策略管理"""

import streamlit as st
from pathlib import Path

from duant.core.config import load_config
from duant.data.sqlite_store import SqliteStore
from duant.strategy.loader import StrategyLoader


@st.cache_resource
def get_store() -> SqliteStore:
    config = load_config()
    return SqliteStore(config.data.db_path)


@st.cache_data
def list_strategies() -> list[str]:
    config = load_config()
    project_root = Path.cwd()
    loader = StrategyLoader(
        yaml_dir=project_root / "config" / "strategies",
        python_dir=project_root / "strategies",
    )
    return list(loader.list_strategies().keys())


def render():
    st.title("策略管理")

    store = get_store()
    strategies = list_strategies()

    if not strategies:
        st.info("暂无策略，请在 config/strategies/ 或 strategies/ 目录下添加策略")
        return

    # 策略列表
    st.subheader("策略列表")
    for name in strategies:
        state = store.get_strategy_state(name)
        status = state.get("status", "stopped") if state else "stopped"
        mode = state.get("mode", "-") if state else "-"
        started_at = state.get("started_at", "-") if state else "-"
        error_count = state.get("error_count", 0) if state else 0

        status_icon = {"running": "🟢", "paused": "🟡", "stopped": "🔴"}.get(status, "⚪")

        with st.expander(f"{status_icon} {name} — {status}", expanded=False):
            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**状态**: {status}")
                st.write(f"**模式**: {mode}")
                st.write(f"**启动时间**: {started_at}")
                st.write(f"**错误次数**: {error_count}")

            with col2:
                if state and state.get("config"):
                    st.write("**运行配置**:")
                    for k, v in state["config"].items():
                        st.write(f"  - {k}: {v}")

            col_btn1, col_btn2, col_btn3 = st.columns(3)
            with col_btn1:
                if st.button("启动回测", key=f"bt_{name}"):
                    st.info(f"请前往「回测中心」页面选择策略 {name} 运行回测")
            with col_btn2:
                if st.button("启动模拟盘", key=f"paper_{name}"):
                    st.info(f"请使用命令行: `duant paper --strategy {name}`")
            with col_btn3:
                if status == "running" and st.button("停止", key=f"stop_{name}"):
                    st.info(f"请使用命令行: Ctrl+C 停止正在运行的策略")


render()
