from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from ..shared.logging import get_logger

LOGGER = get_logger(__name__)


@dataclass
class NewsEvent:
    id: str
    title: str
    content: str
    timestamp: float
    sentiment: float
    relevance: float
    symbols: List[str]


class BaseNewsFeed:
    def __init__(self, config: Dict[str, any]):
        self.config = config

    def stream(self) -> Iterable[NewsEvent]:
        raise NotImplementedError


class SyntheticNewsFeed(BaseNewsFeed):
    def __init__(self, config: Dict[str, any]):
        super().__init__(config)
        self.symbols = config.get("symbols", ["510300.SH", "600519.SH"])
        self.languages = config.get("languages", ["zh"])
        self.refresh_interval = config.get("refresh_interval", 60)
        self.news_templates = [
            "{symbol} 发布了季度财报，业绩超出预期",
            "{symbol} 宣布重大战略合作",
            "{symbol} 股价大幅上涨，创历史新高",
            "{symbol} 行业政策利好，分析师看好",
            "{symbol} 技术突破，新产品即将发布",
        ]

    def stream(self) -> Iterable[NewsEvent]:
        import random
        import uuid
        
        while True:
            for symbol in self.symbols:
                template = random.choice(self.news_templates)
                title = template.format(symbol=symbol)
                content = f"{title}。详细内容请关注公司公告。"
                event = NewsEvent(
                    id=str(uuid.uuid4()),
                    title=title,
                    content=content,
                    timestamp=time.time(),
                    sentiment=random.uniform(0.3, 0.7),
                    relevance=random.uniform(0.5, 1.0),
                    symbols=[symbol]
                )
                yield event
            time.sleep(self.refresh_interval)


class TushareNewsFeed(BaseNewsFeed):
    def __init__(self, config: Dict[str, any]):
        super().__init__(config)
        self.token = config.get("token")
        self.symbols = config.get("symbols", [])
        self.refresh_interval = config.get("refresh_interval", 60)
        self._ts_module = None

    def _get_tushare(self):
        if self._ts_module is not None:
            return self._ts_module
        try:
            import tushare as ts
        except ImportError as exc:
            raise RuntimeError(
                "TushareNewsFeed 需要安装 tushare 包；请先 `pip install tushare`。"
            ) from exc
        if not self.token:
            raise RuntimeError("TushareNewsFeed 缺少 token；请配置 token。")
        ts.set_token(self.token)
        self._ts_module = ts
        return ts

    def stream(self) -> Iterable[NewsEvent]:
        import uuid
        
        while True:
            try:
                ts = self._get_tushare()
                pro = ts.pro_api()
                
                # 获取新闻数据
                news = pro.news(src="新浪财经", start_date="20240101", end_date="20241231", fields="title,content,pub_time")
                
                for _, row in news.iterrows():
                    title = row.get("title", "")
                    content = row.get("content", "")
                    pub_time = row.get("pub_time", "")
                    
                    # 简单的相关性分析，判断新闻是否与关注的股票相关
                    relevant_symbols = []
                    for symbol in self.symbols:
                        code = symbol.split(".")[0]
                        if code in title or code in content:
                            relevant_symbols.append(symbol)
                    
                    if relevant_symbols:
                        event = NewsEvent(
                            id=str(uuid.uuid4()),
                            title=title,
                            content=content,
                            timestamp=time.time(),
                            sentiment=0.5,  # 简单默认值，实际应该使用 NLP 模型分析
                            relevance=0.7,  # 简单默认值
                            symbols=relevant_symbols
                        )
                        yield event
            except Exception as e:
                LOGGER.warning(f"Failed to fetch news: {e}")
            
            time.sleep(self.refresh_interval)


class NewsFeed:
    def __init__(self, config: Dict[str, any]):
        self.config = config
        feed_type = config.get("type", "synthetic").lower()
        
        if feed_type == "synthetic":
            self.impl = SyntheticNewsFeed(config)
        elif feed_type == "tushare":
            self.impl = TushareNewsFeed(config)
        else:
            raise ValueError(f"Unsupported news feed type: {feed_type}")

    def stream(self) -> Iterable[NewsEvent]:
        return self.impl.stream()