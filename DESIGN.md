# duant - 开发设计文档

> 本文档基于 REQUIREMENTS.md，定义各模块的详细设计。所有实现以此为准。

---

## 1. 核心数据模型

所有核心数据使用 `dataclass` 定义，创建后不可变（`frozen=True`）。

### 1.1 行情数据

```python
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

@dataclass(frozen=True)
class Bar:
    symbol: str           # "000001.SZ" / "BTC/USDT"
    market: Market
    timeframe: TimeFrame
    datetime: datetime
    open: float
    high: float
    low: float
    close: float
    pre_close: float      # 昨收价，涨跌停判断必需，加密货币为 0
    volume: float
    amount: float          # 成交额（A股）/ quote_volume（加密）
    turnover: float = 0.0  # 换手率（%），加密货币为 0
    circ_market_cap: float = 0.0  # 流通市值（万元），加密货币为 0

@dataclass(frozen=True)
class Tick:
    symbol: str
    market: Market
    datetime: datetime
    price: float
    volume: float
    bid: float             # 买一价
    ask: float             # 卖一价
```

### 1.2 订单与成交

```python
class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(str, Enum):
    MARKET = "market"       # 市价单
    LIMIT = "limit"         # 限价单

class OrderStatus(str, Enum):
    PENDING = "pending"     # 待提交
    SUBMITTED = "submitted" # 已提交
    PARTIAL = "partial"     # 部分成交
    FILLED = "filled"       # 完全成交
    CANCELLED = "cancelled" # 已撤单
    REJECTED = "rejected"   # 已拒绝

@dataclass(frozen=True)
class Order:
    order_id: str           # UUID
    symbol: str
    market: Market
    side: OrderSide
    order_type: OrderType
    price: float            # 限价单价格，市价单为 0
    amount: float           # 委托数量
    status: OrderStatus
    strategy_name: str      # 来源策略
    created_at: datetime
    updated_at: datetime

@dataclass(frozen=True)
class Trade:
    trade_id: str           # UUID
    order_id: str           # 关联订单
    symbol: str
    market: Market
    side: OrderSide
    price: float            # 成交价格
    amount: float           # 成交数量
    commission: float       # 手续费
    slippage: float         # 滑点金额
    traded_at: datetime
```

### 1.3 持仓与账户

```python
@dataclass(frozen=True)
class Position:
    symbol: str
    market: Market
    quantity: float         # 持仓数量
    avg_price: float        # 持仓均价
    current_price: float    # 当前市价
    unrealized_pnl: float   # 未实现盈亏
    market_value: float     # 市值
    updated_at: datetime

@dataclass(frozen=True)
class Account:
    cash: float             # 可用现金
    positions: tuple[Position, ...]  # frozen=True 需要 tuple
    total_value: float      # 总资产 = cash + sum(market_value)
    realized_pnl: float     # 已实现盈亏
    updated_at: datetime
```

### 1.4 风控事件

```python
class RiskLevel(str, Enum):
    STRATEGY = "strategy"   # 策略级
    ACCOUNT = "account"     # 账户级

class RiskAction(str, Enum):
    REJECT = "reject"       # 拒绝订单
    CLOSE = "close"         # 强制平仓
    PAUSE = "pause"         # 暂停策略
    HALT = "halt"           # 暂停所有策略

@dataclass(frozen=True)
class RiskEvent:
    event_id: str           # UUID
    level: RiskLevel
    rule_name: str          # 触发的规则名
    action: RiskAction
    symbol: str | None      # 关联标的（账户级可为 None）
    detail: str             # 触发详情
    created_at: datetime
```

---

## 2. Parquet 文件 Schema

### 2.1 文件组织

```
data/
├── a_stock/
│   ├── daily/
│   │   └── {symbol}.parquet      # 如 000001.SZ.parquet
│   └── minute/
│       └── {symbol}.parquet
└── crypto/
    ├── 1d/
    │   └── {symbol}.parquet      # 如 BTC_USDT.parquet
    ├── 1h/
    │   └── {symbol}.parquet
    └── ...
```

### 2.2 列定义

**A股 Parquet 列定义（10 列）**：

| 列名 | 类型 | 说明 | 来源 |
|------|------|------|------|
| datetime | `datetime64[ns]` | 时间戳，作为索引 | trade_date |
| open | `float64` | 开盘价 | open |
| high | `float64` | 最高价 | high |
| low | `float64` | 最低价 | low |
| close | `float64` | 收盘价 | close |
| pre_close | `float64` | 昨收价 | pre_close，涨跌停判断必需 |
| volume | `float64` | 成交量（手） | vol |
| amount | `float64` | 成交额（千元） | amount |
| turnover | `float64` | 换手率（%） | turnover_rate，策略常用，不可从 OHLCV 推算 |
| circ_market_cap | `float64` | 流通市值（万元） | circ_market_cap，仓位管理/筛选常用，不可从 OHLCV 推算 |

**加密货币 Parquet 列定义（8 列）**：

| 列名 | 类型 | 说明 |
|------|------|------|
| datetime | `datetime64[ns]` | 时间戳，作为索引 |
| open | `float64` | 开盘价 |
| high | `float64` | 最高价 |
| low | `float64` | 最低价 |
| close | `float64` | 收盘价 |
| volume | `float64` | 成交量 |
| amount | `float64` | 成交额（quote_volume） |
| trades | `float64` | 成交笔数 |

**设计原则**：只存不可推算的字段。涨跌额、涨跌幅、连板数等派生数据不存储，由程序计算。

### 2.3 读写规范

```python
# 写入
df.to_parquet(path, engine="pyarrow", compression="snappy", index=True)

# 读取
df = pd.read_parquet(path, engine="pyarrow")

# 时间范围过滤（利用索引加速）
df = df.loc["2024-01-01":"2025-01-01"]
```

