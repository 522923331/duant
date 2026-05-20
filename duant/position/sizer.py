"""仓位管理"""

from abc import ABC, abstractmethod

import numpy as np

from duant.core.event import Market


class PositionSizer(ABC):
    """仓位管理抽象基类"""

    @abstractmethod
    def calculate(self, symbol: str, price: float, portfolio, market: Market = Market.A_STOCK) -> float:
        """计算建议买入数量"""


class FixedAmountSizer(PositionSizer):
    """固定金额买入"""

    def __init__(self, amount: float = 10000):
        self.amount = amount

    def calculate(self, symbol: str, price: float, portfolio, market: Market = Market.A_STOCK) -> float:
        if price <= 0:
            return 0
        qty = self.amount / price
        if market == Market.A_STOCK:
            qty = int(qty // 100) * 100
        return max(qty, 0)


class FixedPercentSizer(PositionSizer):
    """固定比例买入（占总资产的比例）"""

    def __init__(self, pct: float = 0.1):
        self.pct = pct

    def calculate(self, symbol: str, price: float, portfolio, market: Market = Market.A_STOCK) -> float:
        if price <= 0:
            return 0
        total_value = portfolio.get_total_value()
        buy_amount = total_value * self.pct
        qty = buy_amount / price
        if market == Market.A_STOCK:
            qty = int(qty // 100) * 100
        return max(qty, 0)


class KellySizer(PositionSizer):
    """凯利公式（半注，降低波动）

    f = (p * b - (1-p)) / b * fraction
    其中 p=胜率, b=盈亏比, fraction=凯利半注系数
    """

    def __init__(self, win_rate: float = 0.5, profit_loss_ratio: float = 2.0, fraction: float = 0.5):
        self.win_rate = win_rate
        self.profit_loss_ratio = profit_loss_ratio
        self.fraction = fraction

    def calculate(self, symbol: str, price: float, portfolio, market: Market = Market.A_STOCK) -> float:
        if price <= 0:
            return 0

        b = self.profit_loss_ratio
        p = self.win_rate
        kelly = (p * b - (1 - p)) / b if b > 0 else 0
        kelly = max(kelly, 0) * self.fraction

        total_value = portfolio.get_total_value()
        buy_amount = total_value * kelly
        qty = buy_amount / price
        if market == Market.A_STOCK:
            qty = int(qty // 100) * 100
        return max(qty, 0)


class EqualRiskSizer(PositionSizer):
    """等风险仓位（按波动率分配，使每个标的风险贡献相等）

    仓位 = (target_risk * total_value) / (ATR * multiplier)
    """

    def __init__(self, target_risk: float = 0.01, lookback: int = 20):
        self.target_risk = target_risk
        self.lookback = lookback

    def calculate(self, symbol: str, price: float, portfolio, market: Market = Market.A_STOCK) -> float:
        if price <= 0:
            return 0

        # 从 DataBuffer 获取 ATR
        atr = self._calc_atr(symbol, portfolio)
        if atr <= 0:
            atr = price * 0.02  # 默认 2% 波动

        total_value = portfolio.get_total_value()
        risk_per_unit = atr * 2  # 用 2 倍 ATR 作为单标的风险
        if risk_per_unit <= 0:
            return 0

        target_risk_amount = total_value * self.target_risk
        qty = target_risk_amount / risk_per_unit
        if market == Market.A_STOCK:
            qty = int(qty // 100) * 100
        return max(qty, 0)

    def _calc_atr(self, symbol: str, portfolio) -> float:
        """计算 ATR（Average True Range）"""
        try:
            buffer = getattr(portfolio, "_buffer", None)
            if not buffer:
                return 0
            df = buffer.get_dataframe(symbol)
            if df.empty or len(df) < 2:
                return 0

            high = df["high"].values
            low = df["low"].values
            close_prev = np.roll(df["close"].values, 1)
            close_prev[0] = close_prev[1]

            tr = np.maximum(
                high - low,
                np.maximum(
                    np.abs(high - close_prev),
                    np.abs(low - close_prev),
                ),
            )

            lookback = min(self.lookback, len(tr))
            return float(np.mean(tr[-lookback:])) if lookback > 0 else 0
        except Exception:
            return 0


def create_sizer(config: dict) -> PositionSizer:
    """根据配置创建仓位管理器"""
    sizer_type = config.get("sizer", "fixed_percent")

    sizer_map = {
        "fixed_amount": lambda: FixedAmountSizer(**config.get("fixed_amount", {})),
        "fixed_percent": lambda: FixedPercentSizer(**config.get("fixed_percent", {})),
        "kelly": lambda: KellySizer(**config.get("kelly", {})),
        "equal_risk": lambda: EqualRiskSizer(**config.get("equal_risk", {})),
    }

    factory = sizer_map.get(sizer_type)
    if not factory:
        raise ValueError(f"未知仓位管理策略: {sizer_type}")
    return factory()
