# duant - 个人量化交易系统需求文档

> 麻雀虽小，五脏俱全。个人使用，简单可靠。

---

## 1. 项目概述

### 1.1 定位

duant 是一个面向个人投资者的轻量级量化交易系统，覆盖从策略研究到实盘交易的全链路。不追求大而全的平台化，而是追求**小而精**——每个模块都可用、可靠、可维护。

### 1.2 核心原则

| 原则 | 含义 |
|------|------|
| **简单优先** | 宁可少做，不做复杂。能用 100 行解决的绝不写 200 行 |
| **个人适配** | 不考虑多用户、权限、分布式，只服务一个人 |
| **数据可靠** | 行情数据必须准确，回测结果必须可复现 |
| **实盘安全** | 风控兜底，异常不丢钱。下单前必须过风控 |
| **可观测** | 所有操作有日志，所有状态可查，出问题能追溯 |

### 1.3 目标市场

- **A股**：沪深股票、ETF、可转债
- **加密货币**：主流币种（BTC、ETH 等），主流交易所（Binance、OKX 等）

---

## 2. 技术栈

| 类别 | 选型 | 理由 |
|------|------|------|
| 语言 | Python 3.12+ | 生态最丰富，策略开发效率高 |
| 数据处理 | pandas + numpy | 标准选择，无替代必要 |
| 数据源-A股 | tushare（主）/ akshare（备） | tushare 数据稳定可靠、接口规范、会员权限覆盖全；akshare 免费但不稳定，作为 tushare 不可用时的降级备选 |
| 数据源-加密 | ccxt | 统一接口对接 100+ 交易所 |
| 实盘-A股 | xtquant（miniQMT）/ easytrader（过渡） | QMT 模式：10 万+可开通，接口稳定，首选；模拟登录模式：UI 自动化下单，低频可用，QMT 开通前的过渡 |
| 实盘-加密 | ccxt | 同数据源，接口统一 |
| 数据存储 | Parquet（行情）+ SQLite（交易记录） | 列式压缩存储，回测读取快 5-10 倍，磁盘占用小 3-5 倍；SQLite 存交易/持仓等结构化数据 |
| 回测引擎 | 自研（向量化 + 事件驱动混合） | 向量化做快速筛选，事件驱动做精确验证 |
| Web UI | Streamlit | 最轻量的 Python Web 方案，适合个人 |
| 配置格式 | YAML | 可读性好，适合声明式策略 |
| 日志 | loguru | 比标准库好用，零配置 |
| 通知 | 企业微信/Telegram webhook | 个人即时通知，无需自建服务 |
| 包管理 | uv | 快，现代化 |

**不引入**：MySQL、PostgreSQL、Redis、Docker、消息队列、微服务——个人项目不需要企业级基础设施。行情数据是 OLAP 模式（低频批量写入、全量读取计算），列式文件比行式数据库更适合；交易记录数据量小，SQLite 足够且零运维。

---

## 3. 功能模块详细需求

### 3.1 数据模块（duant/data）

#### 3.1.1 行情获取

| 功能 | 要求 |
|------|------|
| A股日K/分钟K | 通过 tushare 获取（主），akshare 降级备选，支持指定日期范围 |
| A股实时行情 | 盘中 tick 级别数据（miniQMT 连接时可用） |
| 加密货币K线 | 通过 ccxt 获取，支持 1m/5m/15m/1h/4h/1d |
| 加密货币实时 | ccxt websocket 推送 |
| 复权处理 | A股默认前复权 |
| 数据缓存 | 本地 Parquet 文件缓存，避免重复请求 |

#### 3.1.2 数据存储

**行情数据 → Parquet（列式压缩文件）**

- 按市场/周期/标的分文件存储，组织结构：

```
data/
├── a_stock/
│   ├── daily/
│   │   ├── 000001.SZ.parquet
│   │   ├── 600519.SH.parquet
│   │   └── ...
│   └── minute/
│       ├── 000001.SZ.parquet
│       └── ...
└── crypto/
    ├── 1d/
    │   ├── BTC_USDT.parquet
    │   └── ...
    └── 1h/
        └── ...
```