- 压缩：snappy（速度快，压缩率适中）
- 引擎：pyarrow
- 增量更新：读取已有文件 → 合并新数据 → 去重 → 覆盖写入

---

## 3. SQLite 表结构

数据库文件：`data/duant.db`

### 3.1 orders 表 — 订单记录

```sql
CREATE TABLE IF NOT EXISTS orders (
    order_id    TEXT PRIMARY KEY,
    symbol      TEXT NOT NULL,
    market      TEXT NOT NULL,            -- a_stock / crypto
    side        TEXT NOT NULL,            -- buy / sell
    order_type  TEXT NOT NULL,            -- market / limit
    price       REAL NOT NULL DEFAULT 0,
    amount      REAL NOT NULL,
    filled      REAL NOT NULL DEFAULT 0,  -- 已成交数量
    status      TEXT NOT NULL,            -- pending/submitted/partial/filled/cancelled/rejected
    strategy    TEXT NOT NULL,            -- 来源策略名
    reject_reason TEXT,                   -- 拒绝原因（风控拒绝时填写）
    created_at  TEXT NOT NULL,            -- ISO 8601
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_orders_strategy ON orders(strategy);
```

### 3.2 trades 表 — 成交记录

```sql
CREATE TABLE IF NOT EXISTS trades (
    trade_id    TEXT PRIMARY KEY,
    order_id    TEXT NOT NULL REFERENCES orders(order_id),
    symbol      TEXT NOT NULL,
    market      TEXT NOT NULL,
    side        TEXT NOT NULL,
    price       REAL NOT NULL,
    amount      REAL NOT NULL,
    commission  REAL NOT NULL DEFAULT 0,
    slippage    REAL NOT NULL DEFAULT 0,
    traded_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_trades_order ON trades(order_id);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_traded ON trades(traded_at);
```

### 3.3 positions 表 — 持仓快照

```sql
CREATE TABLE IF NOT EXISTS positions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT NOT NULL,
    market      TEXT NOT NULL,
    quantity    REAL NOT NULL,
    avg_price   REAL NOT NULL,
    snapshot_at TEXT NOT NULL,            -- 快照时间
    UNIQUE(symbol, market, snapshot_at)
);

CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
CREATE INDEX IF NOT EXISTS idx_positions_snapshot ON positions(snapshot_at);
```

### 3.4 risk_events 表 — 风控事件

```sql
CREATE TABLE IF NOT EXISTS risk_events (
    event_id    TEXT PRIMARY KEY,
    level       TEXT NOT NULL,            -- strategy / account
    rule_name   TEXT NOT NULL,
    action      TEXT NOT NULL,            -- reject/close/pause/halt
    symbol      TEXT,                     -- 可为空（账户级事件）
    detail      TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_risk_level ON risk_events(level);
CREATE INDEX IF NOT EXISTS idx_risk_rule ON risk_events(rule_name);
CREATE INDEX IF NOT EXISTS idx_risk_created ON risk_events(created_at);
```

### 3.5 strategy_state 表 — 策略运行状态

```sql
CREATE TABLE IF NOT EXISTS strategy_state (
    name        TEXT PRIMARY KEY,         -- 策略名
    status      TEXT NOT NULL,            -- running / paused / stopped
    mode        TEXT NOT NULL,            -- backtest / paper / live
    config      TEXT NOT NULL,            -- JSON，策略运行配置
    started_at  TEXT,                     -- 启动时间
    stopped_at  TEXT,                     -- 停止时间
    error_count INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL
);
```

### 3.6 daily_equity 表 — 每日净值

```sql
CREATE TABLE IF NOT EXISTS daily_equity (
    date        TEXT NOT NULL,
    mode        TEXT NOT NULL,            -- backtest / paper / live
    cash        REAL NOT NULL,
    market_value REAL NOT NULL,
    total_value REAL NOT NULL,
    realized_pnl REAL NOT NULL DEFAULT 0,
    PRIMARY KEY(date, mode)
);

CREATE INDEX IF NOT EXISTS idx_equity_date ON daily_equity(date);
```

### 3.7 data_sync 表 — 数据同步记录

```sql
CREATE TABLE IF NOT EXISTS data_sync (
    symbol      TEXT NOT NULL,
    market      TEXT NOT NULL,
    timeframe   TEXT NOT NULL,
    last_date   TEXT NOT NULL,            -- 最新已同步日期
    row_count   INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY(symbol, market, timeframe)
);
```

---

## 4. 模块类设计

### 4.1 数据模块（duant/data）

#### DataFetcher — 行情获取

```python
class DataFetcher:
    """统一行情获取入口，tushare 优先，akshare 降级"""

    def __init__(self, config: DataConfig):
        self.tushare = TushareFetcher(config.tushare_token)
        self.akshare = AkshareFetcher()
        self.ccxt = CryptoFetcher(config.exchange_configs)

    def fetch_bars(
        self,
        symbol: str,
        market: Market,
        timeframe: TimeFrame,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """获取K线数据，A股 tushare 优先，失败降级 akshare"""

    def fetch_tick(self, symbol: str, market: Market) -> Tick:
        """获取实时行情"""
```

#### ParquetStore — 行情存储

```python
class ParquetStore:
    """Parquet 文件读写，按市场/周期/标的组织"""

    def __init__(self, base_path: Path):
        self.base_path = base_path  # data/

    def save(self, df: pd.DataFrame, symbol: str, market: Market, timeframe: TimeFrame) -> None:
        """写入 Parquet，增量合并去重"""

    def load(self, symbol: str, market: Market, timeframe: TimeFrame,
             start: datetime | None = None, end: datetime | None = None) -> pd.DataFrame:
        """读取 Parquet，支持时间范围过滤"""

    def list_symbols(self, market: Market, timeframe: TimeFrame) -> list[str]:
        """列出已有数据的标的"""

    def get_last_date(self, symbol: str, market: Market, timeframe: TimeFrame) -> datetime | None:
        """获取最新数据日期，用于增量更新"""

    def _merge(self, existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        """合并新旧数据，去重（按 datetime），保留新数据"""
```

