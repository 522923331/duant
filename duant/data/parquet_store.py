"""Parquet 行情数据存储"""

from datetime import datetime
from pathlib import Path

import pandas as pd

from duant.core.event import Market, TimeFrame


class ParquetStore:
    """Parquet 文件读写，按市场/周期/标的组织"""

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path)

    def _file_path(self, symbol: str, market: Market, timeframe: TimeFrame) -> Path:
        return self.base_path / market.value / timeframe.value / f"{symbol}.parquet"

    def save(self, df: pd.DataFrame, symbol: str, market: Market, timeframe: TimeFrame) -> None:
        """写入 Parquet，增量合并去重"""
        path = self._file_path(symbol, market, timeframe)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            existing = pd.read_parquet(path, engine="pyarrow")
            df = self._merge(existing, df)

        df.to_parquet(path, engine="pyarrow", compression="snappy", index=True)

    def load(
        self,
        symbol: str,
        market: Market,
        timeframe: TimeFrame,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        """读取 Parquet，支持时间范围过滤"""
        path = self._file_path(symbol, market, timeframe)
        if not path.exists():
            return pd.DataFrame()

        df = pd.read_parquet(path, engine="pyarrow")

        if start or end:
            if not isinstance(df.index, pd.DatetimeIndex):
                df.index = pd.to_datetime(df.index)
            if start:
                df = df.loc[start:]
            if end:
                df = df.loc[:end]

        return df

    def list_symbols(self, market: Market, timeframe: TimeFrame) -> list[str]:
        """列出已有数据的标的"""
        directory = self.base_path / market.value / timeframe.value
        if not directory.exists():
            return []
        return [p.stem for p in directory.glob("*.parquet")]

    def get_last_date(self, symbol: str, market: Market, timeframe: TimeFrame) -> datetime | None:
        """获取最新数据日期，用于增量更新"""
        df = self.load(symbol, market, timeframe)
        if df.empty:
            return None
        if isinstance(df.index, pd.DatetimeIndex):
            return df.index[-1].to_pydatetime()
        return pd.to_datetime(df.index[-1]).to_pydatetime()

    @staticmethod
    def _merge(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        """合并新旧数据，去重（按索引），保留新数据"""
        combined = pd.concat([existing, new])
        combined = combined[~combined.index.duplicated(keep="last")]
        combined = combined.sort_index()
        return combined