- 列定义（A股）：`datetime, open, high, low, close, pre_close, volume, amount, turnover, circ_market_cap`
- 列定义（加密货币）：`datetime, open, high, low, close, volume, amount, trades`
- `pre_close`：昨收价，涨跌停判断必需，不可从 OHLCV 推算
- `turnover`：换手率，策略常用，不可从 OHLCV 推算
- `circ_market_cap`：流通市值，仓位管理/筛选常用，不可从 OHLCV 推算
- 派生数据（涨跌额、涨跌幅等）不存储，由程序计算
- `datetime` 作为索引列，支持 pandas 时间切片过滤
- 回测时一次性读入内存，全量顺序扫描，I/O 不是瓶颈

**交易记录/持仓/风控日志 → SQLite**

- 单文件数据库 `duant.db`，存放结构化事务数据
- 表：`orders`（订单）、`positions`（持仓快照）、`risk_events`（风控事件）、`strategy_state`（策略状态）
- 数据量小（远小于行情），需要事务保障，SQLite 合适

**为什么不选 MySQL**：行情数据访问模式是 OLAP（低频批量写、全量读），列式存储天然优于行式数据库；个人项目零运维优先，MySQL 需要安装服务、配账号、做备份，收益抵不过运维成本。

#### 3.1.3 数据更新

- 支持增量更新（只拉取缺失日期的数据）
- 支持全量刷新（重新拉取指定时间段）
- 数据校验：检查缺失日期、异常值（涨跌停超限、成交量为零等）

### 3.2 策略模块（duant/strategy）

#### 3.2.1 声明式策略（YAML 配置）

无需写代码，通过 YAML 描述策略逻辑：

```yaml
name: "均线金叉"
market: a_stock
symbols: ["000001.SZ", "600519.SH"]
timeframe: "1d"

entry:
  condition: "cross_up(ma(close, 5), ma(close, 20))"
  action: buy
  amount: 100

exit:
  condition: "cross_down(ma(close, 5), ma(close, 20))"
  action: sell
  amount: 100

risk:
  stop_loss: 0.05        # 止损 5%
  take_profit: 0.15      # 止盈 15%
  max_position_pct: 0.3  # 单标的最大仓位 30%
```

声明式策略需支持的内置函数：

| 类别 | 函数 |
|------|------|
| 趋势 | ma, ema, macd, bollinger |
| 动量 | rsi, kdj, cci |
| 成交量 | obv, volume_ratio |
| 逻辑 | cross_up, cross_down, above, below, between |
| 组合 | and, or, not |

#### 3.2.2 编程式策略（Python 类）

适合复杂逻辑，继承基类实现：

```python
from duant.strategy import StrategyBase

class MyStrategy(StrategyBase):
    params = {
        "fast_period": 5,
        "slow_period": 20,
    }

    def on_bar(self, bar):
        fast_ma = self.indicators.ma(self.close, self.params["fast_period"])
        slow_ma = self.indicators.ma(self.close, self.params["slow_period"])

        if self.cross_up(fast_ma, slow_ma):
            self.buy(bar.symbol, amount=100)
        elif self.cross_down(fast_ma, slow_ma):
            self.sell(bar.symbol, amount=100)
```

策略基类必须提供的接口：

| 接口 | 说明 |
|------|------|
| `on_bar(bar)` | K 线回调 |
| `on_tick(tick)` | Tick 回调（实盘/模拟盘用） |
| `on_order(order)` | 订单状态变化回调 |
| `buy/sell/short/cover` | 下单接口 |
| `get_position(symbol)` | 查询持仓 |
| `get_cash()` | 查询现金 |
| `indicators` | 技术指标计算器 |
| `cross_up/cross_down` | 交叉判断 |

#### 3.2.3 策略管理

- 策略注册：所有策略（声明式和编程式）统一注册到策略管理器
- 策略参数：支持运行时参数覆盖
- 策略组合：多个策略可组合运行，各自独立计算信号

### 3.3 回测引擎（duant/backtest）

#### 3.3.1 核心能力

| 功能 | 要求 |
|------|------|
| 数据驱动 | 逐 bar 推送，模拟真实行情序列 |
| 订单模拟 | 支持限价单、市价单，考虑滑点和手续费 |
| 滑点模型 | 默认固定滑点，可选百分比滑点 |
| 手续费模型 | A股：万2.5 + 印花税千1（卖出）；加密：0.1% |
| 资金管理 | 初始资金可配，现金不足时拒绝买入 |
| 成交规则 | A股：100 股整手；加密：按最小下单量 |
| 涨跌停处理 | A股涨停无法买入、跌停无法卖出 |