#### SqliteStore — 交易记录存储

```python
class SqliteStore:
    """SQLite 读写，存交易记录、持仓、风控事件等"""

    def __init__(self, db_path: Path):
        self.db_path = db_path  # data/duant.db

    # --- 订单 ---
    def save_order(self, order: Order) -> None: ...
    def update_order_status(self, order_id: str, status: OrderStatus, filled: float = 0, reject_reason: str = "") -> None: ...
    def get_orders(self, symbol: str | None = None, status: OrderStatus | None = None, start: datetime | None = None, end: datetime | None = None) -> list[Order]: ...

    # --- 成交 ---
    def save_trade(self, trade: Trade) -> None: ...
    def get_trades(self, symbol: str | None = None, start: datetime | None = None, end: datetime | None = None) -> list[Trade]: ...

    # --- 持仓快照 ---
    def save_position_snapshot(self, positions: list[Position], snapshot_at: datetime) -> None: ...
    def get_latest_positions(self) -> list[Position]: ...

    # --- 风控事件 ---
    def save_risk_event(self, event: RiskEvent) -> None: ...
    def get_risk_events(self, level: RiskLevel | None = None, start: datetime | None = None) -> list[RiskEvent]: ...

    # --- 策略状态 ---
    def save_strategy_state(self, name: str, status: str, mode: str, config: dict) -> None: ...
    def get_strategy_state(self, name: str) -> dict | None: ...

    # --- 每日净值 ---
    def save_daily_equity(self, date: str, mode: str, cash: float, market_value: float, total_value: float, realized_pnl: float) -> None: ...
    def get_equity_curve(self, mode: str, start: str | None = None) -> pd.DataFrame: ...

    # --- 数据同步 ---
    def get_sync_record(self, symbol: str, market: str, timeframe: str) -> dict | None: ...
    def update_sync_record(self, symbol: str, market: str, timeframe: str, last_date: str, row_count: int) -> None: ...
```

### 4.2 策略模块（duant/strategy）

#### StrategyBase — 策略基类

```python
class StrategyBase(ABC):
    """所有策略的基类，编程式策略继承此类"""

    params: dict = {}                     # 策略默认参数

    def __init__(self):
        self._context: Context | None = None  # 运行时注入

    @property
    def context(self) -> Context:
        """策略运行上下文，由引擎注入"""
        return self._context

    # --- 生命周期 ---
    def on_start(self) -> None:
        """策略启动时调用（可选覆写）"""

    @abstractmethod
    def on_bar(self, bar: Bar) -> None:
        """每根K线回调（必须实现）"""

    def on_tick(self, tick: Tick) -> None:
        """实时行情回调（可选覆写）"""

    def on_order(self, order: Order) -> None:
        """订单状态变化回调（可选覆写）"""

    def on_stop(self) -> None:
        """策略停止时调用（可选覆写）"""

    # --- 交易接口（委托给 Context） ---
    def buy(self, symbol: str, amount: float, price: float = 0, order_type: OrderType = OrderType.MARKET) -> Order: ...
    def sell(self, symbol: str, amount: float, price: float = 0, order_type: OrderType = OrderType.MARKET) -> Order: ...
    def cancel(self, order_id: str) -> bool: ...

    # --- 查询接口 ---
    def get_position(self, symbol: str) -> Position | None: ...
    def get_cash(self) -> float: ...
    def get_account(self) -> Account: ...

    # --- 技术指标（委托给 Context.indicators） ---
    @property
    def indicators(self) -> IndicatorCalculator: ...

    # --- 交叉判断 ---
    def cross_up(self, series_a: pd.Series, series_b: pd.Series) -> bool:
        """series_a 从下方穿过 series_b"""
    def cross_down(self, series_a: pd.Series, series_b: pd.Series) -> bool:
        """series_a 从上方穿过 series_b"""
```

#### Context — 策略运行上下文

```python
@dataclass
class Context:
    """策略运行时上下文，引擎创建并注入策略"""

    account: Account
    indicators: IndicatorCalculator
    data_buffer: DataBuffer       # 历史数据缓存
    order_handler: OrderHandler   # 下单处理器（回测/模拟/实盘不同实现）
```

#### IndicatorCalculator — 技术指标计算器

```python
class IndicatorCalculator:
    """技术指标计算，基于 pandas/numpy，输入为 DataBuffer 中的历史数据"""

    def __init__(self, data_buffer: DataBuffer):
        self._buffer = data_buffer

    # 趋势指标
    def ma(self, period: int, field: str = "close") -> pd.Series: ...
    def ema(self, period: int, field: str = "close") -> pd.Series: ...
    def macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]: ...
    def bollinger(self, period: int = 20, std_dev: float = 2.0) -> tuple[pd.Series, pd.Series, pd.Series]: ...

    # 动量指标
    def rsi(self, period: int = 14) -> pd.Series: ...
    def kdj(self, n: int = 9, m1: int = 3, m2: int = 3) -> tuple[pd.Series, pd.Series, pd.Series]: ...
    def cci(self, period: int = 14) -> pd.Series: ...

    # 成交量指标
    def obv(self) -> pd.Series: ...
    def volume_ratio(self, period: int = 5) -> pd.Series: ...
```

#### DataBuffer — 数据缓存

```python
class DataBuffer:
    """维护策略运行中的历史数据窗口，供指标计算使用"""

    def __init__(self, max_len: int = 500):
        self._data: dict[str, pd.DataFrame] = {}  # symbol -> DataFrame
        self._max_len = max_len

    def append(self, bar: Bar) -> None:
        """追加一根 bar，超出 max_len 截断"""

    def get_series(self, symbol: str, field: str) -> pd.Series:
        """获取某个标的的某个字段序列，如 close"""

    def get_dataframe(self, symbol: str) -> pd.DataFrame:
        """获取某个标的的完整 DataFrame"""
```

