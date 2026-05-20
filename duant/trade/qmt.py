"""A股 QMT 网关（miniQMT，通过 xtquant）"""

from datetime import datetime
from loguru import logger

from duant.core.config import QmtConfig
from duant.core.event import (
    Market,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)
from duant.trade.gateway import TradeGateway


class QmtGateway(TradeGateway):
    """通过 xtquant 连接 miniQMT，程序化交易"""

    def __init__(self, config: QmtConfig):
        self.config = config
        self._xt = None
        self._connected = False

    def connect(self) -> None:
        try:
            from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
            from xtquant.xttype import StockAccount
        except ImportError:
            raise ImportError(
                "xtquant 未安装，请运行: pip install xtquant\n"
                "QMT 网关需要 miniQMT 客户端运行并安装 xtquant 库"
            )

        self._xt = XtQuantTrader(self.config.path)
        account = StockAccount(self.config.account_id)
        self._xt.start()
        result = self._xt.connect()
        if result == 0:
            self._connected = True
            logger.info(f"QMT 连接成功: {self.config.account_id}")
        else:
            self._connected = False
            raise ConnectionError(f"QMT 连接失败: {result}")

    def disconnect(self) -> None:
        if self._xt:
            self._xt.stop()
            self._connected = False
            logger.info("QMT 已断开连接")

    def buy(self, symbol: str, price: float, amount: float) -> Order:
        self._ensure_connected()
        from xtquant.xttype import StockAccount
        account = StockAccount(self.config.account_id)
        order_id = self._xt.order_stock(
            account, symbol, 0,  # 0=买入
            int(amount), int(price * 100) if price > 0 else 0,  # 限价单
            2 if price > 0 else 4,  # 2=限价 4=市价
            strategy_name="duant",
        )
        return Order(
            order_id=str(order_id),
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
        from xtquant.xttype import StockAccount
        account = StockAccount(self.config.account_id)
        order_id = self._xt.order_stock(
            account, symbol, 1,  # 1=卖出
            int(amount), int(price * 100) if price > 0 else 0,
            2 if price > 0 else 4,
            strategy_name="duant",
        )
        return Order(
            order_id=str(order_id),
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
        from xtquant.xttype import StockAccount
        account = StockAccount(self.config.account_id)
        result = self._xt.cancel_order_stock(account, int(order_id))
        return result == 0

    def get_position(self, symbol: str) -> Position | None:
        self._ensure_connected()
        from xtquant.xttype import StockAccount
        account = StockAccount(self.config.account_id)
        positions = self._xt.query_stock_positions(account)
        for p in positions:
            if p.stock_code == symbol:
                return Position(
                    symbol=symbol,
                    market=Market.A_STOCK,
                    quantity=p.volume,
                    avg_price=float(p.avg_price) / 100 if hasattr(p, "avg_price") else 0,
                    current_price=0,
                    unrealized_pnl=0,
                    market_value=0,
                    updated_at=datetime.now(),
                )
        return None

    def get_positions(self) -> list[Position]:
        self._ensure_connected()
        from xtquant.xttype import StockAccount
        account = StockAccount(self.config.account_id)
        positions = self._xt.query_stock_positions(account)
        result = []
        for p in positions:
            result.append(Position(
                symbol=p.stock_code,
                market=Market.A_STOCK,
                quantity=p.volume,
                avg_price=float(p.avg_price) / 100 if hasattr(p, "avg_price") else 0,
                current_price=0,
                unrealized_pnl=0,
                market_value=0,
                updated_at=datetime.now(),
            ))
        return result

    def get_balance(self) -> float:
        self._ensure_connected()
        from xtquant.xttype import StockAccount
        account = StockAccount(self.config.account_id)
        asset = self._xt.query_stock_asset(account)
        return float(asset.cash) if asset else 0

    def get_orders(self) -> list[Order]:
        self._ensure_connected()
        from xtquant.xttype import StockAccount
        account = StockAccount(self.config.account_id)
        orders = self._xt.query_stock_orders(account)
        result = []
        for o in orders:
            result.append(Order(
                order_id=str(o.order_id),
                symbol=o.stock_code,
                market=Market.A_STOCK,
                side=OrderSide.BUY if o.order_side == 0 else OrderSide.SELL,
                order_type=OrderType.MARKET,
                price=float(o.price) / 100 if hasattr(o, "price") else 0,
                amount=o.order_volume,
                status=OrderStatus.SUBMITTED,
                strategy_name="duant",
                created_at=datetime.now(),
                updated_at=datetime.now(),
            ))
        return result

    def is_connected(self) -> bool:
        return self._connected

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise ConnectionError("QMT 未连接，请先调用 connect()")
