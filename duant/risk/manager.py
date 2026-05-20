"""风控管理器"""

from datetime import datetime

from loguru import logger

from duant.core.config import RiskConfig, RiskRuleConfig
from duant.core.event import RiskEvent
from duant.data.sqlite_store import SqliteStore
from duant.risk.rules import (
    MaxDailyLossRule,
    MaxDailyTradesRule,
    MaxDrawdownRule,
    MaxHoldingRule,
    MaxPositionRule,
    MinCashRule,
    RiskRule,
    StopLossRule,
    TakeProfitRule,
)


class RiskManager:
    """风控管理器，所有订单必须经过风控检查"""

    def __init__(self, config: RiskConfig, sqlite: SqliteStore | None = None, notifier=None):
        self.rules: list[RiskRule] = []
        self.sqlite = sqlite
        self.notifier = notifier
        self._halted = False

        self._build_rules(config)

    def _build_rules(self, config: RiskConfig) -> None:
        """根据配置构建风控规则"""
        rule_map: dict[str, type[RiskRule]] = {
            "max_position": MaxPositionRule,
            "max_daily_trades": MaxDailyTradesRule,
            "stop_loss": StopLossRule,
            "take_profit": TakeProfitRule,
            "max_drawdown": MaxDrawdownRule,
            "max_daily_loss": MaxDailyLossRule,
            "max_holding": MaxHoldingRule,
            "min_cash": MinCashRule,
        }

        rule_param_map: dict[str, dict[str, str]] = {
            "max_position": {"max_pct": "max_pct"},
            "max_daily_trades": {"max_count": "max_count"},
            "stop_loss": {"loss_pct": "loss_pct"},
            "take_profit": {"profit_pct": "profit_pct"},
            "max_drawdown": {"max_dd": "max_dd"},
            "max_daily_loss": {"max_loss": "max_loss"},
            "max_holding": {"max_count": "max_count"},
            "min_cash": {"min_pct": "min_pct"},
        }

        for rule_name, rule_cfg in config.rules.items():
            if not rule_cfg.enabled:
                continue

            rule_cls = rule_map.get(rule_name)
            if not rule_cls:
                logger.warning(f"未知风控规则: {rule_name}")
                continue

            params = {}
            param_map = rule_param_map.get(rule_name, {})
            for cfg_key, param_key in param_map.items():
                val = getattr(rule_cfg, cfg_key, None)
                if val is not None:
                    params[param_key] = val

            rule = rule_cls(**params)
            self.rules.append(rule)
            logger.info(f"加载风控规则: {rule_name}")

        if not self.rules:
            logger.warning("未配置任何风控规则")

    def check(self, order, portfolio) -> tuple[bool, str]:
        """检查订单是否通过风控"""
        if self._halted:
            return False, "账户已暂停交易，需手动恢复"

        for rule in self.rules:
            if not rule.enabled:
                continue
            passed, reason = rule.check_order(order, portfolio)
            if not passed:
                event = RiskEvent(
                    event_id=_gen_id(),
                    level=rule.name and _get_level(rule),
                    rule_name=rule.name,
                    action=_get_action(rule),
                    symbol=order.symbol,
                    detail=reason,
                    created_at=datetime.now(),
                )
                self._record_event(event)
                logger.warning(f"风控拦截: {reason}")
                return False, reason

        return True, ""

    def check_market(self, portfolio) -> list[RiskEvent]:
        """市场级风控检查"""
        events = []
        for rule in self.rules:
            if not rule.enabled:
                continue
            event = rule.check_market(portfolio)
            if event:
                events.append(event)
                self._record_event(event)

                if event.action.value in ("halt", "pause"):
                    self._halted = True
                    logger.error(f"账户级风控触发: {event.detail}")

        return events

    def resume(self) -> None:
        """手动恢复账户交易"""
        self._halted = False
        logger.info("账户交易已恢复")

    @property
    def halted(self) -> bool:
        return self._halted

    def _record_event(self, event: RiskEvent) -> None:
        if self.sqlite:
            try:
                self.sqlite.save_risk_event(event)
            except Exception as e:
                logger.error(f"记录风控事件失败: {e}")

        if self.notifier:
            try:
                self.notifier.send_risk(event)
            except Exception as e:
                logger.error(f"发送风控通知失败: {e}")


def _gen_id() -> str:
    import uuid
    return uuid.uuid4().hex[:16]


def _get_level(rule: RiskRule):
    from duant.core.event import RiskLevel
    if rule.name in ("max_drawdown", "max_daily_loss"):
        return RiskLevel.ACCOUNT
    return RiskLevel.STRATEGY


def _get_action(rule: RiskRule):
    from duant.core.event import RiskAction
    if rule.name in ("max_drawdown", "max_daily_loss"):
        return RiskAction.HALT
    if rule.name in ("stop_loss", "take_profit"):
        return RiskAction.CLOSE
    return RiskAction.REJECT