#### YamlStrategyLoader — 声明式策略加载

```python
class YamlStrategyLoader:
    """解析 YAML 声明式策略，动态生成 StrategyBase 子类实例"""

    def load(self, yaml_path: Path) -> StrategyBase:
        """加载 YAML 文件，解析条件表达式，生成策略实例"""

    def _parse_condition(self, expr: str) -> Callable[[Context], bool]:
        """将条件表达式字符串解析为可执行函数

        示例: "cross_up(ma(close, 5), ma(close, 20))"
        解析为: lambda ctx: ctx.indicators.cross_up(
                    ctx.indicators.ma(5, "close"),
                    ctx.indicators.ma(20, "close"))
        """
```

条件表达式解析规则：

| 表达式 | 解析为 |
|--------|--------|
| `close` | `buffer.get_series(symbol, "close")` |
| `ma(close, 5)` | `indicators.ma(5, "close")` |
| `cross_up(a, b)` | `cross_up(a, b)` |
| `above(a, b)` | `a.iloc[-1] > b.iloc[-1]` |
| `below(a, b)` | `a.iloc[-1] < b.iloc[-1]` |
| `and(a, b)` | `a and b` |
| `or(a, b)` | `a or b` |

### 4.3 回测引擎（duant/backtest）

#### BacktestEngine

```python
class BacktestEngine:
    """回测引擎主类"""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.store = ParquetStore(config.data_path)
        self.matcher = OrderMatcher(config.commission_model, config.slippage_model)
        self.portfolio = Portfolio(config.initial_cash)
        self.indicators = IndicatorCalculator(...)

    def run(self, strategy: StrategyBase, symbols: list[str], start: datetime, end: datetime) -> BacktestResult:
        """
        回测主循环:
        1. 加载所有标的的行情数据
        2. 按时间合并排序，逐 bar 推送
        3. 策略计算信号 → 生成订单 → 撮合 → 更新持仓
        4. 记录每日净值
        5. 运算性能指标
        """

    def _feed_bars(self, strategy: StrategyBase, symbols: list[str], start: datetime, end: datetime) -> None:
        """按时间合并多标的行情，逐 bar 推送给策略"""

    def _calculate_metrics(self) -> BacktestMetrics:
        """计算回测指标"""
```

#### BacktestConfig

```python
@dataclass
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    data_path: Path = Path("data/")
    commission_model: str = "a_stock"     # a_stock / crypto
    slippage_model: str = "fixed"         # fixed / percent
    slippage_value: float = 0.01          # 固定滑点金额 或 百分比
```

#### OrderMatcher — 订单撮合器

```python
class OrderMatcher:
    """回测中的订单撮合，模拟真实成交"""

    def __init__(self, commission_model: str, slippage_model: str, slippage_value: float):
        ...

    def match(self, order: Order, bar: Bar) -> Trade | None:
        """
        撮合逻辑:
        1. 市价单：按 bar 的 open + 滑点成交
        2. 限价单：检查价格是否触及
        3. A股特殊：涨跌停检查、整手检查
        4. 计算手续费
        """

    def _calc_commission(self, trade_price: float, trade_amount: float, side: OrderSide, market: Market) -> float:
        """
        A股：佣金万2.5（最低5元）+ 印花税千1（卖出）+ 过户费十万分之1.5
        加密：0.1%（买卖都收）
        """
```

#### Portfolio — 回测投资组合

```python
class Portfolio:
    """回测中的虚拟账户，管理现金和持仓"""

    def __init__(self, initial_cash: float):
        self.cash: float = initial_cash
        self.positions: dict[str, Position] = {}
        self.trades: list[Trade] = []
        self.equity_curve: list[dict] = []   # 每日净值

    def apply_trade(self, trade: Trade) -> None:
        """应用成交，更新现金和持仓"""

    def update_price(self, symbol: str, price: float) -> None:
        """更新持仓市价"""

    def get_total_value(self) -> float:
        """总资产 = cash + sum(持仓市值)"""

    def snapshot_equity(self, date: str) -> None:
        """记录每日净值快照"""
```

#### BacktestResult — 回测结果

```python
@dataclass(frozen=True)
class BacktestResult:
    metrics: BacktestMetrics
    trades: tuple[Trade, ...]
    equity_curve: pd.DataFrame     # date, cash, market_value, total_value
    positions: tuple[tuple[str, Position], ...]  # 最终持仓，frozen 需要 tuple

@dataclass(frozen=True)
class BacktestMetrics:
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    profit_loss_ratio: float
    trade_count: int
```

### 4.4 模拟盘引擎（duant/paper）

#### PaperEngine

```python
class PaperEngine:
    """模拟盘引擎，实时行情驱动，虚拟成交"""

    def __init__(self, config: PaperConfig):
        self.config = config
        self.fetcher = DataFetcher(config.data_config)
        self.portfolio = Portfolio(config.initial_cash)
        self.sqlite = SqliteStore(config.db_path)
        self._running: bool = False

    def start(self, strategy: StrategyBase) -> None:
        """
        启动模拟盘:
        1. 从 SQLite 恢复上次状态
        2. 启动行情轮询（A股 akshare / 加密 ccxt ws）
        3. 逐 bar/tick 推给策略
        4. 虚拟成交，记录到 SQLite
        """

    def stop(self) -> None:
        """停止模拟盘，持久化状态到 SQLite"""

    def _poll_market(self, strategy: StrategyBase) -> None:
        """轮询行情（A股：每 3-5 秒拉一次；加密：websocket 推送）"""

    def _restore_state(self) -> None:
        """从 SQLite 恢复持仓和账户状态"""
```

