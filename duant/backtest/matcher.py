"""订单撮合器"""

from datetime import datetime

import numpy as np

from duant.core.config import BacktestConfig, CommissionConfig, CryptoCommissionConfig, SlippageConfig
from duant.core.event import Bar, Market, Order, OrderSide, OrderType, Trade


class OrderMatcher:
    """回测中的订单撮合"""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.slippage = config.slippage

    def match(self, order: Order, bar: Bar) -> Trade | None:
        """
        撮合逻辑:
        1. 市价单：按 bar 的 open + 滑点成交
        2. 限价单：检查价格是否触及
        3. A股特殊：涨跌停检查、整手检查
        4. 计算手续费
        """
        if order.market == Market.A_STOCK:
            return self._match_a_stock(order, bar)
        elif order.market == Market.CRYPTO:
            return self._match_crypto(order, bar)
        return None

    def _match_a_stock(self, order: Order, bar: Bar) -> Trade | None:
        """A股撮合"""
        # 涨跌停检查
        if bar.pre_close > 0:
            limit_up = round(bar.pre_close * 1.1, 2)
            limit_down = round(bar.pre_close * 0.9, 2)

            # 涨停无法买入
            if order.side == OrderSide.BUY and bar.close >= limit_up:
                return None
            # 跌停无法卖出
            if order.side == OrderSide.SELL and bar.close <= limit_down:
                return None

        # 确定成交价格
        if order.order_type == OrderType.MARKET:
            trade_price = bar.open
        elif order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY and bar.low <= order.price:
                trade_price = order.price
            elif order.side == OrderSide.SELL and bar.high >= order.price:
                trade_price = order.price
            else:
                return None  # 限价未触及
        else:
            return None

        # 滑点
        trade_price = self._apply_slippage(trade_price, order.side)

        # 整手检查（100 股整数倍）
        trade_amount = int(order.amount // 100) * 100
        if trade_amount <= 0:
            return None

        # 手续费
        commission = self._calc_a_stock_commission(trade_price, trade_amount, order.side)

        # 成交额检查
        trade_value = trade_price * trade_amount
        if trade_value + commission > 0 and order.side == OrderSide.BUY:
            pass  # 资金检查在 Portfolio 层做

        return Trade(
            trade_id=order.order_id + "_t",
            order_id=order.order_id,
            symbol=order.symbol,
            market=order.market,
            side=order.side,
            price=trade_price,
            amount=trade_amount,
            commission=commission,
            slippage=abs(trade_price - bar.open) * trade_amount,
            traded_at=bar.datetime,
        )

    def _match_crypto(self, order: Order, bar: Bar) -> Trade | None:
        """加密货币撮合"""
        if order.order_type == OrderType.MARKET:
            trade_price = bar.open
        elif order.order_type == OrderType.LIMIT:
            if order.side == OrderSide.BUY and bar.low <= order.price:
                trade_price = order.price
            elif order.side == OrderSide.SELL and bar.high >= order.price:
                trade_price = order.price
            else:
                return None
        else:
            return None

        trade_price = self._apply_slippage(trade_price, order.side)
        trade_amount = order.amount

        commission = self._calc_crypto_commission(trade_price, trade_amount)

        return Trade(
            trade_id=order.order_id + "_t",
            order_id=order.order_id,
            symbol=order.symbol,
            market=order.market,
            side=order.side,
            price=trade_price,
            amount=trade_amount,
            commission=commission,
            slippage=abs(trade_price - bar.open) * trade_amount,
            traded_at=bar.datetime,
        )

    def _apply_slippage(self, price: float, side: OrderSide) -> float:
        """应用滑点"""
        if self.slippage.model == "fixed":
            return price + self.slippage.value if side == OrderSide.BUY else price - self.slippage.value
        elif self.slippage.model == "percent":
            return price * (1 + self.slippage.value) if side == OrderSide.BUY else price * (1 - self.slippage.value)
        return price

    def _calc_a_stock_commission(self, price: float, amount: float, side: OrderSide) -> float:
        """A股手续费：佣金万2.5（最低5元）+ 印花税千1（卖出）+ 过户费"""
        cfg = self.config.a_stock_commission
        trade_value = price * amount

        # 佣金
        commission = max(trade_value * cfg.rate, cfg.min)

        # 印花税（仅卖出）
        stamp_tax = trade_value * cfg.stamp_tax if side == OrderSide.SELL else 0.0

        # 过户费
        transfer_fee = trade_value * cfg.transfer_fee

        return round(commission + stamp_tax + transfer_fee, 2)

    def _calc_crypto_commission(self, price: float, amount: float) -> float:
        """加密货币手续费"""
        cfg = self.config.crypto_commission
        return round(price * amount * cfg.rate, 2)
