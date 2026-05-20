"""YAML 声明式策略解析器"""

import re
from pathlib import Path

import yaml
from loguru import logger

from duant.core.event import Bar, Market, OrderSide, OrderType, TimeFrame
from duant.strategy.base import StrategyBase


class YamlStrategyLoader:
    """解析 YAML 声明式策略，动态生成 StrategyBase 子类"""

    def load(self, yaml_path: Path) -> StrategyBase:
        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)

        name = cfg["name"]
        market = Market(cfg["market"])
        timeframe = TimeFrame(cfg["timeframe"])
        entry = cfg.get("entry", {})
        exit_ = cfg.get("exit", {})
        risk = cfg.get("risk", {})
        params = cfg.get("params", {})

        entry_fn = self._parse_condition(entry.get("condition", "")) if entry.get("condition") else None
        exit_fn = self._parse_condition(exit_.get("condition", "")) if exit_.get("condition") else None

        entry_action = OrderSide.BUY if entry.get("action") == "buy" else OrderSide.SELL
        exit_action = OrderSide.SELL if exit_.get("action") == "sell" else OrderSide.BUY
        entry_amount = entry.get("amount", 0)
        exit_amount = exit_.get("amount", 0)

        class YamlStrategy(StrategyBase):
            _entry_fn = staticmethod(entry_fn) if entry_fn else None
            _exit_fn = staticmethod(exit_fn) if exit_fn else None
            _entry_action = entry_action
            _exit_action = exit_action
            _entry_amount = entry_amount
            _exit_amount = exit_amount
            _yaml_params = params

            def __init_subclass__(cls, **kwargs):
                super().__init_subclass__(**kwargs)

            def on_bar(self, bar: Bar) -> None:
                if self._entry_fn and self._entry_fn(self):
                    if self._entry_action == OrderSide.BUY:
                        self.buy(bar.symbol, self._entry_amount)
                    else:
                        self.sell(bar.symbol, self._entry_amount)

                if self._exit_fn and self._exit_fn(self):
                    if self._exit_action == OrderSide.BUY:
                        self.buy(bar.symbol, self._exit_amount)
                    else:
                        self.sell(bar.symbol, self._exit_amount)

        YamlStrategy.__name__ = name
        YamlStrategy.__qualname__ = name
        return YamlStrategy()

    def _parse_condition(self, expr: str):
        """将条件表达式解析为可执行函数

        支持的语法:
        - ma(close, 5) -> indicators.ma(5, "close")
        - ema(close, 20) -> indicators.ema(20, "close")
        - rsi(14) -> indicators.rsi(14)
        - cross_up(a, b) -> strategy.cross_up(a, b)
        - above(a, b) -> a.iloc[-1] > b.iloc[-1]
        - below(a, b) -> a.iloc[-1] < b.iloc[-1]
        - and(a, b) / or(a, b)
        """

        def condition_fn(strategy: StrategyBase) -> bool:
            return self._eval_expr(expr, strategy)

        return condition_fn

    def _eval_expr(self, expr: str, strategy: StrategyBase) -> bool:
        """递归求值条件表达式"""
        expr = expr.strip()

        # and / or
        and_match = self._match_func("and", expr)
        or_match = self._match_func("or", expr)

        if and_match:
            args = and_match
            return self._eval_expr(args[0], strategy) and self._eval_expr(args[1], strategy)
        if or_match:
            args = or_match
            return self._eval_expr(args[0], strategy) or self._eval_expr(args[1], strategy)

        # cross_up / cross_down
        cross_up_match = self._match_func("cross_up", expr)
        if cross_up_match:
            a = self._eval_series(cross_up_match[0], strategy)
            b = self._eval_series(cross_up_match[1], strategy)
            return strategy.cross_up(a, b)

        cross_down_match = self._match_func("cross_down", expr)
        if cross_down_match:
            a = self._eval_series(cross_down_match[0], strategy)
            b = self._eval_series(cross_down_match[1], strategy)
            return strategy.cross_down(a, b)

        # above / below
        above_match = self._match_func("above", expr)
        if above_match:
            a = self._eval_series(above_match[0], strategy)
            b = self._eval_series(above_match[1], strategy)
            return a.iloc[-1] > b.iloc[-1] if len(a) > 0 and len(b) > 0 else False

        below_match = self._match_func("below", expr)
        if below_match:
            a = self._eval_series(below_match[0], strategy)
            b = self._eval_series(below_match[1], strategy)
            return a.iloc[-1] < b.iloc[-1] if len(a) > 0 and len(b) > 0 else False

        # between
        between_match = self._match_func("between", expr)
        if between_match:
            a = self._eval_series(between_match[0], strategy)
            low = float(between_match[1])
            high = float(between_match[2])
            return low <= a.iloc[-1] <= high if len(a) > 0 else False

        raise ValueError(f"无法解析条件表达式: {expr}")

    def _eval_series(self, expr: str, strategy: StrategyBase):
        """将表达式解析为 pandas Series"""
        expr = expr.strip()

        # ma(close, 5)
        ma_match = self._match_func("ma", expr)
        if ma_match:
            field = ma_match[0].strip('"').strip("'")
            period = int(ma_match[1])
            return strategy.context.indicators.ma(period, field)

        # ema(close, 20)
        ema_match = self._match_func("ema", expr)
        if ema_match:
            field = ema_match[0].strip('"').strip("'")
            period = int(ema_match[1])
            return strategy.context.indicators.ema(period, field)

        # rsi(14)
        rsi_match = self._match_func("rsi", expr)
        if rsi_match:
            period = int(rsi_match[0])
            return strategy.context.indicators.rsi(period)

        # macd(...)
        macd_match = self._match_func("macd", expr)
        if macd_match:
            fast = int(macd_match[0]) if len(macd_match) > 0 else 12
            slow = int(macd_match[1]) if len(macd_match) > 1 else 26
            signal = int(macd_match[2]) if len(macd_match) > 2 else 9
            dif, dea, hist = strategy.context.indicators.macd(fast, slow, signal)
            return dif  # 默认返回 DIF

        # bollinger(...)
        boll_match = self._match_func("bollinger", expr)
        if boll_match:
            period = int(boll_match[0]) if len(boll_match) > 0 else 20
            std = float(boll_match[1]) if len(boll_match) > 1 else 2.0
            upper, mid, lower = strategy.context.indicators.bollinger(period, std)
            return mid

        # 简单字段名: close, open, high, low, volume
        if expr in ("close", "open", "high", "low", "volume", "amount", "turnover"):
            return strategy.context.indicators._get_series(None, expr)

        raise ValueError(f"无法解析序列表达式: {expr}")

    @staticmethod
    def _match_func(func_name: str, expr: str) -> list[str] | None:
        """匹配函数调用，返回参数列表"""
        pattern = rf"^{func_name}\s*\((.+)\)$"
        m = re.match(pattern, expr)
        if not m:
            return None
        args_str = m.group(1)
        return _split_args(args_str)


def _split_args(s: str) -> list[str]:
    """按逗号分割函数参数，考虑嵌套括号"""
    args = []
    depth = 0
    current = []
    for ch in s:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        args.append("".join(current).strip())
    return args