### 4.5 交易网关（duant/trade）

#### TradeGateway — 抽象层

```python
class TradeGateway(ABC):
    """交易网关抽象层，所有网关实现此接口"""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def buy(self, symbol: str, price: float, amount: float) -> Order: ...

    @abstractmethod
    def sell(self, symbol: str, price: float, amount: float) -> Order: ...

    @abstractmethod
    def cancel(self, order_id: str) -> bool: ...

    @abstractmethod
    def get_position(self, symbol: str) -> Position | None: ...

    @abstractmethod
    def get_positions(self) -> list[Position]: ...

    @abstractmethod
    def get_balance(self) -> float: ...

    @abstractmethod
    def get_orders(self) -> list[Order]: ...

    @abstractmethod
    def is_connected(self) -> bool: ...
```

#### QmtGateway — miniQMT 网关

```python
class QmtGateway(TradeGateway):
    """通过 xtquant 连接 miniQMT，程序化交易"""

    def __init__(self, config: QmtConfig):
        self.xt = None  # xtquant.XtQuantTrader
        self.config = config

    def connect(self) -> None:
        """连接 QMT 交易客户端"""

    def buy(self, symbol: str, price: float, amount: float) -> Order:
        """通过 xtquant 下买入单"""

    def sell(self, symbol: str, price: float, amount: float) -> Order:
        """通过 xtquant 下卖出单"""

    def cancel(self, order_id: str) -> bool:
        """通过 xtquant 撤单"""
```

#### SimulateGateway — 模拟登录网关

```python
class SimulateGateway(TradeGateway):
    """通过 easytrader 控制券商客户端，UI 自动化下单"""

    def __init__(self, config: SimulateConfig):
        self.trader = None  # easytrader 实例
        self.config = config
        self.confirm_before_trade: bool = True  # 下单前弹窗确认

    def connect(self) -> None:
        """连接券商客户端（easytrader.use("ths")）"""

    def buy(self, symbol: str, price: float, amount: float) -> Order:
        """通过 UI 自动化买入，confirm_before_trade=True 时弹窗确认"""

    def sell(self, symbol: str, price: float, amount: float) -> Order:
        """通过 UI 自动化卖出"""

    def _confirm(self, action: str, symbol: str, price: float, amount: float) -> bool:
        """弹窗确认（Tkinter 或终端输入），返回是否确认"""
```

#### CryptoGateway — 加密货币网关

```python
class CryptoGateway(TradeGateway):
    """通过 ccxt 连接加密货币交易所"""

    def __init__(self, config: CryptoConfig):
        self.exchange = None  # ccxt.binance / ccxt.okx
        self.config = config

    def connect(self) -> None:
        """初始化交易所连接，加载市场信息"""

    def buy(self, symbol: str, price: float, amount: float) -> Order: ...
    def sell(self, symbol: str, price: float, amount: float) -> Order: ...
    def cancel(self, order_id: str) -> bool: ...
```

#### GatewayFactory — 网关工厂

```python
class GatewayFactory:
    """根据配置创建对应的交易网关"""

    @staticmethod
    def create(config: TradeConfig) -> TradeGateway:
        match config.gateway:
            case "qmt":
                return QmtGateway(config.qmt)
            case "simulate":
                return SimulateGateway(config.simulate)
            case "crypto":
                return CryptoGateway(config.crypto)
            case _:
                raise ValueError(f"Unknown gateway: {config.gateway}")
```

### 4.6 风控模块（duant/risk）

#### RiskManager

```python
class RiskManager:
    """风控管理器，所有订单必须经过风控检查"""

    def __init__(self, rules: list[RiskRule], sqlite: SqliteStore, notifier: Notifier):
        self.rules = rules
        self.sqlite = sqlite
        self.notifier = notifier
        self._halted: bool = False  # 账户级暂停标志

    def check(self, order: Order, portfolio: Portfolio) -> tuple[bool, str]:
        """
        检查订单是否通过风控:
        1. 如果账户已暂停，直接拒绝
        2. 逐条规则检查，任一不通过即拒绝
        3. 返回 (是否通过, 原因)
        """

    def check_market(self, portfolio: Portfolio) -> list[RiskEvent]:
        """
        市场级风控检查（非订单触发）:
        - 最大回撤
        - 每日最大亏损
        返回触发的风控事件列表
        """

    def resume(self) -> None:
        """手动恢复账户交易"""
```

#### RiskRule — 风控规则基类

```python
class RiskRule(ABC):
    """风控规则抽象基类"""

    name: str
    enabled: bool = True

    @abstractmethod
    def check_order(self, order: Order, portfolio: Portfolio) -> tuple[bool, str]:
        """检查订单，返回 (是否通过, 原因)"""

    def check_market(self, portfolio: Portfolio) -> RiskEvent | None:
        """市场级检查（可选），返回风控事件或 None"""
        return None
```

#### 具体风控规则

```python
class MaxPositionRule(RiskRule):
    """单标的最大仓位"""
    name = "max_position"
    def __init__(self, max_pct: float = 0.3): ...

class MaxDailyTradesRule(RiskRule):
    """单日最大交易次数"""
    name = "max_daily_trades"
    def __init__(self, max_count: int = 20): ...

class StopLossRule(RiskRule):
    """止损线"""
    name = "stop_loss"
    def __init__(self, loss_pct: float = 0.05): ...

class TakeProfitRule(RiskRule):
    """止盈线"""
    name = "take_profit"
    def __init__(self, profit_pct: float = 0.15): ...

class MaxDrawdownRule(RiskRule):
    """最大回撤限制"""
    name = "max_drawdown"
    def __init__(self, max_dd: float = 0.10): ...

class MaxDailyLossRule(RiskRule):
    """每日最大亏损"""
    name = "max_daily_loss"
    def __init__(self, max_loss: float = 0.03): ...

class MaxHoldingRule(RiskRule):
    """最大持仓数"""
    name = "max_holding"
    def __init__(self, max_count: int = 10): ...

class MinCashRule(RiskRule):
    """最小现金保留"""
    name = "min_cash"
    def __init__(self, min_pct: float = 0.10): ...
```

