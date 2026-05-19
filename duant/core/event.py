"""核心数据模型定义"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Market(str, Enum):
    A_STOCK = "a_stock"
    CRYPTO = "crypto"


class TimeFrame(str, Enum):
    MIN_1 = "1m"
    MIN_5 = "5m"
    MIN_15 = "15m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAILY = "1d"


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class RiskLevel(str, Enum):
    STRATEGY = "strategy"
    ACCOUNT = "account"


class RiskAction(str, Enum):
    REJECT = "reject"
    CLOSE = "close"
    PAUSE = "pause"
    HALT = "halt"


@dataclass(frozen=True)
class Bar:
    symbol: str
    market: Market
    timeframe: TimeFrame
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    pre_close: float
    volume: float
    amount: float
    turnover: float = 0.0
    circ_market_cap: float = 0.0


@dataclass(frozen=True)
class Tick:
    symbol: str
    market: Market
    datetime: datetime
    price: float
    volume: float
    bid: float
    ask: float


@dataclass(frozen=True)
class Order:
    order_id: str
    symbol: str
    market: Market
    side: OrderSide
    order_type: OrderType
    price: float
    amount: float
    status: OrderStatus
    strategy_name: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class Trade:
    trade_id: str
    order_id: str
    symbol: str
    market: Market
    side: OrderSide
    price: float
    amount: float
    commission: float
    slippage: float
    traded_at: datetime


@dataclass(frozen=True)
class Position:
    symbol: str
    market: Market
    quantity: float
    avg_price: float
    current_price: float
    unrealized_pnl: float
    market_value: float
    updated_at: datetime


@dataclass(frozen=True)
class Account:
    cash: float
    positions: tuple[Position, ...]
    total_value: float
    realized_pnl: float
    updated_at: datetime


@dataclass(frozen=True)
class RiskEvent:
    event_id: str
    level: RiskLevel
    rule_name: str
    action: RiskAction
    symbol: str | None
    detail: str
    created_at: datetime


@dataclass(frozen=True)
class BacktestMetrics:
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    profit_loss_ratio: float
    trade_count: int


@dataclass(frozen=True)
class BacktestResult:
    metrics: BacktestMetrics
    trades: tuple[Trade, ...]
    equity_curve: "pd.DataFrame"
    positions: tuple[tuple[str, Position], ...]
