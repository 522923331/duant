"""配置加载模块，支持 YAML + 环境变量替换"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml


_ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def _resolve_env_vars(value: str) -> str:
    """替换 ${VAR} 为环境变量值"""
    return _ENV_PATTERN.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _resolve_dict(d: dict) -> dict:
    """递归替换字典中的环境变量引用"""
    result = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = _resolve_env_vars(v)
        elif isinstance(v, dict):
            result[k] = _resolve_dict(v)
        elif isinstance(v, list):
            result[k] = [_resolve_env_vars(i) if isinstance(i, str) else i for i in v]
        else:
            result[k] = v
    return result


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个字典，override 覆盖 base"""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


@dataclass
class CommissionConfig:
    rate: float = 0.00025
    min: float = 5.0
    stamp_tax: float = 0.001
    transfer_fee: float = 0.000015


@dataclass
class CryptoCommissionConfig:
    rate: float = 0.001


@dataclass
class SlippageConfig:
    model: str = "fixed"
    value: float = 0.01


@dataclass
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    a_stock_commission: CommissionConfig = field(default_factory=CommissionConfig)
    crypto_commission: CryptoCommissionConfig = field(default_factory=CryptoCommissionConfig)
    slippage: SlippageConfig = field(default_factory=SlippageConfig)


@dataclass
class QmtConfig:
    path: str = ""
    account_id: str = ""


@dataclass
class SimulateConfig:
    broker: str = "ths"
    confirm: bool = True


@dataclass
class CryptoTradeConfig:
    exchange: str = "binance"
    api_key: str = ""
    secret: str = ""


@dataclass
class TradeConfig:
    gateway: str = "qmt"
    live_mode: bool = False
    confirm_large_order: bool = True
    large_order_pct: float = 0.2
    qmt: QmtConfig = field(default_factory=QmtConfig)
    simulate: SimulateConfig = field(default_factory=SimulateConfig)
    crypto: CryptoTradeConfig = field(default_factory=CryptoTradeConfig)


@dataclass
class RiskRuleConfig:
    enabled: bool = True
    max_pct: float = 0.3
    max_count: int = 20
    loss_pct: float = 0.05
    profit_pct: float = 0.15
    max_dd: float = 0.10
    max_loss: float = 0.03
    min_pct: float = 0.10


@dataclass
class RiskConfig:
    rules: dict[str, RiskRuleConfig] = field(default_factory=dict)


@dataclass
class PositionSizerConfig:
    sizer: str = "fixed_percent"  # fixed_amount / fixed_percent / kelly / equal_risk
    fixed_amount: dict = field(default_factory=lambda: {"amount": 10000})
    fixed_percent: dict = field(default_factory=lambda: {"pct": 0.1})
    kelly: dict = field(default_factory=lambda: {"win_rate": 0.5, "profit_loss_ratio": 2.0, "fraction": 0.5})
    equal_risk: dict = field(default_factory=lambda: {"target_risk": 0.01, "lookback": 20})


@dataclass
class NotifyConfig:
    webhooks: list[dict] = field(default_factory=list)


@dataclass
class DataConfig:
    data_path: str = "./data"
    db_path: str = "./data/duant.db"
    tushare_token: str = ""


@dataclass
class LogConfig:
    level: str = "INFO"
    path: str = "./logs"
    rotation: str = "1 day"
    retention: str = "30 days"


@dataclass
class AppConfig:
    data: DataConfig = field(default_factory=DataConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    trade: TradeConfig = field(default_factory=TradeConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    position: PositionSizerConfig = field(default_factory=PositionSizerConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    log: LogConfig = field(default_factory=LogConfig)


def load_config(config_path: Path | None = None) -> AppConfig:
    """
    加载配置，合并顺序：默认值 → default.yaml → 用户配置文件
    环境变量引用 ${VAR} 自动替换
    """
    cfg_dict: dict = {}

    # 加载默认配置
    default_path = Path(__file__).parent.parent.parent / "config" / "default.yaml"
    if default_path.exists():
        with open(default_path) as f:
            cfg_dict = _resolve_dict(yaml.safe_load(f) or {})

    # 加载用户配置，合并覆盖
    if config_path and config_path.exists():
        with open(config_path) as f:
            user_cfg = _resolve_dict(yaml.safe_load(f) or {})
            cfg_dict = _deep_merge(cfg_dict, user_cfg)

    return _dict_to_config(cfg_dict)


def _dict_to_config(d: dict) -> AppConfig:
    """将字典转换为 AppConfig dataclass"""
    data_cfg = d.get("data", {})
    bt_cfg = d.get("backtest", {})
    trade_cfg = d.get("trade", {})
    risk_cfg = d.get("risk", {})
    notify_cfg = d.get("notify", {})
    log_cfg = d.get("log", {})

    # 构建佣金配置
    commission = bt_cfg.get("commission", {})
    a_stock_comm = commission.get("a_stock", {})
    crypto_comm = commission.get("crypto", {})

    backtest = BacktestConfig(
        initial_cash=bt_cfg.get("initial_cash", 1_000_000),
        a_stock_commission=CommissionConfig(**a_stock_comm) if a_stock_comm else CommissionConfig(),
        crypto_commission=CryptoCommissionConfig(**crypto_comm) if crypto_comm else CryptoCommissionConfig(),
        slippage=SlippageConfig(**bt_cfg.get("slippage", {})),
    )

    trade = TradeConfig(
        gateway=trade_cfg.get("gateway", "qmt"),
        live_mode=trade_cfg.get("live_mode", False),
        confirm_large_order=trade_cfg.get("confirm_large_order", True),
        large_order_pct=trade_cfg.get("large_order_pct", 0.2),
        qmt=QmtConfig(**trade_cfg.get("qmt", {})),
        simulate=SimulateConfig(**trade_cfg.get("simulate", {})),
        crypto=CryptoTradeConfig(**trade_cfg.get("crypto", {})),
    )

    risk = RiskConfig()
    for rule_name, rule_val in risk_cfg.get("rules", {}).items():
        risk.rules[rule_name] = RiskRuleConfig(**rule_val)

    position_cfg = d.get("position", {})
    position = PositionSizerConfig(
        sizer=position_cfg.get("sizer", "fixed_percent"),
        fixed_amount=position_cfg.get("fixed_amount", {"amount": 10000}),
        fixed_percent=position_cfg.get("fixed_percent", {"pct": 0.1}),
        kelly=position_cfg.get("kelly", {"win_rate": 0.5, "profit_loss_ratio": 2.0, "fraction": 0.5}),
        equal_risk=position_cfg.get("equal_risk", {"target_risk": 0.01, "lookback": 20}),
    )

    return AppConfig(
        data=DataConfig(**data_cfg),
        backtest=backtest,
        trade=trade,
        risk=risk,
        position=position,
        notify=NotifyConfig(**notify_cfg),
        log=LogConfig(**log_cfg),
    )