### 4.7 仓位管理（duant/position）

```python
class PositionSizer(ABC):
    """仓位管理抽象基类"""

    @abstractmethod
    def calculate(self, symbol: str, price: float, portfolio: Portfolio) -> float:
        """计算建议买入数量"""

class FixedAmountSizer(PositionSizer):
    """固定金额买入"""
    def __init__(self, amount: float = 10000): ...

class FixedPercentSizer(PositionSizer):
    """固定比例买入（占总资产的比例）"""
    def __init__(self, pct: float = 0.1): ...

class KellySizer(PositionSizer):
    """凯利公式"""
    def __init__(self, win_rate: float, profit_loss_ratio: float, fraction: float = 0.5): ...
    # fraction 为凯利半注，降低波动

class EqualRiskSizer(PositionSizer):
    """等风险仓位"""
    def __init__(self, target_risk: float = 0.01, lookback: int = 20): ...
    # 按波动率分配，使每个标的风险贡献相等
```

### 4.8 通知模块（duant/notify）

```python
class Notifier:
    """Webhook 通知，支持企业微信和 Telegram"""

    def __init__(self, config: NotifyConfig):
        self.webhooks: list[WebhookConfig] = config.webhooks

    def send(self, title: str, content: str, level: str = "info") -> None:
        """发送通知到所有配置的 webhook"""

    def send_trade(self, trade: Trade) -> None: ...
    def send_risk(self, event: RiskEvent) -> None: ...
    def send_daily_report(self, account: Account) -> None: ...

@dataclass
class WebhookConfig:
    type: str          # wecom / telegram
    url: str           # webhook URL
    secret: str = ""   # 企业微信签名密钥（可选）
```

### 4.9 主引擎（duant/core）

#### Engine

```python
class Engine:
    """系统主引擎，协调所有模块"""

    def __init__(self, config: AppConfig):
        self.config = config
        self.fetcher = DataFetcher(config.data)
        self.parquet = ParquetStore(config.data.data_path)
        self.sqlite = SqliteStore(config.data.db_path)
        self.notifier = Notifier(config.notify)
        self.risk_manager: RiskManager | None = None
        self.gateway: TradeGateway | None = None

    # --- 回测 ---
    def backtest(self, strategy: StrategyBase, symbols: list[str],
                 start: datetime, end: datetime, config: BacktestConfig | None = None) -> BacktestResult:
        """运行回测"""

    # --- 模拟盘 ---
    def start_paper(self, strategy: StrategyBase) -> None:
        """启动模拟盘"""

    def stop_paper(self) -> None:
        """停止模拟盘"""

    # --- 实盘 ---
    def start_live(self, strategy: StrategyBase) -> None:
        """启动实盘交易"""

    def stop_live(self) -> None:
        """停止实盘"""

    # --- 数据管理 ---
    def update_data(self, symbols: list[str], market: Market, timeframe: TimeFrame) -> None:
        """增量更新行情数据"""

    def download_data(self, symbols: list[str], market: Market, timeframe: TimeFrame,
                      start: datetime, end: datetime) -> None:
        """下载指定范围的行情数据"""
```

### 4.10 交易流程编排（OrderHandler）

```python
class OrderHandler:
    """下单处理器，编排策略→风控→网关的完整流程"""

    def __init__(self, risk_manager: RiskManager, gateway: TradeGateway,
                 portfolio: Portfolio, sqlite: SqliteStore, notifier: Notifier):
        ...

    def submit(self, order: Order) -> Order:
        """
        提交订单的完整流程:
        1. 风控检查 → 不通过则记录并拒绝
        2. 仓位调整（可选，由 PositionSizer 计算实际数量）
        3. 提交到网关 → 获取成交回报
        4. 更新持仓
        5. 记录到 SQLite
        6. 发送通知
        """
```

---

## 5. 模块交互流程

### 5.1 回测流程

