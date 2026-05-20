"""风控规则实现"""

from abc import ABC, abstractmethod
from datetime import datetime

from duant.core.event import (
    Order,
    OrderSide,
    RiskAction,
    RiskEvent,
    RiskLevel,
)


class RiskRule(ABC):
    """风控规则抽象基类"""

    name: str = ""
    enabled: bool = True

    @abstractmethod
    def check_order(self, order: Order, portfolio) -> tuple[bool, str]:
        """检查订单，返回 (是否通过, 原因)"""

    def check_market(self, portfolio) -> RiskEvent | None:
        """市场级检查（可选），返回风控事件或 None"""
        return None


class MaxPositionRule(RiskRule):
    """单标的最大仓位"""

    name = "max_position"

    def __init__(self, max_pct: float = 0.3):
        self.max_pct = max_pct

    def check_order(self, order: Order, portfolio) -> tuple[bool, str]:
        if order.side != OrderSide.BUY:
            return True, ""

        total_value = portfolio.get_total_value()
        if total_value <= 0:
            return True, ""

        current_qty = portfolio.positions.get(order.symbol, {}).get("quantity", 0)
        current_mv = current_qty * order.price
        order_mv = order.price * order.amount
        new_pct = (current_mv + order_mv) / total_value

        if new_pct > self.max_pct:
            return False, f"单标的仓位 {new_pct:.1%} 超过限制 {self.max_pct:.1%}"
        return True, ""


class MaxDailyTradesRule(RiskRule):
    """单日最大交易次数"""

    name = "max_daily_trades"

    def __init__(self, max_count: int = 20):
        self.max_count = max_count

    def check_order(self, order: Order, portfolio) -> tuple[bool, str]:
        today = datetime.now().strftime("%Y-%m-%d")
        today_trades = sum(
            1 for t in portfolio.trades
            if t.traded_at.strftime("%Y-%m-%d") == today
        )
        if today_trades >= self.max_count:
            return False, f"今日交易次数 {today_trades} 已达上限 {self.max_count}"
        return True, ""


class StopLossRule(RiskRule):
    """止损线"""

    name = "stop_loss"

    def __init__(self, loss_pct: float = 0.05):
        self.loss_pct = loss_pct

    def check_order(self, order: Order, portfolio) -> tuple[bool, str]:
        if order.side != OrderSide.SELL:
            return True, ""

        pos = portfolio.positions.get(order.symbol)
        if not pos:
            return True, ""

        loss_pct = (pos["avg_price"] - order.price) / pos["avg_price"] if pos["avg_price"] > 0 else 0
        if loss_pct >= self.loss_pct:
            # 止损卖出应该放行，但记录事件
            return True, ""
        return True, ""

    def check_market(self, portfolio) -> RiskEvent | None:
        for sym, pos in portfolio.positions.items():
            if pos["avg_price"] <= 0:
                continue
            current_price = pos.get("current_price", pos["avg_price"])
            loss_pct = (pos["avg_price"] - current_price) / pos["avg_price"]
            if loss_pct >= self.loss_pct:
                return RiskEvent(
                    event_id=_gen_id(),
                    level=RiskLevel.STRATEGY,
                    rule_name=self.name,
                    action=RiskAction.CLOSE,
                    symbol=sym,
                    detail=f"{sym} 亏损 {loss_pct:.1%}，触发止损线 {self.loss_pct:.1%}",
                    created_at=datetime.now(),
                )
        return None


class TakeProfitRule(RiskRule):
    """止盈线"""

    name = "take_profit"

    def __init__(self, profit_pct: float = 0.15):
        self.profit_pct = profit_pct

    def check_order(self, order: Order, portfolio) -> tuple[bool, str]:
        return True, ""

    def check_market(self, portfolio) -> RiskEvent | None:
        for sym, pos in portfolio.positions.items():
            if pos["avg_price"] <= 0:
                continue
            current_price = pos.get("current_price", pos["avg_price"])
            profit_pct = (current_price - pos["avg_price"]) / pos["avg_price"]
            if profit_pct >= self.profit_pct:
                return RiskEvent(
                    event_id=_gen_id(),
                    level=RiskLevel.STRATEGY,
                    rule_name=self.name,
                    action=RiskAction.CLOSE,
                    symbol=sym,
                    detail=f"{sym} 盈利 {profit_pct:.1%}，触发止盈线 {self.profit_pct:.1%}",
                    created_at=datetime.now(),
                )
        return None


