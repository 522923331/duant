"""技术指标计算器"""

import numpy as np
import pandas as pd

from duant.strategy.base import DataBuffer


class IndicatorCalculator:
    """技术指标计算，基于 pandas/numpy"""

    def __init__(self, data_buffer: DataBuffer):
        self._buffer = data_buffer

    # --- 趋势指标 ---

    def ma(self, period: int, field: str = "close", symbol: str | None = None) -> pd.Series:
        s = self._get_series(symbol, field)
        return s.rolling(window=period).mean()

    def ema(self, period: int, field: str = "close", symbol: str | None = None) -> pd.Series:
        s = self._get_series(symbol, field)
        return s.ewm(span=period, adjust=False).mean()

    def macd(
        self, fast: int = 12, slow: int = 26, signal: int = 9,
        field: str = "close", symbol: str | None = None,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        s = self._get_series(symbol, field)
        ema_fast = s.ewm(span=fast, adjust=False).mean()
        ema_slow = s.ewm(span=slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=signal, adjust=False).mean()
        hist = (dif - dea) * 2
        return dif, dea, hist

    def bollinger(
        self, period: int = 20, std_dev: float = 2.0,
        field: str = "close", symbol: str | None = None,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        s = self._get_series(symbol, field)
        mid = s.rolling(window=period).mean()
        std = s.rolling(window=period).std()
        upper = mid + std_dev * std
        lower = mid - std_dev * std
        return upper, mid, lower

    # --- 动量指标 ---

    def rsi(self, period: int = 14, field: str = "close", symbol: str | None = None) -> pd.Series:
        s = self._get_series(symbol, field)
        delta = s.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))

    def kdj(
        self, n: int = 9, m1: int = 3, m2: int = 3, symbol: str | None = None,
    ) -> tuple[pd.Series, pd.Series, pd.Series]:
        high = self._get_series(symbol, "high")
        low = self._get_series(symbol, "low")
        close = self._get_series(symbol, "close")
        lowest_low = low.rolling(window=n).min()
        highest_high = high.rolling(window=n).max()
        rsv = (close - lowest_low) / (highest_high - lowest_low).replace(0, np.nan) * 100
        k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
        d = k.ewm(alpha=1 / m2, adjust=False).mean()
        j = 3 * k - 2 * d
        return k, d, j

    def cci(self, period: int = 14, symbol: str | None = None) -> pd.Series:
        high = self._get_series(symbol, "high")
        low = self._get_series(symbol, "low")
        close = self._get_series(symbol, "close")
        tp = (high + low + close) / 3
        ma_tp = tp.rolling(window=period).mean()
        md = tp.rolling(window=period).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        return (tp - ma_tp) / (0.015 * md.replace(0, np.nan))

    # --- 成交量指标 ---

    def obv(self, symbol: str | None = None) -> pd.Series:
        close = self._get_series(symbol, "close")
        volume = self._get_series(symbol, "volume")
        direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        return (volume * direction).cumsum()

    def volume_ratio(self, period: int = 5, symbol: str | None = None) -> pd.Series:
        volume = self._get_series(symbol, "volume")
        avg_vol = volume.rolling(window=period).mean()
        return volume / avg_vol.replace(0, np.nan)

    # --- 内部方法 ---

    def _get_series(self, symbol: str | None, field: str) -> pd.Series:
        sym = symbol or self._current_symbol()
        return self._buffer.get_series(sym, field)

    def _current_symbol(self) -> str:
        # 从 buffer 中获取第一个有数据的 symbol
        for sym in self._buffer._data:
            if self._buffer._data[sym]:
                return sym
        return ""