```
┌─────────────────────────────────────────────────────────┐
│                    BacktestEngine.run()                  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  1. ParquetStore.load() → 加载行情到内存                 │
│                    ↓                                    │
│  2. 合并多标的行情，按时间排序                             │
│                    ↓                                    │
│  3. ┌── 循环每一根 bar ──────────────────────────┐      │
│    │  strategy.on_bar(bar)                        │      │
│    │       ↓                                      │      │
│    │  策略调用 buy/sell → 生成 Order               │      │
│    │       ↓                                      │      │
│    │  OrderMatcher.match(order, bar)              │      │
│    │       ↓                                      │      │
│    │  生成 Trade → Portfolio.apply_trade()        │      │
│    │       ↓                                      │      │
│    │  Portfolio.update_price() → 更新持仓市值      │      │
│    │       ↓                                      │      │
│    │  Portfolio.snapshot_equity() → 记录净值       │      │
│    └──────────────────────────────────────────────┘      │
│                    ↓                                    │
│  4. BacktestMetrics 计算 → 返回 BacktestResult          │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

### 5.2 实盘交易流程

```
┌──────────────────────────────────────────────────────┐
│                  实盘交易流程                          │
├──────────────────────────────────────────────────────┤
│                                                      │
│  行情推送 (tick/bar)                                  │
│       ↓                                              │
│  strategy.on_bar/on_tick()                           │
│       ↓                                              │
│  策略调用 buy/sell                                    │
│       ↓                                              │
│  OrderHandler.submit(order)                          │
│       │                                              │
│       ├── RiskManager.check() ── 不通过 ──→ 拒绝订单  │
│       │         ↓ 通过                                │
│       ├── SimulateGateway: confirm() (可选)           │
│       │         ↓ 确认                                │
│       ├── TradeGateway.buy/sell() ──→ 提交到券商/交易所│
│       │         ↓                                     │
│       ├── 成交回报 → 生成 Trade                       │
│       │         ↓                                     │
│       ├── Portfolio.apply_trade() → 更新持仓          │
│       │         ↓                                     │
│       ├── SqliteStore.save_order() + save_trade()     │
│       │         ↓                                     │
│       └── Notifier.send_trade() → 发送通知            │
│                                                      │
└──────────────────────────────────────────────────────┘
```

### 5.3 风控拦截流程

```
┌──────────────────────────────────────────────────────┐
│                 风控检查流程                           │
├──────────────────────────────────────────────────────┤
│                                                      │
│  订单触发:                                            │
│    OrderHandler.submit(order)                        │
│       ↓                                              │
│    RiskManager.check(order, portfolio)               │
│       │                                              │
│       ├── MaxPositionRule    → 单标的仓位超限?        │
│       ├── MaxDailyTradesRule → 今日交易次数超限?      │
│       ├── StopLossRule       → 需要止损?             │
│       ├── TakeProfitRule     → 需要止盈?             │
│       ├── MaxHoldingRule     → 持仓数超限?           │
│       ├── MinCashRule        → 现金不足?             │
│       │                                              │
│       ├── 任一不通过 → 拒绝订单，记录 RiskEvent        │
│       └── 全部通过   → 继续下单                       │
│                                                      │
│  市场触发（每 bar 检查）:                              │
│    RiskManager.check_market(portfolio)               │
│       │                                              │
│       ├── MaxDrawdownRule  → 账户回撤超限 → halt      │
│       ├── MaxDailyLossRule → 当日亏损超限 → halt      │
│       │                                              │
│       └── 触发 → 暂停所有策略，记录 RiskEvent，发通知  │
│                                                      │
└──────────────────────────────────────────────────────┘
```

---

## 6. YAML 配置 Schema

### 6.1 default.yaml — 系统默认配置

```yaml
# ===== 数据配置 =====
data:
  data_path: "./data"
  db_path: "./data/duant.db"
  tushare_token: "${TUSHARE_TOKEN}"    # 环境变量引用
  sources:
    a_stock: tushare                    # 主数据源
    a_stock_fallback: akshare           # 降级数据源
    crypto: ccxt

# ===== 回测默认参数 =====
backtest:
  initial_cash: 1000000
  commission:
    a_stock:
      rate: 0.00025                    # 佣金万2.5
      min: 5                           # 最低佣金5元
      stamp_tax: 0.001                 # 印花税千1（卖出）
      transfer_fee: 0.000015           # 过户费
    crypto:
      rate: 0.001                      # 0.1%
  slippage:
    model: fixed                       # fixed / percent
    value: 0.01                        # 固定金额 或 百分比

# ===== 交易配置 =====
trade:
  gateway: qmt                         # qmt / simulate / crypto
  live_mode: false                     # 必须显式开启实盘
  confirm_large_order: true            # 大额订单确认
  large_order_pct: 0.2                 # 超过总资产20%视为大额
  qmt:
    path: ""                           # QMT 安装路径
    account_id: ""                     # 资金账号
  simulate:
    broker: ths                        # ths / yjb / yh
    confirm: true                      # 下单前确认
  crypto:
    exchange: binance
    api_key: "${CRYPTO_API_KEY}"
    secret: "${CRYPTO_SECRET}"

# ===== 风控配置 =====
risk:
  rules:
    max_position:
      enabled: true
      max_pct: 0.3
    max_daily_trades:
      enabled: true
      max_count: 20
    stop_loss:
      enabled: true
      loss_pct: 0.05
    take_profit:
      enabled: false
      profit_pct: 0.15
    max_drawdown:
      enabled: true
      max_dd: 0.10
    max_daily_loss:
      enabled: true
      max_loss: 0.03
    max_holding:
      enabled: true
      max_count: 10
    min_cash:
      enabled: true
      min_pct: 0.10

# ===== 仓位管理 =====
position:
  sizer: fixed_percent                 # fixed_amount / fixed_percent / kelly / equal_risk
  fixed_amount:
    amount: 10000
  fixed_percent:
    pct: 0.1
  kelly:
    win_rate: 0.5
    profit_loss_ratio: 2.0
    fraction: 0.5
  equal_risk:
    target_risk: 0.01
    lookback: 20

# ===== 通知配置 =====
notify:
  webhooks: []
  # - type: wecom
  #   url: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx"
  #   secret: ""
  # - type: telegram
  #   url: "https://api.telegram.org/botXXX/sendMessage"
  #   secret: ""

# ===== 日志配置 =====
log:
  level: INFO
  path: "./logs"
  rotation: "1 day"
  retention: "30 days"
```

### 6.2 声明式策略 YAML schema

```yaml
# 策略元信息
name: string              # 策略名称（必填）
market: a_stock | crypto  # 市场（必填）
symbols: [string]         # 交易标的列表（必填）
timeframe: string         # K线周期（必填）

# 入场条件
entry:
  condition: string       # 条件表达式（必填）
  action: buy | sell      # 动作（必填）
  amount: number          # 数量（必填）
  order_type: market | limit  # 订单类型（默认 market）
  price: number           # 限价单价格（限价单时必填）

# 出场条件
exit:
  condition: string       # 条件表达式（必填）
  action: buy | sell      # 动作（必填）
  amount: number          # 数量（必填）
  order_type: market | limit
  price: number

# 策略级风控（覆盖默认配置）
risk:
  stop_loss: number       # 止损线（可选）
  take_profit: number     # 止盈线（可选）
  max_position_pct: number # 单标的最大仓位（可选）

# 策略参数（可选，用于参数化）
params:
  key: value
