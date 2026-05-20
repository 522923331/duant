"""回测引擎"""

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from loguru import logger

from duant.core.config import BacktestConfig
from duant.core.event import (
    Account,
    Bar,
    Market,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    TimeFrame,
    Trade,
)
from duant.data.parquet_store import ParquetStore
from duant.strategy.base import Context, DataBuffer, OrderHandler, StrategyBase
from duant.strategy.indicators import IndicatorCalculator
from duant.backtest.matcher import OrderMatcher
from duant.backtest.report import BacktestMetrics, BacktestResult, calculate_metrics


class Portfolio:
    """回测中的虚拟账户"""

    def __init__(self, initial_cash: float):
        self.initial_cash = initial_cash
        self.cash: float = initial_cash
        self._positions: dict[str, dict] = {}  # symbol -> {quantity, avg_price, market}
        self._latest_prices: dict[str, float] = {}  # symbol -> latest close price
        self.trades: list[Trade] = []
        self.equity_records: list[dict] = []
        self._peak_value: float = initial_cash
        self._realized_pnl: float = 0.0
        self._daily_start_value: float = initial_cash  # 当日起始净值

    @property
    def positions(self) -> dict[str, dict]:
        return self._positions

    def apply_trade(self, trade: Trade) -> None:
        """应用成交，更新现金和持仓"""
        trade_value = trade.price * trade.amount

        if trade.side == OrderSide.BUY:
            cost = trade_value + trade.commission
            if cost > self.cash:
                logger.warning(f"资金不足，跳过买入: {trade.symbol}, 需要 {cost:.2f}, 可用 {self.cash:.2f}")
                return

            self.cash -= cost
            if trade.symbol in self._positions:
                pos = self._positions[trade.symbol]
                total_qty = pos["quantity"] + trade.amount
                pos["avg_price"] = (pos["avg_price"] * pos["quantity"] + trade_value) / total_qty
                pos["quantity"] = total_qty
            else:
                self._positions[trade.symbol] = {
                    "quantity": trade.amount,
                    "avg_price": trade.price,
                    "market": trade.market,
                }
        else:  # SELL
            if trade.symbol not in self._positions or self._positions[trade.symbol]["quantity"] < trade.amount:
                logger.warning(f"持仓不足，跳过卖出: {trade.symbol}")
                return

            pos = self._positions[trade.symbol]
            pnl = (trade.price - pos["avg_price"]) * trade.amount - trade.commission
            self._realized_pnl += pnl
            self.cash += trade_value - trade.commission
            pos["quantity"] -= trade.amount

            if pos["quantity"] <= 0:
                del self._positions[trade.symbol]

        self.trades.append(trade)

    def update_price(self, symbol: str, price: float) -> None:
        """更新标的最新价格"""
        self._latest_prices[symbol] = price

    def get_total_value(self, prices: dict[str, float] | None = None) -> float:
        """总资产 = cash + 持仓市值"""
        market_value = 0.0
        for sym, pos in self._positions.items():
            price = (prices or self._latest_prices).get(sym, pos["avg_price"])
            market_value += price * pos["quantity"]
        return self.cash + market_value

    def get_account(self, prices: dict[str, float] | None = None) -> Account:
        """获取当前账户状态"""
        positions_list = []
        market_value = 0.0
        now = datetime.now()

        for sym, pos in self._positions.items():
            current_price = (prices or self._latest_prices).get(sym, pos["avg_price"])
            mv = current_price * pos["quantity"]
            unrealized = (current_price - pos["avg_price"]) * pos["quantity"]
            market_value += mv

            positions_list.append(Position(
                symbol=sym,
                market=pos["market"],
                quantity=pos["quantity"],
                avg_price=pos["avg_price"],
                current_price=current_price,
                unrealized_pnl=unrealized,
                market_value=mv,
                updated_at=now,
            ))

        total = self.cash + market_value
        return Account(
            cash=self.cash,
            positions=tuple(positions_list),
            total_value=total,
            realized_pnl=self._realized_pnl,
            updated_at=now,
        )

    def snapshot_equity(self, date: str, prices: dict[str, float] | None = None) -> None:
        """记录每日净值"""
        total = self.get_total_value(prices)
        market_value = 0.0
        for sym, pos in self._positions.items():
            price = (prices or self._latest_prices).get(sym, pos["avg_price"])
            market_value += price * pos["quantity"]

        self._peak_value = max(self._peak_value, total)

        self.equity_records.append({
            "date": date,
            "cash": self.cash,
            "market_value": market_value,
            "total_value": total,
            "realized_pnl": self._realized_pnl,
        })

    def get_daily_pnl_pct(self) -> float:
        """当日盈亏比例"""
        if self._daily_start_value <= 0:
            return 0
        return (self.get_total_value() - self._daily_start_value) / self._daily_start_value


class BacktestOrderHandler(OrderHandler):
    """回测专用的订单处理器，收集订单由引擎撮合"""

    def __init__(self):
        self.pending_orders: list[Order] = []

    def submit(self, order: Order) -> Order:
        self.pending_orders.append(order)
        return order


