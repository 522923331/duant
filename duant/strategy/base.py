"""策略基类"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from duant.core.event import (
    Account,
    Bar,
    Market,
    Order,
    OrderSide,
    OrderType,
    Position,
    Tick,
)


class DataBuffer:
    """维护策略运行中的历史数据窗口"""

    def __init__(self, max_len: int = 500):
        self._data: dict[str, list[dict]] = {}
        self._max_len = max_len

    def append(self, bar: Bar) -> None:
        if bar.symbol not in self._data:
            self._data[bar.symbol] = []

        row = {
            "open": bar.open, "high": bar.high, "low": bar.low, "close": bar.close,
            "pre_close": bar.pre_close, "volume": bar.volume, "amount": bar.amount,
            "turnover": bar.turnover, "circ_market_cap": bar.circ_market_cap,
        }
        self._data[bar.symbol].append(row)
        if len(self._data[bar.symbol]) > self._max_len:
            self._data[bar.symbol] = self._data[bar.symbol][-self._max_len:]

    def get_series(self, symbol: str, field: str) -> pd.Series:
        if symbol not in self._data or not self._data[symbol]:
            return pd.Series(dtype=float)
        return pd.Series([r[field] for r in self._data[symbol]], dtype=float)

    def get_dataframe(self, symbol: str) -> pd.DataFrame:
        if symbol not in self._data or not self._data[symbol]:
            return pd.DataFrame()
        return pd.DataFrame(self._data[symbol])

    def get_latest(self, symbol: str, field: str, n: int = 1) -> pd.Series:
        if symbol not in self._data:
            return pd.Series(dtype=float)
        data = self._data[symbol][-n:]
        return pd.Series([r[field] for r in data], dtype=float)


class OrderHandler:
    """下单处理器接口（回测/模拟/实盘不同实现）"""

    def submit(self, order: Order) -> Order:
        return order


@dataclass
class Context:
    """策略运行时上下文"""
    account: Account
    indicators: "IndicatorCalculator"
    data_buffer: DataBuffer
    order_handler: OrderHandler
    current_bar: Bar | None = None


class StrategyBase(ABC):
    """所有策略的基类"""

    params: dict = {}

    def __init__(self):
        self._context: Context | None = None
        self._params: dict = dict(self.__class__.params)

    @property
    def context(self) -> Context:
        if self._context is None:
            raise RuntimeError("策略未初始化，请在引擎中使用")
        return self._context

    def set_context(self, ctx: Context) -> None:
        self._context = ctx

    def set_params(self, params: dict) -> None:
        self._params.update(params)

    def get_param(self, key: str, default=None):
        return self._params.get(key, default)

    # --- 生命周期 ---
    def on_start(self) -> None:
        pass

    @abstractmethod
    def on_bar(self, bar: Bar) -> None:
        pass

    def on_tick(self, tick: Tick) -> None:
        pass

    def on_order(self, order: Order) -> None:
        pass

    def on_stop(self) -> None:
        pass

    # --- 交易接口 ---
    def buy(self, symbol: str, amount: float, price: float = 0, order_type: OrderType = OrderType.MARKET) -> Order:
        order = Order(
            order_id=_gen_id(),
            symbol=symbol,
            market=self.context.current_bar.market if self.context.current_bar else Market.A_STOCK,
            side=OrderSide.BUY,
            order_type=order_type,
            price=price,
            amount=amount,
            status=OrderStatus.PENDING,
            strategy_name=self.__class__.__name__,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        return self.context.order_handler.submit(order)

    def sell(self, symbol: str, amount: float, price: float = 0, order_type: OrderType = OrderType.MARKET) -> Order:
        order = Order(
            order_id=_gen_id(),
            symbol=symbol,
            market=self.context.current_bar.market if self.context.current_bar else Market.A_STOCK,
            side=OrderSide.SELL,
            order_type=order_type,
            price=price,
            amount=amount,
            status=OrderStatus.PENDING,
            strategy_name=self.__class__.__name__,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        return self.context.order_handler.submit(order)

    # --- 查询接口 ---
    def get_position(self, symbol: str) -> Position | None:
        for p in self.context.account.positions:
            if p.symbol == symbol:
                return p
        return None

    def get_cash(self) -> float:
        return self.context.account.cash

    def get_account(self) -> Account:
        return self.context.account

    # --- 交叉判断 ---
    def cross_up(self, series_a: pd.Series, series_b: pd.Series) -> bool:
        if len(series_a) < 2 or len(series_b) < 2:
            return False
        return series_a.iloc[-2] <= series_b.iloc[-2] and series_a.iloc[-1] > series_b.iloc[-1]

    def cross_down(self, series_a: pd.Series, series_b: pd.Series) -> bool:
        if len(series_a) < 2 or len(series_b) < 2:
            return False
        return series_a.iloc[-2] >= series_b.iloc[-2] and series_a.iloc[-1] < series_b.iloc[-1]


def _gen_id() -> str:
    import uuid
    return uuid.uuid4().hex[:16]


# 延迟导入
from duant.core.event import OrderStatus  # noqa: E402