class MaxDrawdownRule(RiskRule):
    """最大回撤限制（账户级）"""

    name = "max_drawdown"

    def __init__(self, max_dd: float = 0.10):
        self.max_dd = max_dd

    def check_order(self, order: Order, portfolio) -> tuple[bool, str]:
        return True, ""

    def check_market(self, portfolio) -> RiskEvent | None:
        if portfolio.initial_cash <= 0:
            return None

        peak = getattr(portfolio, "_peak_value", portfolio.initial_cash)
        current = portfolio.get_total_value()
        dd = (peak - current) / peak if peak > 0 else 0

        if dd >= self.max_dd:
            return RiskEvent(
                event_id=_gen_id(),
                level=RiskLevel.ACCOUNT,
                rule_name=self.name,
                action=RiskAction.HALT,
                symbol=None,
                detail=f"账户回撤 {dd:.1%}，超过限制 {self.max_dd:.1%}，暂停所有策略",
                created_at=datetime.now(),
            )
        return None


class MaxDailyLossRule(RiskRule):
    """每日最大亏损（账户级）"""

    name = "max_daily_loss"

    def __init__(self, max_loss: float = 0.03):
        self.max_loss = max_loss

    def check_order(self, order: Order, portfolio) -> tuple[bool, str]:
        return True, ""

    def check_market(self, portfolio) -> RiskEvent | None:
        today = datetime.now().strftime("%Y-%m-%d")
        today_records = [
            r for r in portfolio.equity_records
            if r.get("date") == today
        ]
        if len(today_records) < 2:
            return None

        day_start = today_records[0]["total_value"]
        day_end = today_records[-1]["total_value"]
        if day_start <= 0:
            return None

        day_loss = (day_start - day_end) / day_start
        if day_loss >= self.max_loss:
            return RiskEvent(
                event_id=_gen_id(),
                level=RiskLevel.ACCOUNT,
                rule_name=self.name,
                action=RiskAction.HALT,
                symbol=None,
                detail=f"今日亏损 {day_loss:.1%}，超过限制 {self.max_loss:.1%}，暂停所有策略",
                created_at=datetime.now(),
            )
        return None


class MaxHoldingRule(RiskRule):
    """最大持仓数"""

    name = "max_holding"

    def __init__(self, max_count: int = 10):
        self.max_count = max_count

    def check_order(self, order: Order, portfolio) -> tuple[bool, str]:
        if order.side != OrderSide.BUY:
            return True, ""

        holding_count = len(portfolio.positions)
        new_symbol = order.symbol not in portfolio.positions
        if new_symbol and holding_count >= self.max_count:
            return False, f"持仓数 {holding_count} 已达上限 {self.max_count}"
        return True, ""


class MinCashRule(RiskRule):
    """最小现金保留"""

    name = "min_cash"

    def __init__(self, min_pct: float = 0.10):
        self.min_pct = min_pct

    def check_order(self, order: Order, portfolio) -> tuple[bool, str]:
        if order.side != OrderSide.BUY:
            return True, ""

        total_value = portfolio.get_total_value()
        if total_value <= 0:
            return True, ""

        order_cost = order.price * order.amount
        remaining_cash = portfolio.cash - order_cost
        remaining_pct = remaining_cash / total_value

        if remaining_pct < self.min_pct:
            return False, f"买入后现金占比 {remaining_pct:.1%} 低于保留 {self.min_pct:.1%}"
        return True, ""


def _gen_id() -> str:
    import uuid
    return uuid.uuid4().hex[:16]
