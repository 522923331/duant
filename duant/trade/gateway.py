"""交易网关抽象层与工厂"""

from abc import ABC, abstractmethod

from duant.core.config import TradeConfig
from duant.core.event import Order, Position


class TradeGateway(ABC):
    """交易网关抽象层，所有网关实现此接口"""

    @abstractmethod
    def connect(self) -> None:
        """连接交易通道"""

    @abstractmethod
    def disconnect(self) -> None:
        """断开连接"""

    @abstractmethod
    def buy(self, symbol: str, price: float, amount: float) -> Order:
        """买入"""

    @abstractmethod
    def sell(self, symbol: str, price: float, amount: float) -> Order:
        """卖出"""

    @abstractmethod
    def cancel(self, order_id: str) -> bool:
        """撤单"""

    @abstractmethod
    def get_position(self, symbol: str) -> Position | None:
        """查询持仓"""

    @abstractmethod
    def get_positions(self) -> list[Position]:
        """查询所有持仓"""

    @abstractmethod
    def get_balance(self) -> float:
        """查询可用资金"""

    @abstractmethod
    def get_orders(self) -> list[Order]:
        """查询今日委托"""

    @abstractmethod
    def is_connected(self) -> bool:
        """是否已连接"""


class GatewayFactory:
    """根据配置创建对应的交易网关"""

    @staticmethod
    def create(config: TradeConfig) -> TradeGateway:
        match config.gateway:
            case "qmt":
                from duant.trade.qmt import QmtGateway
                return QmtGateway(config.qmt)
            case "simulate":
                from duant.trade.simulate import SimulateGateway
                return SimulateGateway(config.simulate)
            case "crypto":
                from duant.trade.crypto import CryptoGateway
                return CryptoGateway(config.crypto)
            case _:
                raise ValueError(f"未知网关类型: {config.gateway}")
