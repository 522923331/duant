"""均线交叉策略示例"""

from duant.core.event import Bar
from duant.strategy.base import StrategyBase


class MACrossStrategy(StrategyBase):
    """均线金叉/死叉策略"""

    params = {
        "fast_period": 5,
        "slow_period": 20,
        "amount": 100,
    }

    def on_bar(self, bar: Bar) -> None:
        fast_period = self.get_param("fast_period")
        slow_period = self.get_param("slow_period")
        amount = self.get_param("amount")

        fast_ma = self.context.indicators.ma(fast_period, "close")
        slow_ma = self.context.indicators.ma(slow_period, "close")

        if self.cross_up(fast_ma, slow_ma):
            self.buy(bar.symbol, amount)
        elif self.cross_down(fast_ma, slow_ma):
            self.sell(bar.symbol, amount)