#### 3.3.2 性能指标

回测完成后必须输出以下指标：

| 指标 | 说明 |
|------|------|
| 总收益率 | (期末资金 - 初始资金) / 初始资金 |
| 年化收益率 | 按交易日折算 |
| 最大回撤 | 峰值到谷值的最大跌幅 |
| 夏普比率 | (年化收益 - 无风险利率) / 年化波动率 |
| 胜率 | 盈利交易次数 / 总交易次数 |
| 盈亏比 | 平均盈利 / 平均亏损 |
| 交易次数 | 总交易次数 |
| 收益曲线 | 每日净值序列 |

#### 3.3.3 回测报告

- 控制台输出核心指标摘要
- Streamlit 页面展示收益曲线、回撤曲线、交易明细
- 导出 CSV（交易记录 + 每日净值）

### 3.4 模拟盘（duant/paper）

模拟盘是回测和实盘之间的桥梁，用实时行情驱动策略，但不真实下单。

| 功能 | 要求 |
|------|------|
| 行情源 | A股：akshare 实时接口（延迟几秒）；加密：ccxt websocket |
| 订单执行 | 按实时价格模拟成交，记录虚拟持仓和盈亏 |
| 状态持久化 | SQLite 存储模拟盘状态，重启后恢复 |
| 与实盘一致 | 策略代码、下单接口与实盘完全一致，切换只需改配置 |

### 3.5 实盘交易（duant/trade）

#### 3.5.1 交易网关模式

A股实盘支持两种网关模式，通过配置切换，策略代码无需改动：

| 模式 | 接口 | 说明 |
|------|------|------|
| **QMT 模式**（推荐） | xtquant (miniQMT) | 10 万+资产可开通，接口稳定，程序化下单，首选方案 |
| **模拟登录模式**（过渡） | easytrader / 同花顺客户端 | 通过 UI 自动化操作券商客户端下单，无需额外权限；适合低频交易（每日 1-2 次），开通 QMT 前的过渡方案 |
| 加密货币 | ccxt | 统一接口，配置 apiKey/secret，无门槛 |

**模拟登录模式说明**：
- 原理：程序控制同花顺/通达信客户端窗口，模拟鼠标键盘操作完成下单
- 适用场景：QMT 权限未开通前的过渡期，低频交易（每日 1-2 次）
- 限制：依赖客户端 UI 稳定性，速度慢（秒级），不适合高频；客户端不能最小化/被遮挡
- 安全：下单前弹窗确认（可配置跳过），防误操作
- 迁移：切换到 QMT 模式只需改配置项 `trade.gateway: qmt`，策略代码零改动

#### 3.5.2 交易接口

统一抽象层，策略代码不感知底层差异：

```python
class TradeGateway(ABC):
    @abstractmethod
    def buy(self, symbol, price, amount) -> Order: ...

    @abstractmethod
    def sell(self, symbol, price, amount) -> Order: ...

    @abstractmethod
    def cancel(self, order_id) -> bool: ...

    @abstractmethod
    def get_position(self, symbol) -> Position: ...

    @abstractmethod
    def get_balance(self) -> float: ...

    @abstractmethod
    def get_orders(self) -> list[Order]: ...
```

#### 3.5.3 安全机制

- **下单前风控检查**：每笔订单必须经过风控模块审核
- **确认机制**：大额订单（超过总资产 N%）需二次确认（可配置开关）
- **断线重连**：交易连接断开自动重试，重试期间暂停策略
- **状态同步**：启动时与券商同步持仓和订单状态，避免本地与实际不一致

### 3.6 风控模块（duant/risk）

风控是量化系统的安全阀，必须在任何交易执行前拦截。

#### 3.6.1 策略级风控

| 规则 | 默认值 | 说明 |
|------|--------|------|
| 单标的最大仓位 | 30% | 单只股票/币种不超过总资产的 30% |
| 单日最大交易次数 | 20 | 防止策略异常频繁交易 |
| 止损线 | -5% | 单笔亏损超限自动平仓 |
| 止盈线 | +15% | 单笔盈利超限自动平仓（可选） |

#### 3.6.2 账户级风控

| 规则 | 默认值 | 说明 |
|------|--------|------|
| 最大回撤限制 | 10% | 账户回撤超限暂停所有策略 |
| 每日最大亏损 | 3% | 当日亏损超限停止交易 |
| 最大持仓数 | 10 | 同时持有标的数量上限 |
| 最小现金保留 | 10% | 账户至少保留 10% 现金 |

