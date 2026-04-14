from __future__ import annotations

import os
import pickle
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Set

from ..shared.logging import get_logger

LOGGER = get_logger(__name__)


class TradingCalendar:
    def __init__(self, market: str = "cn"):
        self.market = market.lower()
        self.cache_dir = Path(".cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / f"{market}_trading_days.pkl"
        self.trading_days: Set[str] = set()
        self._load_cache()

    def _load_cache(self) -> None:
        if self.cache_file.exists():
            try:
                with self.cache_file.open("rb") as f:
                    self.trading_days = pickle.load(f)
                LOGGER.info(f"Loaded trading calendar from cache: {len(self.trading_days)} days")
            except Exception as e:
                LOGGER.warning(f"Failed to load trading calendar cache: {e}")
                self.trading_days = set()

    def _save_cache(self) -> None:
        try:
            with self.cache_file.open("wb") as f:
                pickle.dump(self.trading_days, f)
            LOGGER.info(f"Saved trading calendar to cache: {len(self.trading_days)} days")
        except Exception as e:
            LOGGER.warning(f"Failed to save trading calendar cache: {e}")

    def is_trading_day(self, dt: Optional[date | datetime] = None) -> bool:
        if dt is None:
            dt = date.today()
        if isinstance(dt, datetime):
            dt = dt.date()
        date_str = dt.strftime("%Y-%m-%d")
        
        # 检查是否在缓存中
        if date_str in self.trading_days:
            return True
        
        # 检查是否为周末
        if dt.weekday() >= 5:
            return False
        
        # 对于中国市场，添加一些常见的节假日
        if self.market == "cn":
            # 这里可以添加更多节假日
            holidays = {
                "2024-01-01",  # 元旦
                "2024-02-10",  # 春节
                "2024-02-11",
                "2024-02-12",
                "2024-02-13",
                "2024-02-14",
                "2024-04-04",  # 清明节
                "2024-04-05",
                "2024-05-01",  # 劳动节
                "2024-05-02",
                "2024-05-03",
                "2024-06-10",  # 端午节
                "2024-09-17",  # 中秋节
                "2024-09-18",
                "2024-10-01",  # 国庆节
                "2024-10-02",
                "2024-10-03",
                "2024-10-04",
                "2024-10-05",
                "2024-10-06",
                "2024-10-07",
            }
            if date_str in holidays:
                return False
        
        # 默认非周末为交易日
        return True

    def get_trading_days(self, start_date: date, end_date: date) -> List[date]:
        trading_days = []
        current = start_date
        while current <= end_date:
            if self.is_trading_day(current):
                trading_days.append(current)
                self.trading_days.add(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)
        self._save_cache()
        return trading_days

    def get_next_trading_day(self, dt: Optional[date | datetime] = None) -> date:
        if dt is None:
            dt = date.today()
        if isinstance(dt, datetime):
            dt = dt.date()
        next_day = dt + timedelta(days=1)
        while not self.is_trading_day(next_day):
            next_day += timedelta(days=1)
        return next_day

    def get_previous_trading_day(self, dt: Optional[date | datetime] = None) -> date:
        if dt is None:
            dt = date.today()
        if isinstance(dt, datetime):
            dt = dt.date()
        prev_day = dt - timedelta(days=1)
        while not self.is_trading_day(prev_day):
            prev_day -= timedelta(days=1)
        return prev_day