```

---

## 7. Streamlit 页面设计

### 7.1 页面路由

```python
# duant/web/app.py
import streamlit as st

pg = st.navigation([
    st.Page("pages/dashboard.py", title="仪表盘", icon="📊"),
    st.Page("pages/strategy.py", title="策略管理", icon="🧠"),
    st.Page("pages/backtest.py", title="回测中心", icon="🔬"),
    st.Page("pages/position.py", title="持仓监控", icon="💰"),
    st.Page("pages/trades.py", title="交易记录", icon="📋"),
    st.Page("pages/data.py", title="数据管理", icon="🗄️"),
    st.Page("pages/risk.py", title="风控配置", icon="🛡️"),
    st.Page("pages/settings.py", title="系统设置", icon="⚙️"),
])
pg.run()
```

### 7.2 各页面布局

#### 仪表盘 (dashboard.py)

```
┌──────────────────────────────────────────────────┐
│  仪表盘                                          │
├──────────────────────────────────────────────────┤
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌────────┐│
│  │ 总资产   │ │ 今日盈亏 │ │ 持仓数   │ │ 运行中  ││
│  │ ¥1.2M  │ │ +1.5%   │ │ 5       │ │ 2策略  ││
│  └─────────┘ └─────────┘ └─────────┘ └────────┘│
│                                                  │
│  ┌──────────────────────────────────────────────┐│
│  │ 收益曲线 (plotly line chart)                  ││
│  │   - 总资产曲线                                ││
│  │   - 回撤曲线                                  ││
│  └──────────────────────────────────────────────┘│
│                                                  │
│  ┌──────────────────────────────────────────────┐│
│  │ 持仓概览 (dataframe)                          ││
│  │   标的 | 数量 | 市值 | 盈亏 | 占比            ││
│  └──────────────────────────────────────────────┘│
│                                                  │
│  ┌──────────────────────────────────────────────┐│
│  │ 最近交易 (最近5条)                             ││
│  └──────────────────────────────────────────────┘│
└──────────────────────────────────────────────────┘
```

#### 回测中心 (backtest.py)

```
┌──────────────────────────────────────────────────┐
│  回测中心                                         │
├──────────────────────────────────────────────────┤
│  ┌── 配置区 ─────────────────────────────────────┐│
│  │ 策略: [下拉选择]  标的: [多选]  周期: [下拉]   ││
│  │ 起始: [日期]  结束: [日期]  初始资金: [输入]   ││
│  │ [运行回测]                                     ││
│  └───────────────────────────────────────────────┘│
│                                                  │
│  ┌── 结果区 ─────────────────────────────────────┐│
│  │ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐          ││
│  │ │总收益 │ │年化  │ │最大回撤│ │夏普  │          ││
│  │ │+25%  │ │+18%  │ │-8%   │ │1.5   │          ││
│  │ └──────┘ └──────┘ └──────┘ └──────┘          ││
│  │                                                ││
│  │ 收益曲线 + 回撤曲线 (plotly)                    ││
│  │                                                ││
│  │ 交易明细 (可排序 dataframe)                     ││
│  │ [导出CSV]                                      ││
│  └───────────────────────────────────────────────┘│
└──────────────────────────────────────────────────┘
```

#### 其他页面

| 页面 | 核心组件 |
|------|----------|
| 策略管理 | 策略列表(表格) + 启停按钮 + 参数编辑表单 + 运行日志 |
| 持仓监控 | 持仓表格 + 个股盈亏柱状图 + 仓位占比饼图 |
| 交易记录 | 可筛选/排序的成交表格 + 日期范围选择器 + 导出按钮 |
| 数据管理 | 标的列表 + 数据状态(最新日期/行数) + 下载/更新按钮 + 校验结果 |
| 风控配置 | 规则开关(toggle) + 参数输入 + 触发历史表格 |
| 系统设置 | 券商/交易所配置表单 + 通知配置 + 系统参数 |

---

## 8. CLI 入口设计

```python
# duant/cli.py
import click

@click.group()
def cli():
    """duant - 个人量化交易系统"""

@cli.command()
@click.option("--strategy", "-s", required=True, help="策略名称")
@click.option("--symbol", multiple=True, help="交易标的")
@click.option("--start", help="开始日期 YYYY-MM-DD")
@click.option("--end", help="结束日期 YYYY-MM-DD")
@click.option("--cash", default=1000000, help="初始资金")
def backtest(strategy, symbol, start, end, cash):
    """运行回测"""

@cli.command()
@click.option("--strategy", "-s", required=True, help="策略名称")
def paper(strategy):
    """启动模拟盘"""

@cli.command()
@click.option("--strategy", "-s", required=True, help="策略名称")
def live(strategy):
    """启动实盘交易"""

@cli.command()
@click.option("--port", default=8501, help="端口号")
def web(port):
    """启动 Web UI"""

@cli.command()
@click.option("--symbol", multiple=True, help="标的代码")
@click.option("--market", type=click.Choice(["a_stock", "crypto"]), required=True)
@click.option("--timeframe", default="1d", help="K线周期")
def update(symbol, market, timeframe):
    """增量更新行情数据"""
```

---

## 9. 依赖清单

```
# pyproject.toml [project.dependencies]
python = ">=3.12"
pandas = ">=2.2"
numpy = ">=1.26"
pyarrow = ">=15.0"          # Parquet 读写
tushare = ">=1.4"
akshare = ">=1.14"
ccxt = ">=4.0"
streamlit = ">=1.35"
plotly = ">=5.20"
loguru = ">=0.7"
click = ">=8.1"
pyyaml = ">=6.0"
```

可选依赖（按需安装）：

```
# 实盘网关
xtquant = ">=1.0"           # QMT 网关
easytrader = ">=0.21"       # 模拟登录网关

# 加密货币 websocket
websockets = ">=12.0"
```
