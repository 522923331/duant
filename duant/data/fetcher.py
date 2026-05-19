"""行情数据获取，tushare 优先，akshare 降级，ccxt 加密货币"""

import time
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from loguru import logger

from duant.core.event import Market, TimeFrame

_A_STOCK_COLUMNS = ["datetime", "open", "high", "low", "close", "pre_close", "volume", "amount", "turnover", "circ_market_cap"]
_CRYPTO_COLUMNS = ["datetime", "open", "high", "low", "close", "volume", "amount", "trades"]

_TIMEFRAME_MAP_TUSHARE = {
    TimeFrame.DAILY: "daily",
    TimeFrame.MIN_1: "1min",
    TimeFrame.MIN_5: "5min",
    TimeFrame.MIN_15: "15min",
    TimeFrame.HOUR_1: "60min",
}


def _retry(fn, max_retries: int = 3, base_delay: float = 1.0):
    """指数退避重试"""
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2 ** attempt)
            logger.warning(f"第{attempt + 1}次重试，{delay}秒后重试，错误: {e}")
            time.sleep(delay)


class TushareFetcher:
    """tushare A股数据获取"""

    def __init__(self, token: str):
        import tushare as ts

        ts.set_token(token)
        self.pro = ts.pro_api()
        logger.info("tushare 初始化完成")

    def fetch_bars(
        self, symbol: str, timeframe: TimeFrame, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """获取A股K线数据"""
        ts_code = symbol  # tushare 格式：000001.SZ
        start_str = start.strftime("%Y%m%d")
        end_str = end.strftime("%Y%m%d")

        if timeframe == TimeFrame.DAILY:
            df = _retry(
                lambda: self.pro.daily(
                    ts_code=ts_code, start_date=start_str, end_date=end_str
                )
            )
            # 获取换手率和流通市值
            try:
                basic = _retry(
                    lambda: self.pro.daily_basic(
                        ts_code=ts_code, start_date=start_str, end_date=end_str,
                        fields="ts_code,trade_date,turnover_rate,circ_mv",
                    )
                )
                if not basic.empty:
                    df = df.merge(basic, on=["ts_code", "trade_date"], how="left")
            except Exception as e:
                logger.warning(f"获取 daily_basic 失败: {e}，换手率和流通市值将缺失")
                df["turnover_rate"] = np.nan
                df["circ_mv"] = np.nan
        else:
            freq = _TIMEFRAME_MAP_TUSHARE.get(timeframe)
            if not freq:
                raise ValueError(f"tushare 不支持周期: {timeframe}")
            df = _retry(
                lambda: self.pro.stk_mins(
                    ts_code=ts_code, start_date=start_str + " 09:00:00",
                    end_date=end_str + " 15:00:00", freq=freq,
                )
            )
            df["turnover_rate"] = 0.0
            df["circ_mv"] = 0.0
            df["pre_close"] = 0.0

        if df.empty:
            return pd.DataFrame(columns=_A_STOCK_COLUMNS).set_index("datetime")

        return self._normalize(df, timeframe)

    def _normalize(self, df: pd.DataFrame, timeframe: TimeFrame) -> pd.DataFrame:
        """标准化 tushare 数据为统一格式"""
        if "trade_date" in df.columns:
            df["datetime"] = pd.to_datetime(df["trade_date"])
        elif "trade_time" in df.columns:
            df["datetime"] = pd.to_datetime(df["trade_time"])
        else:
            df["datetime"] = pd.NaT

        result = pd.DataFrame()
        result["datetime"] = df["datetime"]
        result["open"] = df["open"].astype(float)
        result["high"] = df["high"].astype(float)
        result["low"] = df["low"].astype(float)
        result["close"] = df["close"].astype(float)
        result["pre_close"] = df["pre_close"].astype(float) if "pre_close" in df.columns else 0.0
        result["volume"] = df["vol"].astype(float) if "vol" in df.columns else df["volume"].astype(float) if "volume" in df.columns else 0.0
        result["amount"] = df["amount"].astype(float) * 1000  # tushare amount 单位是千元，转成元
        result["turnover"] = df["turnover_rate"].astype(float) if "turnover_rate" in df.columns else 0.0
        result["circ_market_cap"] = df["circ_mv"].astype(float) * 10000 if "circ_mv" in df.columns else 0.0  # tushare circ_mv 单位是万元，转成元

        result = result.sort_values("datetime").drop_duplicates(subset=["datetime"])
        result = result.set_index("datetime")
        return result


class AkshareFetcher:
    """akshare A股数据获取（降级备选）"""

    def fetch_bars(
        self, symbol: str, timeframe: TimeFrame, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """获取A股K线数据"""
        import akshare as ak

        # 转换代码格式：000001.SZ -> 000001
        code = symbol.split(".")[0]

        if timeframe == TimeFrame.DAILY:
            df = _retry(
                lambda: ak.stock_zh_a_hist(
                    symbol=code, period="daily",
                    start_date=start.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",
                )
            )
        else:
            period_map = {
                TimeFrame.MIN_1: "1", TimeFrame.MIN_5: "5",
                TimeFrame.MIN_15: "15", TimeFrame.MIN_30: "30", TimeFrame.HOUR_1: "60",
            }
            period = period_map.get(timeframe)
            if not period:
                raise ValueError(f"akshare 不支持周期: {timeframe}")
            df = _retry(
                lambda: ak.stock_zh_a_hist_min_em(symbol=code, period=period, adjust="qfq")
            )
            df = df[
                (pd.to_datetime(df["时间"]) >= start)
                & (pd.to_datetime(df["时间"]) <= end)
            ]

        if df.empty:
            return pd.DataFrame(columns=_A_STOCK_COLUMNS).set_index("datetime")

        return self._normalize(df)

    def _normalize(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化 akshare 数据"""
        result = pd.DataFrame()
        result["datetime"] = pd.to_datetime(df["日期"] if "日期" in df.columns else df["时间"])
        result["open"] = df["开盘"].astype(float)
        result["high"] = df["最高"].astype(float)
        result["low"] = df["最低"].astype(float)
        result["close"] = df["收盘"].astype(float)
        result["pre_close"] = df["昨收"].astype(float) if "昨收" in df.columns else 0.0
        result["volume"] = df["成交量"].astype(float)
        result["amount"] = df["成交额"].astype(float)
        result["turnover"] = df["换手率"].astype(float) if "换手率" in df.columns else 0.0
        result["circ_market_cap"] = 0.0  # akshare 日K不直接提供流通市值

        result = result.sort_values("datetime").drop_duplicates(subset=["datetime"])
        result = result.set_index("datetime")
        return result


class CryptoFetcher:
    """ccxt 加密货币数据获取"""

    def __init__(self, exchange_id: str = "binance", config: dict | None = None):
        import ccxt

        exchange_class = getattr(ccxt, exchange_id, None)
        if not exchange_class:
            raise ValueError(f"不支持的交易所: {exchange_id}")
        self.exchange = exchange_class(config or {})
        logger.info(f"ccxt {exchange_id} 初始化完成")

    def fetch_bars(
        self, symbol: str, timeframe: TimeFrame, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """获取加密货币K线数据"""
        since = int(start.timestamp() * 1000)
        limit = 1000

        all_ohlcvs = []
        current_since = since
        end_ms = int(end.timestamp() * 1000)

        while current_since < end_ms:
            ohlcvs = _retry(
                lambda cs=current_since: self.exchange.fetch_ohlcv(
                    symbol, timeframe.value, since=cs, limit=limit
                )
            )
            if not ohlcvs:
                break
            all_ohlcvs.extend(ohlcvs)
            current_since = ohlcvs[-1][0] + 1
            if len(ohlcvs) < limit:
                break

        if not all_ohlcvs:
            return pd.DataFrame(columns=_CRYPTO_COLUMNS).set_index("datetime")

        df = pd.DataFrame(all_ohlcvs, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["amount"] = 0.0  # ccxt 标准 OHLCV 没有 quote_volume，后续补充
        df["trades"] = 0.0

        # 尝试获取 quote_volume
        try:
            df_v = pd.DataFrame(all_ohlcvs, columns=["timestamp", "open", "high", "low", "close", "volume"])
            # 部分交易所返回 7 列（含 quote_volume）
            if len(all_ohlcvs[0]) > 6:
                df["amount"] = [row[6] if len(row) > 6 else 0.0 for row in all_ohlcvs]
        except (IndexError, TypeError):
            pass

        result = df[["datetime", "open", "high", "low", "close", "volume", "amount", "trades"]].copy()
        result = result.sort_values("datetime").drop_duplicates(subset=["datetime"])
        result = result.set_index("datetime")
        return result


class DataFetcher:
    """统一行情获取入口，tushare 优先，akshare 降级"""

    def __init__(self, tushare_token: str = "", crypto_exchange: str = "binance"):
        self.tushare = TushareFetcher(tushare_token) if tushare_token else None
        self.akshare = AkshareFetcher()
        self._crypto_fetcher: CryptoFetcher | None = None
        self._crypto_exchange = crypto_exchange

    @property
    def crypto(self) -> CryptoFetcher:
        if self._crypto_fetcher is None:
            self._crypto_fetcher = CryptoFetcher(self._crypto_exchange)
        return self._crypto_fetcher

    def fetch_bars(
        self,
        symbol: str,
        market: Market,
        timeframe: TimeFrame,
        start: datetime,
        end: datetime,
    ) -> pd.DataFrame:
        """获取K线数据，A股 tushare 优先，失败降级 akshare"""
        if market == Market.A_STOCK:
            return self._fetch_a_stock(symbol, timeframe, start, end)
        elif market == Market.CRYPTO:
            return self.crypto.fetch_bars(symbol, timeframe, start, end)
        else:
            raise ValueError(f"不支持的市场: {market}")

    def _fetch_a_stock(
        self, symbol: str, timeframe: TimeFrame, start: datetime, end: datetime
    ) -> pd.DataFrame:
        """A股数据获取，tushare 优先"""
        if self.tushare:
            try:
                df = self.tushare.fetch_bars(symbol, timeframe, start, end)
                if not df.empty:
                    return df
                logger.warning(f"tushare 返回空数据: {symbol} {timeframe}")
            except Exception as e:
                logger.warning(f"tushare 获取失败，降级 akshare: {e}")

        logger.info(f"使用 akshare 获取: {symbol} {timeframe}")
        return self.akshare.fetch_bars(symbol, timeframe, start, end)