class BacktestEngine:
    """回测引擎主类"""

    def __init__(self, config: BacktestConfig | None = None, data_path: str = "./data"):
        self.config = config or BacktestConfig()
        self.store = ParquetStore(data_path)
        self.matcher = OrderMatcher(self.config)
        self.risk_manager = None  # 可选接入风控
        self.position_sizer = None  # 可选接入仓位管理

    def set_risk_manager(self, risk_manager) -> None:
        """接入风控管理器"""
        self.risk_manager = risk_manager

    def set_position_sizer(self, position_sizer) -> None:
        """接入仓位管理器"""
        self.position_sizer = position_sizer

    def run(
        self,
        strategy: StrategyBase,
        symbols: list[str],
        start: datetime,
        end: datetime,
        market: Market = Market.A_STOCK,
        timeframe: TimeFrame = TimeFrame.DAILY,
    ) -> BacktestResult:
        """运行回测"""
        logger.info(f"回测开始: 策略={strategy.__class__.__name__}, 标的={symbols}, "
                     f"区间={start.date()}~{end.date()}, 初始资金={self.config.initial_cash:,.0f}")

        # 1. 加载行情数据
        all_bars: list[Bar] = []
        for symbol in symbols:
            df = self.store.load(symbol, market, timeframe, start, end)
            if df.empty:
                logger.warning(f"无数据: {symbol} {market.value} {timeframe.value}")
                continue
            for idx, row in df.iterrows():
                bar = Bar(
                    symbol=symbol, market=market, timeframe=timeframe,
                    datetime=idx.to_pydatetime() if hasattr(idx, "to_pydatetime") else idx,
                    open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row["close"]),
                    pre_close=float(row.get("pre_close", 0)),
                    volume=float(row.get("volume", 0)),
                    amount=float(row.get("amount", 0)),
                    turnover=float(row.get("turnover", 0)),
                    circ_market_cap=float(row.get("circ_market_cap", 0)),
                )
                all_bars.append(bar)

        if not all_bars:
            logger.error("无可用行情数据")
            return self._empty_result()

        # 2. 按时间排序
        all_bars.sort(key=lambda b: b.datetime)

        # 3. 初始化
        portfolio = Portfolio(self.config.initial_cash)
        buffer = DataBuffer(max_len=500)
        indicators = IndicatorCalculator(buffer)
        order_handler = BacktestOrderHandler()

        account = portfolio.get_account()
        ctx = Context(
            account=account,
            indicators=indicators,
            data_buffer=buffer,
            order_handler=order_handler,
            position_sizer=self.position_sizer,
        )
        ctx._portfolio = portfolio
        strategy.set_context(ctx)
        strategy.on_start()

        # 4. 逐 bar 推送
        current_date = ""
        strategy_halted = False

        for bar in all_bars:
            # 缓存 bar 数据
            buffer.append(bar)
            ctx.current_bar = bar

            # 更新最新价格
            portfolio.update_price(bar.symbol, bar.close)

            # 每日净值快照（在策略计算前，记录日起始值）
            bar_date = bar.datetime.strftime("%Y-%m-%d")
            if bar_date != current_date:
                if current_date:
                    portfolio.snapshot_equity(current_date)
                portfolio._daily_start_value = portfolio.get_total_value()
                current_date = bar_date

                # 市场级风控检查（新的一天）
                if self.risk_manager:
                    events = self.risk_manager.check_market(portfolio)
                    if events:
                        strategy_halted = True
                        for event in events:
                            logger.warning(f"风控触发: {event.detail}")

            # 策略计算（如果未被风控暂停）
            order_handler.pending_orders.clear()
            if not strategy_halted:
                try:
                    strategy.on_bar(bar)
                except Exception as e:
                    logger.error(f"策略异常 (bar={bar.datetime}): {e}")
                    continue

            # 撮合订单
            for order in order_handler.pending_orders:
                # 风控检查
                if self.risk_manager:
                    passed, reason = self.risk_manager.check(order, portfolio)
                    if not passed:
                        continue

                trade = self.matcher.match(order, bar)
                if trade:
                    portfolio.apply_trade(trade)

            # 更新账户
            ctx._account = portfolio.get_account()

        # 最后一天快照
        if current_date:
            portfolio.snapshot_equity(current_date)

        strategy.on_stop()

        # 5. 计算指标
        metrics = calculate_metrics(portfolio, self.config.initial_cash)
        equity_curve = pd.DataFrame(portfolio.equity_records)
        if not equity_curve.empty:
            equity_curve = equity_curve.set_index("date")

        result = BacktestResult(
            metrics=metrics,
            trades=tuple(portfolio.trades),
            equity_curve=equity_curve,
            positions=tuple(
                (sym, Position(
                    symbol=sym, market=pos["market"],
                    quantity=pos["quantity"], avg_price=pos["avg_price"],
                    current_price=portfolio._latest_prices.get(sym, pos["avg_price"]),
                    unrealized_pnl=(portfolio._latest_prices.get(sym, pos["avg_price"]) - pos["avg_price"]) * pos["quantity"],
                    market_value=portfolio._latest_prices.get(sym, pos["avg_price"]) * pos["quantity"],
                    updated_at=datetime.now(),
                ))
                for sym, pos in portfolio._positions.items()
            ),
        )

        logger.info(f"回测完成: 总收益率={metrics.total_return:.2%}, "
                     f"最大回撤={metrics.max_drawdown:.2%}, 夏普={metrics.sharpe_ratio:.2f}")

        return result

    def _empty_result(self) -> BacktestResult:
        return BacktestResult(
            metrics=BacktestMetrics(0, 0, 0, 0, 0, 0, 0),
            trades=(),
            equity_curve=pd.DataFrame(),
            positions=(),
        )
