"""风控配置"""

import streamlit as st
import yaml
from pathlib import Path

from duant.core.config import load_config
from duant.data.sqlite_store import SqliteStore


@st.cache_resource
def get_store() -> SqliteStore:
    config = load_config()
    return SqliteStore(config.data.db_path)


def render():
    st.title("风控配置")

    config = load_config()
    store = get_store()

    # === 风控规则开关 ===
    st.subheader("风控规则")
    risk_config = config.risk

    rule_defaults = {
        "max_position": {"enabled": True, "label": "单标的最大仓位", "param": "max_pct", "default": 0.3, "is_pct": True},
        "max_daily_trades": {"enabled": True, "label": "单日最大交易次数", "param": "max_count", "default": 20, "is_pct": False},
        "stop_loss": {"enabled": True, "label": "止损线", "param": "loss_pct", "default": 0.05, "is_pct": True},
        "take_profit": {"enabled": False, "label": "止盈线", "param": "profit_pct", "default": 0.15, "is_pct": True},
        "max_drawdown": {"enabled": True, "label": "最大回撤限制", "param": "max_dd", "default": 0.10, "is_pct": True},
        "max_daily_loss": {"enabled": True, "label": "每日最大亏损", "param": "max_loss", "default": 0.03, "is_pct": True},
        "max_holding": {"enabled": True, "label": "最大持仓数", "param": "max_count", "default": 10, "is_pct": False},
        "min_cash": {"enabled": True, "label": "最小现金保留", "param": "min_pct", "default": 0.10, "is_pct": True},
    }

    for rule_name, rule_def in rule_defaults.items():
        rule_cfg = risk_config.rules.get(rule_name)
        enabled = rule_cfg.enabled if rule_cfg else rule_def["enabled"]

        with st.container():
            col1, col2, col3 = st.columns([3, 2, 1])
            with col1:
                new_enabled = st.checkbox(rule_def["label"], value=enabled, key=f"risk_{rule_name}")
            with col2:
                default_val = getattr(rule_cfg, rule_def["param"], rule_def["default"]) if rule_cfg else rule_def["default"]
                if rule_def["is_pct"]:
                    pct_val = int(default_val * 100) if isinstance(default_val, float) and default_val <= 1 else int(default_val)
                    param_val = st.slider(
                        rule_def["param"] + "(%)",
                        min_value=0,
                        max_value=100,
                        value=pct_val,
                        step=1,
                        format="%d",
                        key=f"risk_param_{rule_name}",
                    )
                    param_val = param_val / 100.0
                else:
                    param_val = st.number_input(
                        rule_def["param"],
                        value=int(default_val),
                        key=f"risk_param_{rule_name}",
                    )
            with col3:
                st.write("")

    # === 风控触发历史 ===
    st.subheader("风控触发历史")
    from duant.core.event import RiskLevel
    events = store.get_risk_events()
    if events:
        event_data = []
        for e in events[:50]:
            event_data.append({
                "时间": e.created_at.strftime("%Y-%m-%d %H:%M"),
                "级别": e.level.value,
                "规则": e.rule_name,
                "动作": e.action.value,
                "标的": e.symbol or "-",
                "详情": e.detail,
            })
        st.dataframe(event_data, use_container_width=True, hide_index=True)
    else:
        st.info("暂无风控事件")


render()
