from __future__ import annotations

import copy
from typing import Any, Dict, Iterator, List

from ..config import FeedsSettings
from .feeds import FundamentalFeed, MarketDataFeed, SentimentFeed, Tick
from .news_feed import NewsFeed


class DataPipeline:
    def __init__(self, cfg: FeedsSettings, *, poll_interval_seconds: float = 0.0):
        self.cfg = cfg
        market_payload = copy.deepcopy(cfg.market.payload())
        if poll_interval_seconds > 0 and "poll_interval_seconds" not in market_payload:
            market_payload["poll_interval_seconds"] = poll_interval_seconds
        self.market = MarketDataFeed(market_payload)
        self._market_stream = self.market.stream()
        self.fundamental = (
            FundamentalFeed(cfg.fundamental.payload()) if cfg.fundamental else None
        )
        self.sentiment = (
            SentimentFeed(cfg.sentiment.payload()) if cfg.sentiment else None
        )
        self.news = (
            NewsFeed(cfg.news.payload()) if hasattr(cfg, 'news') and cfg.news else None
        )

    def stream(self, max_iterations: int = 50) -> Iterator[Dict[str, List[Any]]]:
        for _ in range(max_iterations):
            try:
                # 收集所有股票的tick数据
                market_ticks = []
                # 尝试获取与股票数量相同的tick数据
                for _ in range(len(self.market.impl.symbols)):
                    try:
                        tick = next(self._market_stream)
                        market_ticks.append(tick)
                    except StopIteration:
                        break
                
                if not market_ticks:
                    # 没有tick数据，跳过本轮
                    continue
                
                bundle: Dict[str, List[Any]] = {"market": market_ticks}
                if self.fundamental:
                    bundle["fundamental"] = list(self.fundamental.stream())
                if self.sentiment:
                    bundle["sentiment"] = list(self.sentiment.stream())
                if self.news:
                    try:
                        # 尝试获取最新的新闻事件
                        import itertools
                        news_events = list(itertools.islice(self.news.stream(), 3))
                        if news_events:
                            bundle["news"] = news_events
                    except Exception:
                        pass
                yield bundle
            except StopIteration:
                # 市场数据流结束，退出循环
                break
            except Exception as e:
                # 其他异常，记录并继续
                import logging
                logging.warning(f"Error in data pipeline: {e}")
                continue

    def latest_market_tick(self) -> Tick:
        return next(self._market_stream)
