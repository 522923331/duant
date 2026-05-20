"""A股模拟登录网关（easytrader，过渡方案）"""

from datetime import datetime
from loguru import logger

from duant.core.config import SimulateConfig
from duant.core.event import (
    Market,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)
from duant.trade.gateway import TradeGateway


class SimulateGateway(TradeGateway):
    """通过 easytrader 控制券商客户端，UI 自动化下单"""

    def __init__(self, config: SimulateConfig):
        self.config = config
        self.trader = None
        self._connected = False
        self.confirm_before_trade = config.confirm

    def connect(self) -> None:
        try:
            import easytrader
        except ImportError:
            raise ImportError(
                "easytrader 未安装，请运行: pip install easytrader\n"
                "模拟登录网关需要同花顺/通达信客户端运行"
            )

        self.trader = easytrader.use(self.config.broker)
        self.trader.connect()
        self._connected = True
        logger.info(f"模拟登录网关已连接: {self.config.broker}")

    def disconnect(self) -> None:
        self.trader = None
        self._connected = False
        logger.info("模拟登录网关已断开")

    def buy(self, symbol: str, price: float, amount: float) -> Order:
        self._ensure_connected()

        if self.confirm_before_trade:
            if not self._confirm("买入", symbol, price, amount):
                return self._rejected_order(symbol, OrderSide.BUY, price, amount, "用户取消")

        self.trader.buy(symbol, price=price, amount=int(amount))
        return Order(
            order_id=_gen_id(),
            symbol=symbol,
            market=Market.A_STOCK,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT if price > 0 else OrderType.MARKET,
            price=price,
            amount=amount,
            status=OrderStatus.SUBMITTED,
            strategy_name="duant",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    def sell(self, symbol: str, price: float, amount: float) -> Order:
        self._ensure_connected()

        if self.confirm_before_trade:
            if not self._confirm("卖出", symbol, price, amount):
                return self._rejected_order(symbol, OrderSide.SELL, price, amount, "用户取消")

        self.trader.sell(symbol, price=price, amount=int(amount))
        return Order(
            order_id=_gen_id(),
            symbol=symbol,
            market=Market.A_STOCK,
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT if price > 0 else OrderType.MARKET,
            price=price,
            amount=amount,
            status=OrderStatus.SUBMITTED,
            strategy_name="duant",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

    def cancel(self, order_id: str) -> bool:
        self._ensure_connected()
        try:
            self.trader.cancel_entrust(order_id)
            return True
        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return False

    def get_position(self, symbol: str) -> Position | None:
        positions = self.get_positions()
        for p in positions:
            if p.symbol == symbol:
                return p
        return None

    def get_positions(self) -> list[Position]:
        self._ensure_connected()
        try:
            raw = self.trader.position
            result = []
            for p in raw:
                result.append(Position(
                    symbol=p.get("证券代码", ""),
                    market=Market.A_STOCK,
                    quantity=float(p.get("股票余额", 0)),
                    avg_price=float(p.get("成本价", 0)),
                    current_price=float(p.get("当前价", 0)),
                    unrealized_pnl=float(p.get("盈亏", 0)),
                    market_value=float(p.get("股票市值", 0)),
                    updated_at=datetime.now(),
                ))
            return result
        except Exception as e:
            logger.error(f"查询持仓失败: {e}")
            return []

    def get_balance(self) -> float:
        self._ensure_connected()
        try:
            balance = self.trader.balance
            return float(balance.get("可用金额", 0))
        except Exception as e:
            logger.error(f"查询资金失败: {e}")
            return 0

    def get_orders(self) -> list[Order]:
        self._ensure_connected()
        try:
            raw = self.trader.today_entrusts
            result = []
            for o in raw:
                result.append(Order(
                    order_id=str(o.get("委托编号", "")),
                    symbol=o.get("证券代码", ""),
                    market=Market.A_STOCK,
                    side=OrderSide.BUY if "买入" in o.get("操作", "") else OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    price=float(o.get("委托价格", 0)),
                    amount=float(o.get("委托数量", 0)),
                    status=OrderStatus.SUBMITTED,
                    strategy_name="duant",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                ))
            return result
        except Exception as e:
            logger.error(f"查询委托失败: {e}")
            return []

    def is_connected(self) -> bool:
        return self._connected

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise ConnectionError("模拟登录网关未连接，请先调用 connect()")

    def _confirm(self, action: str, symbol: str, price: float, amount: float) -> bool:
        """弹窗确认（终端输入）"""
        msg = f"确认{action}: {symbol} 价格={price:.2f} 数量={amount:.0f}? [y/N] "
        try:
            response = input(msg)
            return response.lower() in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    def _rejected_order(self, symbol: str, side: OrderSide, price: float, amount: float, reason: str) -> Order:
        return Order(
            order_id=_gen_id(),
            symbol=symbol,
            market=Market.A_STOCK,
            side=side,
            order_type=OrderType.MARKET,
            price=price,
            amount=amount,
            status=OrderStatus.REJECTED,
            strategy_name="duant",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )


def _gen_id() -> str:
    import uuid
    return uuid.uuid4().hex[:16]