#### 3.6.3 风控执行

- 风控规则通过 YAML 配置，支持启用/禁用每条规则
- 风控拦截时记录日志并发送通知
- 账户级风控触发时暂停策略，需手动恢复

### 3.7 仓位管理（duant/position）

| 方式 | 说明 |
|------|------|
| 固定金额 | 每次买入固定金额 |
| 固定比例 | 每次买入总资产的固定比例 |
| 凯利公式 | 根据胜率和盈亏比自动计算最优仓位 |
| 等风险 | 按标的波动率分配仓位，使每个标的风险贡献相等 |

仓位管理策略通过配置切换，策略代码无需关心。

### 3.8 Web UI（duant/web）

基于 Streamlit，提供以下页面：

| 页面 | 功能 |
|------|------|
| **仪表盘** | 账户概览（总资产、持仓、今日盈亏）、运行状态 |
| **策略管理** | 策略列表、启停控制、参数调整、运行日志 |
| **回测中心** | 选择策略 + 标的 + 时间范围，一键回测，展示结果 |
| **持仓监控** | 当前持仓明细、盈亏、占比 |
| **交易记录** | 历史成交记录、筛选、导出 |
| **数据管理** | 数据下载、更新、查看、校验 |
| **风控配置** | 风控规则开关、参数调整、触发历史 |
| **系统设置** | 券商/交易所配置、通知配置、系统参数 |

### 3.9 通知系统（duant/notify）

| 事件 | 通知方式 |
|------|----------|
| 订单成交 | webhook |
| 风控触发 | webhook（高优先级） |
| 策略异常 | webhook |
| 每日收盘 | 每日持仓和盈亏摘要 |

支持企业微信机器人和 Telegram Bot，通过 webhook URL 配置。

---

## 4. 项目目录结构

```
duant/
├── REQUIREMENTS.md          # 本文档
├── pyproject.toml           # 项目配置（uv 管理）
├── README.md                # 使用说明
├── config/
│   ├── default.yaml         # 默认配置
│   ├── strategies/          # 声明式策略 YAML 文件
│   └── risk.yaml            # 风控规则配置
├── duant/
│   ├── __init__.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── engine.py        # 主引擎（调度策略、行情、交易）
│   │   ├── event.py         # 事件定义（bar/tick/order/risk）
│   │   └── config.py        # 配置加载
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fetcher.py       # 行情获取（tushare + akshare + ccxt）
│   │   ├── parquet_store.py # Parquet 行情存储
│   │   ├── sqlite_store.py  # SQLite 交易记录存储
│   │   └── cache.py         # 数据缓存与增量更新
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── base.py          # 策略基类
│   │   ├── loader.py        # 策略加载器（YAML + Python）
│   │   ├── indicators.py    # 内置技术指标
│   │   └── yaml_parser.py   # YAML 声明式策略解析器
│   ├── backtest/
│   │   ├── __init__.py
│   │   ├── engine.py        # 回测引擎
│   │   ├── matcher.py       # 订单撮合器
│   │   └── report.py        # 回测报告生成
│   ├── paper/
│   │   ├── __init__.py
│   │   └── engine.py        # 模拟盘引擎
│   ├── trade/
│   │   ├── __init__.py
│   │   ├── gateway.py       # 交易网关抽象层
│   │   ├── qmt.py           # A股 QMT 网关（miniQMT，推荐）
│   │   ├── simulate.py      # A股模拟登录网关（easytrader，过渡方案）
│   │   └── crypto.py        # 加密货币 ccxt 网关
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── manager.py       # 风控管理器
│   │   └── rules.py         # 风控规则实现
│   ├── position/
│   │   ├── __init__.py
│   │   └── sizer.py         # 仓位管理
│   ├── notify/
│   │   ├── __init__.py
│   │   └── webhook.py       # Webhook 通知
│   └── web/
│       ├── __init__.py
│       └── app.py           # Streamlit 应用入口
├── strategies/               # 用户策略目录（编程式）
│   └── example.py
├── data/                     # 本地数据存储目录
│   ├── a_stock/             # A股 Parquet 行情数据
│   │   ├── daily/
│   │   └── minute/
│   ├── crypto/              # 加密货币 Parquet 行情数据
│   │   ├── 1d/
│   │   └── 1h/
│   └── duant.db             # SQLite 数据库（交易记录/持仓/风控）
└── logs/                     # 日志目录
```

