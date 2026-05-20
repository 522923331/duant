"""数据校验与异常值处理"""

from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from loguru import logger

from duant.core.event import Market, TimeFrame
from duant.data.parquet_store import ParquetStore


class DataValidator:
    """行情数据校验器"""

    def __init__(self, store: ParquetStore):
        self.store = store
        self.issues: list[dict] = []

    def validate(self, symbol: str, market: Market, timeframe: TimeFrame,
                 start: datetime | None = None, end: datetime | None = None) -> list[dict]:
        """校验指定标的的数据"""
        self.issues = []
        df = self.store.load(symbol, market, timeframe, start, end)

        if df.empty:
            self.issues.append({
                "type": "missing",
                "symbol": symbol,
                "detail": "无数据",
            })
            return self.issues

        self._check_ohlc(df, symbol)
        self._check_missing_dates(df, symbol, market, timeframe)
        self._check_volume(df, symbol)
        self._check_limit(df, symbol, market)

        if self.issues:
            logger.warning(f"{symbol} 发现 {len(self.issues)} 个数据问题")
        else:
            logger.info(f"{symbol} 数据校验通过")

        return self.issues

    def _check_ohlc(self, df: pd.DataFrame, symbol: str) -> None:
        """检查 OHLC 关系：high >= open/close/low, low <= open/close/high"""
        invalid_high = df["high"] < df[["open", "close", "low"]].max(axis=1)
        invalid_low = df["low"] > df[["open", "close", "high"]].min(axis=1)
        negative_prices = (df[["open", "high", "low", "close"]] <= 0).any(axis=1)

        for idx in df[invalid_high].index[:10]:
            self.issues.append({
                "type": "ohlc_invalid",
                "symbol": symbol,
                "date": str(idx),
                "detail": f"最高价 < max(open,close,low): {df.loc[idx, 'high']:.2f}",
            })

        for idx in df[invalid_low].index[:10]:
            self.issues.append({
                "type": "ohlc_invalid",
                "symbol": symbol,
                "date": str(idx),
                "detail": f"最低价 > min(open,close,high): {df.loc[idx, 'low']:.2f}",
            })

        for idx in df[negative_prices].index[:10]:
            self.issues.append({
                "type": "ohlc_invalid",
                "symbol": symbol,
                "date": str(idx),
                "detail": "价格 <= 0",
            })

    def _check_missing_dates(self, df: pd.DataFrame, symbol: str,
                             market: Market, timeframe: TimeFrame) -> None:
        """检查缺失交易日"""
        if timeframe != TimeFrame.DAILY:
            return  # 分钟级别不检查缺失日期

        dates = pd.DatetimeIndex(df.index)
        if len(dates) < 2:
            return

        # 生成交易日历（简化：排除周末）
        start_date = dates.min()
        end_date = dates.max()
        all_dates = pd.bdate_range(start_date, end_date)

        # A股还需排除节假日（简化：只检查连续缺失超 3 天的）
        missing = all_dates.difference(dates)
        if len(missing) > 3:
            # 找到连续缺失段
            consecutive = self._find_consecutive_missing(missing)
            for segment in consecutive:
                if len(segment) >= 3:
                    self.issues.append({
                        "type": "missing_dates",
                        "symbol": symbol,
                        "date": f"{segment[0].strftime('%Y-%m-%d')} ~ {segment[-1].strftime('%Y-%m-%d')}",
                        "detail": f"连续缺失 {len(segment)} 个交易日",
                    })

    def _check_volume(self, df: pd.DataFrame, symbol: str) -> None:
        """检查异常成交量"""
        if "volume" not in df.columns:
            return

        zero_volume = df["volume"] == 0
        if zero_volume.any():
            count = zero_volume.sum()
            self.issues.append({
                "type": "zero_volume",
                "symbol": symbol,
                "detail": f"共 {count} 天成交量为零",
            })

    def _check_limit(self, df: pd.DataFrame, symbol: str, market: Market) -> None:
        """检查涨跌停异常值"""
        if market != Market.A_STOCK:
            return
        if "pre_close" not in df.columns or df["pre_close"].eq(0).all():
            return

        valid = df[df["pre_close"] > 0].copy()
        if valid.empty:
            return

        valid["pct_change"] = (valid["close"] - valid["pre_close"]) / valid["pre_close"]

        # A股涨跌停 ±10%（ST ±5%，创业板/科创板 ±20%，简化用 11%）
        limit_exceeded = valid["pct_change"].abs() > 0.11
        for idx in valid[limit_exceeded].index[:10]:
            pct = valid.loc[idx, "pct_change"]
            self.issues.append({
                "type": "limit_exceeded",
                "symbol": symbol,
                "date": str(idx),
                "detail": f"涨跌幅 {pct:+.2%} 超过正常范围（可能为ST/创业板/科创板）",
            })

    @staticmethod
    def _find_consecutive_missing(dates: pd.DatetimeIndex) -> list[list]:
        """找到连续缺失的日期段"""
        if len(dates) == 0:
            return []

        segments = []
        current = [dates[0]]

        for i in range(1, len(dates)):
            diff = (dates[i] - dates[i - 1]).days
            if diff <= 3:  # 允许周末间隔
                current.append(dates[i])
            else:
                segments.append(current)
                current = [dates[i]]

        segments.append(current)
        return segments

    def print_report(self) -> None:
        """打印校验报告"""
        if not self.issues:
            print("数据校验通过，无异常")
            return

        print(f"\n数据校验发现 {len(self.issues)} 个问题:")
        print("-" * 60)

        by_type: dict[str, list] = {}
        for issue in self.issues:
            by_type.setdefault(issue["type"], []).append(issue)

        for issue_type, issues in by_type.items():
            print(f"\n  [{issue_type}] {len(issues)} 个")
            for issue in issues[:5]:
                date_info = f" ({issue['date']})" if "date" in issue else ""
                print(f"    - {issue['symbol']}{date_info}: {issue['detail']}")
            if len(issues) > 5:
                print(f"    ... 还有 {len(issues) - 5} 个")
