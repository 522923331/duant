"""模拟盘引擎"""

import threading
import time
from datetime import datetime, timedelta

import pandas as pd
from loguru import logger

from duant.backtest.engine import BacktestOrderHandler, Portfolio
from duant.backtest.matcher import OrderMatcher
from duant.core.config import BacktestConfig, load_config
from duant.core.event import (
    Bar,
    Market,
    Order,
    OrderSide,
    OrderStatus,
    Position,
    TimeFrame,
    Trade,
)
from duant.data.fetcher import DataFetcher
from duant.data.sqlite_store import SqliteStore
from duant.notify.webhook import Notifier
from duant.risk.manager import RiskManager
from duant.strategy.base import Context, DataBuffer, StrategyBase
from duant.strategy.indicators import IndicatorCalculator


class PaperEngine:
    """模拟盘引擎，实时行情驱动，虚拟成交"""

    def __init__(self, config=None, initial_cash: float = 1_000_000.0):
        if config is None:
            config = load_config()
        self.config = config
        self.portfolio = Portfolio(initial_cash)
        self.matcher = OrderMatcher(BacktestConfig())
        self.fetcher = DataFetcher(tushare_token=config.data.tushare_token)
        self.sqlite = SqliteStore(config.data.db_path)

        # 通知
        self.notifier = Notifier(config.notify.webhooks if config.notify.webhooks else None)

        # 风控
        self.risk_manager = RiskManager(config.risk, self.sqlite, self.notifier)

        self._running = False
        self._halted = False
        self._thread: threading.Thread | None = None
        self._buffer = DataBuffer(max_len=500)
        self._indicators = IndicatorCalculator(self._buffer)
        self._current_prices: dict[str, float] = {}
        self._last_bar_date: dict[str, str] = {}  # symbol -> last bar date

    def start(self, strategy: StrategyBase, symbol: str, market: Market,
              timeframe: TimeFrame = TimeFrame.DAILY) -> None:
        """启动模拟盘"""
        if self._running:
            logger.warning("模拟盘已在运行")
            return

        self._running = True
        self._halted = False

        # 从 SQLite 恢复状态
        self._restore_state()

        # 初始化策略
        order_handler = BacktestOrderHandler()
        account = self.portfolio.get_account(self._current_prices)
        ctx = Context(
            account=account,
            indicators=self._indicators,
            data_buffer=self._buffer,
            order_handler=order_handler,
        )
        strategy.set_context(ctx)
        strategy.on_start()

        # 记录策略状态
        self.sqlite.save_strategy_state(
            strategy.__class__.__name__, "running", "paper",
            {"symbol": symbol, "market": market.value, "timeframe": timeframe.value},
        )

        # 启动行情轮询线程
        self._thread = threading.Thread(
            target=self._poll_market,
            args=(strategy, symbol, market, timeframe, order_handler),
            daemon=True,
        )
        self._thread.start()

        logger.info(f"模拟盘启动: {symbol} {market.value} {timeframe.value}")

    def stop(self, strategy_name: str = "") -> None:
        """停止模拟盘，持久化状态"""
        self._running = False

        if self._thread:
            self._thread.join(timeout=10)
            self._thread = None

        # 持久化到 SQLite
        self._save_state()

        # 更新策略状态
        name = strategy_name or "paper_strategy"
        self.sqlite.save_strategy_state(name, "stopped", "paper", {})

        logger.info("模拟盘已停止")

    def resume(self) -> None:
        """恢复被风控暂停的交易"""
        self._halted = False
        self.risk_manager.resume()
        logger.info("模拟盘交易已恢复")

    def _poll_market(self, strategy: StrategyBase, symbol: str,
                     market: Market, timeframe: TimeFrame,
                     order_handler: BacktestOrderHandler) -> None:
        """行情轮询"""
        if market == Market.A_STOCK:
            self._poll_a_stock(strategy, symbol, timeframe, order_handler)
        elif market == Market.CRYPTO:
            self._poll_crypto(strategy, symbol, timeframe, order_handler)

    def _poll_a_stock(self, strategy: StrategyBase, symbol: str,
                      timeframe: TimeFrame, order_handler: BacktestOrderHandler) -> None:
        """A股行情轮询（每 5 秒拉一次实时行情）"""
        interval = 5
        consecutive_errors = 0

        while self._running:
            try:
                # 判断是否在交易时间
                now = datetime.now()
                if not self._is_trading_time(now):
                    time.sleep(30)
                    continue

                # 拉取最新数据
                end = now
                start = now - timedelta(days=5)
                df = self.fetcher.fetch_bars(symbol, Market.A_STOCK, timeframe, start, end)

                if not df.empty:
                    latest = df.iloc[-1]
                    bar = Bar(
                        symbol=symbol,
                        market=Market.A_STOCK,
                        timeframe=timeframe,
                        datetime=df.index[-1].to_pydatetime() if hasattr(df.index[-1], "to_pydatetime") else df.index[-1],
                        open=float(latest["open"]),
                        high=float(latest["high"]),
                        low=float(latest["low"]),
                        close=float(latest["close"]),
                        pre_close=float(latest.get("pre_close", 0)),
                        volume=float(latest.get("volume", 0)),
                        amount=float(latest.get("amount", 0)),
                        turnover=float(latest.get("turnover", 0)),
                        circ_market_cap=float(latest.get("circ_market_cap", 0)),
                    )

                    # 只处理新的 bar（避免重复处理同一根K线）
                    bar_date = bar.datetime.strftime("%Y-%m-%d %H:%M")
                    if bar_date != self._last_bar_date.get(symbol):
                        self._last_bar_date[symbol] = bar_date
                        self._process_bar(bar, strategy, order_handler)

                consecutive_errors = 0  # 重置错误计数

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"行情轮询异常 ({consecutive_errors}): {e}")
                if consecutive_errors >= 10:
                    logger.critical("连续 10 次行情异常，暂停策略")
                    self._halted = True
                    self.notifier.send("模拟盘异常", f"连续 {consecutive_errors} 次行情获取失败", "error")
                    consecutive_errors = 0  # 下次恢复后重试

            time.sleep(interval)

    def _poll_crypto(self, strategy: StrategyBase, symbol: str,
                     timeframe: TimeFrame, order_handler: BacktestOrderHandler) -> None:
        """加密货币行情轮询"""
        interval_map = {
            TimeFrame.MIN_1: 10,
            TimeFrame.MIN_5: 30,
            TimeFrame.MIN_15: 60,
            TimeFrame.HOUR_1: 120,
            TimeFrame.DAILY: 300,
        }
        interval = interval_map.get(timeframe, 30)
        consecutive_errors = 0

        while self._running:
            try:
                end = datetime.now()
                start = end - timedelta(hours=6)
                df = self.fetcher.fetch_bars(symbol, Market.CRYPTO, timeframe, start, end)

                if not df.empty:
                    latest = df.iloc[-1]
                    bar = Bar(
                        symbol=symbol,
                        market=Market.CRYPTO,
                        timeframe=timeframe,
                        datetime=df.index[-1].to_pydatetime() if hasattr(df.index[-1], "to_pydatetime") else df.index[-1],
                        open=float(latest["open"]),
                        high=float(latest["high"]),
                        low=float(latest["low"]),
                        close=float(latest["close"]),
                        pre_close=0,
                        volume=float(latest.get("volume", 0)),
                        amount=float(latest.get("amount", 0)),
                    )

                    bar_date = bar.datetime.strftime("%Y-%m-%d %H:%M")
                    if bar_date != self._last_bar_date.get(symbol):
                        self._last_bar_date[symbol] = bar_date
                        self._process_bar(bar, strategy, order_handler)

                consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"加密货币行情轮询异常 ({consecutive_errors}): {e}")
                if consecutive_errors >= 10:
                    logger.critical("连续 10 次行情异常，暂停策略")
                    self._halted = True
                    self.notifier.send("模拟盘异常", f"连续 {consecutive_errors} 次行情获取失败", "error")
                    consecutive_errors = 0

            time.sleep(interval)

    def _process_bar(self, bar: Bar, strategy: StrategyBase,
                     order_handler: BacktestOrderHandler) -> None:
        """处理单根 bar：推策略 → 风控 → 撮合 → 更新"""
        self._buffer.append(bar)
        self._current_prices[bar.symbol] = bar.close
        self.portfolio.update_price(bar.symbol, bar.close)

        # 市场级风控检查
        if self.risk_manager:
            events = self.risk_manager.check_market(self.portfolio)
            if events:
                self._halted = True
                for event in events:
                    if event.action.value in ("halt", "pause"):
                        logger.error(f"风控触发: {event.detail}")

        # 策略计算（未被风控暂停时）
        order_handler.pending_orders.clear()
        if not self._halted:
            try:
                strategy.on_bar(bar)
            except Exception as e:
                logger.error(f"策略异常: {e}")
                return

        # 撮合订单
        for order in order_handler.pending_orders:
            # 风控检查
            if self.risk_manager:
                passed, reason = self.risk_manager.check(order, self.portfolio)
                if not passed:
                    self.sqlite.save_order(order)
                    self.sqlite.update_order_status(order.order_id, OrderStatus.REJECTED, 0, reason)
                    continue

            trade = self.matcher.match(order, bar)
            if trade:
                self.portfolio.apply_trade(trade)
                # 保存交易记录
                self.sqlite.save_order(order)
                self.sqlite.save_trade(trade)
                self.sqlite.update_order_status(order.order_id, OrderStatus.FILLED, trade.amount)
                # 发送通知
                self.notifier.send_trade(trade)

        # 更新账户
        account = self.portfolio.get_account()
        strategy.context._account = account

        # 每日净值快照
        today = bar.datetime.strftime("%Y-%m-%d")
        self.portfolio.snapshot_equity(today)
        market_value = sum(
            self._current_prices.get(s, pos["avg_price"]) * pos["quantity"]
            for s, pos in self.portfolio.positions.items()
        )
        self.sqlite.save_daily_equity(
            today, "paper",
            self.portfolio.cash,
            market_value,
            self.portfolio.get_total_value(),
            self.portfolio._realized_pnl,
        )

    def _restore_state(self) -> None:
        """从 SQLite 恢复持仓和账户状态"""
        positions = self.sqlite.get_latest_positions()
        if positions:
            for p in positions:
                self.portfolio._positions[p.symbol] = {
                    "quantity": p.quantity,
                    "avg_price": p.avg_price,
                    "market": p.market,
                }
                self._current_prices[p.symbol] = p.current_price
                self.portfolio.update_price(p.symbol, p.current_price)

            # 从最新净值恢复现金
            equity = self.sqlite.get_equity_curve("paper")
            if not equity.empty:
                self.portfolio.cash = float(equity.iloc[-1]["cash"])

            logger.info(f"从 SQLite 恢复状态: {len(positions)} 个持仓")

    def _save_state(self) -> None:
        """持久化持仓到 SQLite"""
        positions = []
        now = datetime.now()
        for sym, pos in self.portfolio._positions.items():
            current_price = self._current_prices.get(sym, pos["avg_price"])
            mv = current_price * pos["quantity"]
            unrealized = (current_price - pos["avg_price"]) * pos["quantity"]
            positions.append(Position(
                symbol=sym,
                market=pos["market"],
                quantity=pos["quantity"],
                avg_price=pos["avg_price"],
                current_price=current_price,
                unrealized_pnl=unrealized,
                market_value=mv,
                updated_at=now,
            ))

        self.sqlite.save_position_snapshot(positions, now)
        logger.info(f"持仓已保存: {len(positions)} 个")

    @staticmethod
    def _is_trading_time(dt: datetime) -> bool:
        """判断是否在 A股交易时间（9:30-11:30, 13:00-15:00）"""
        if dt.weekday() >= 5:
            return False
        t = dt.time()
        from datetime import time as dt_time
        morning = dt_time(9, 30) <= t <= dt_time(11, 30)
        afternoon = dt_time(13, 0) <= t <= dt_time(15, 0)
        return morning or afternoon