**设计要点**：
- 扁平结构，最多两层包嵌套，不搞深层抽象
- 每个模块独立，依赖关系单向：`core → strategy → backtest/paper/trade → risk/position`
- 用户只需关心 `config/`、`strategies/`、`data/` 三个目录

---

## 5. 开发路线图

### Phase 1：数据与回测（MVP）

**目标**：能拉数据、写策略、跑回测

| 任务 | 优先级 |
|------|--------|
| 项目骨架搭建（pyproject.toml、目录结构） | P0 |
| 配置加载模块 | P0 |
| A股数据获取（tushare 主 + akshare 备）+ Parquet 存储 | P0 |
| 加密货币数据获取（ccxt） | P1 |
| 策略基类 + 技术指标 | P0 |
| 回测引擎 + 订单撮合 | P0 |
| 回测报告（控制台 + CSV） | P0 |
| YAML 声明式策略解析 | P1 |

### Phase 2：可视化与风控

**目标**：回测结果可视化，风控体系建立

| 任务 | 优先级 |
|------|--------|
| Streamlit 仪表盘 + 回测页面 | P0 |
| 风控模块（策略级 + 账户级） | P0 |
| 仓位管理 | P1 |
| 回测报告 Streamlit 展示 | P1 |

### Phase 3：模拟盘与实盘

**目标**：从回测走向实盘

| 任务 | 优先级 |
|------|--------|
| 模拟盘引擎 | P0 |
| 交易网关抽象层 | P0 |
| A股 QMT 实盘网关 | P1 |
| A股模拟登录网关（easytrader，过渡方案） | P2 |
| 加密货币 ccxt 实盘网关 | P1 |
| Webhook 通知 | P1 |
| Streamlit 策略管理/持仓/交易记录页面 | P1 |

### Phase 4：打磨

**目标**：稳定可靠，日常可用

| 任务 | 优先级 |
|------|--------|
| 数据校验与异常值处理 | P0 |
| 断线重连与状态恢复 | P1 |
| 每日报告 | P2 |
| 策略组合运行 | P2 |
| 数据管理页面 | P2 |

---

## 6. 非功能性需求

### 6.1 数据可靠性

- 行情数据获取失败自动重试（最多 3 次，指数退避）
- 数据写入前校验：OHLC 关系合法（open/high/low/close 在合理范围）
- 回测结果必须可复现：固定随机种子，相同输入相同输出

### 6.2 错误处理

- 策略异常不崩溃：捕获策略内部异常，记录日志，跳过该 bar 继续
- 交易失败不丢失：下单失败记录到数据库，支持手动重试
- 风控触发有兜底：风控模块本身异常时，默认拒绝交易

### 6.3 日志

- 统一使用 loguru
- 日志级别：DEBUG（开发）、INFO（运行）、WARNING（风控/异常）、ERROR（错误）
- 日志文件按日切割，保留 30 天
- 关键操作必打日志：下单、成交、风控触发、策略启停、数据更新

### 6.4 性能

- 回测速度目标：A股单标的日K 10 年数据 < 5 秒（Parquet 读取 < 50ms，主要耗时在策略计算）
- 数据缓存命中率 > 80%（二次运行时）
- Streamlit 页面加载 < 3 秒

### 6.5 安全

- API Key / Secret 不硬编码，通过环境变量或加密配置文件读取
- 实盘交易默认关闭，需显式配置 `live_mode: true`
- 所有大额操作记录审计日志

---

## 7. 约定

### 7.1 代码风格

- 类型注解：所有函数必须加参数和返回值类型注解
- 不可变数据：行情数据、订单数据使用 dataclass，创建后不修改
- 简单命名：`buy()` 不叫 `execute_buy_order()`，`on_bar()` 不叫 `handle_bar_event()`

### 7.2 配置优先级

命令行参数 > 环境变量 > 用户配置文件 > 默认配置文件

### 7.3 运行模式

```bash
# 回测
duant backtest --strategy ma_cross --symbol 000001.SZ --start 2024-01-01 --end 2025-01-01

# 模拟盘
duant paper --strategy ma_cross

# 实盘
duant live --strategy ma_cross

# Web UI
duant web
```
