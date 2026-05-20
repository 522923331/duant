"""加密货币 ccxt 网关"""

from datetime import datetime
from loguru import logger

from duant.core.config import CryptoTradeConfig
from duant.core.event import (
    Market,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)
from duant.trade.gateway import TradeGateway


class CryptoGateway(TradeGateway):
    """通过 ccxt 连接加密货币交易所"""

    def __init__(self, config: CryptoTradeConfig):
        self.config = config
        self.exchange = None
        self._connected = False

    def connect(self) -> None:
        try:
            import ccxt
        except ImportError:
            raise ImportError(
                "ccxt 未安装，请运行: pip install ccxt\n"
                "加密货币网关需要 ccxt 库"
            )

        exchange_class = getattr(ccxt, self.config.exchange, None)
        if not exchange_class:
            raise ValueError(f"不支持的交易所: {self.config.exchange}")

        self.exchange = exchange_class({
            "apiKey": self.config.api_key,
            "secret": self.config.secret,
            "enableRateLimit": True,
        })
        self.exchange.load_markets()
        self._connected = True
        logger.info(f"加密货币网关已连接: {self.config.exchange}")

    def disconnect(self) -> None:
        if self.exchange:
            self.exchange.close()
        self._connected = False
        logger.info("加密货币网关已断开")

    def buy(self, symbol: str, price: float, amount: float) -> Order:
        self._ensure_connected()
        try:
            if price > 0:
                result = self.exchange.create_limit_buy_order(symbol, amount, price)
            else:
                result = self.exchange.create_market_buy_order(symbol, amount)

            return self._ccxt_to_order(result, OrderSide.BUY)
        except Exception as e:
            logger.error(f"买入失败: {e}")
            raise

    def sell(self, symbol: str, price: float, amount: float) -> Order:
        self._ensure_connected()
        try:
            if price > 0:
                result = self.exchange.create_limit_sell_order(symbol, amount, price)
            else:
                result = self.exchange.create_market_sell_order(symbol, amount)

            return self._ccxt_to_order(result, OrderSide.SELL)
        except Exception as e:
            logger.error(f"卖出失败: {e}")
            raise

    def cancel(self, order_id: str) -> bool:
        self._ensure_connected()
        try:
            # 需要知道 symbol 来撤单，ccxt 要求 symbol 参数
            # 从 open_orders 中查找
            orders = self.exchange.fetch_open_orders()
            for o in orders:
                if str(o["id"]) == order_id:
                    self.exchange.cancel_order(order_id, o["symbol"])
                    return True
            return False
        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return False

    def get_position(self, symbol: str) -> Position | None:
        positions = self.get_positions()
        # 加密货币用 base currency 作为 symbol
        base = symbol.split("/")[0] if "/" in symbol else symbol
        for p in positions:
            if p.symbol == base or p.symbol == symbol:
                return p
        return None

    def get_positions(self) -> list[Position]:
        self._ensure_connected()
        try:
            balance = self.exchange.fetch_balance()
            result = []
            total = balance.get("total", {})
            free = balance.get("free", {})
            used = balance.get("used", {})

            for currency, total_amount in total.items():
                if total_amount and total_amount > 0:
                    result.append(Position(
                        symbol=currency,
                        market=Market.CRYPTO,
                        quantity=total_amount,
                        avg_price=0,
                        current_price=0,
                        unrealized_pnl=0,
                        market_value=0,
                        updated_at=datetime.now(),
                    ))
            return result
        except Exception as e:
            logger.error(f"查询持仓失败: {e}")
            return []

    def get_balance(self) -> float:
        self._ensure_connected()
        try:
            balance = self.exchange.fetch_balance()
            return float(balance.get("free", {}).get("USDT", 0))
        except Exception as e:
            logger.error(f"查询资金失败: {e}")
            return 0

    def get_orders(self) -> list[Order]:
        self._ensure_connected()
        try:
            orders = self.exchange.fetch_open_orders()
            return [self._ccxt_to_order(o, OrderSide.BUY if o["side"] == "buy" else OrderSide.SELL) for o in orders]
        except Exception as e:
            logger.error(f"查询委托失败: {e}")
            return []

    def is_connected(self) -> bool:
        return self._connected

    def _ensure_connected(self) -> None:
        if not self._connected:
            raise ConnectionError("加密货币网关未连接，请先调用 connect()")

    def _ccxt_to_order(self, raw: dict, side: OrderSide) -> Order:
        """将 ccxt 订单转换为 Order"""
        order_type = OrderType.LIMIT if raw.get("type") == "limit" else OrderType.MARKET
        status_map = {
            "open": OrderStatus.SUBMITTED,
            "closed": OrderStatus.FILLED,
            "canceled": OrderStatus.CANCELLED,
            "rejected": OrderStatus.REJECTED,
        }
        status = status_map.get(raw.get("status", ""), OrderStatus.SUBMITTED)

        return Order(
            order_id=str(raw.get("id", "")),
            symbol=raw.get("symbol", ""),
            market=Market.CRYPTO,
            side=side,
            order_type=order_type,
            price=float(raw.get("price", 0) or 0),
            amount=float(raw.get("amount", 0) or 0),
            status=status,
            strategy_name="duant",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
