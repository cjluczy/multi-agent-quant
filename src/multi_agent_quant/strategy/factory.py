from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, List

from ..config import StrategyFactorySettings
from ..data_layer.pipelines import DataPipeline
from ..reasoning import LLMRouter, LLMTask
from ..shared.logging import get_logger
from .factors import FactorCalculator

LOGGER = get_logger(__name__)


@dataclass
class StrategyCandidate:
    name: str
    params: Dict[str, float]
    score: float = 0.0
    origin: str = "template"


class StrategyFactory:
    def __init__(self, cfg: StrategyFactorySettings, data_pipeline: DataPipeline):
        self.cfg = cfg
        self.pipeline = data_pipeline
        self.router = LLMRouter({"default": "qwen2.5:32b"})
        self.factor_calculator = FactorCalculator()
        self._cache: List[StrategyCandidate] = []

    def refresh_if_needed(self) -> None:
        if len(self._cache) < 3:
            LOGGER.info("Refreshing strategy cache")
            self._cache.extend(self.generate_candidates())

    def generate_candidates(self, limit: int | None = None) -> List[StrategyCandidate]:
        limit = limit or self.cfg.autogen.max_candidates
        candidates: List[StrategyCandidate] = []
        
        # 获取最新的市场数据和新闻事件
        context = {"momentum": random.random()}
        try:
            # 尝试获取最新的市场数据
            tick = self.pipeline.latest_market_tick()
            context["latest_price"] = tick.price
            context["symbol"] = tick.symbol
            
            # 计算技术面和基本面因子
            fundamental_data = {}
            bundle = next(self.pipeline.stream(max_iterations=1))
            if "fundamental" in bundle and bundle["fundamental"]:
                fundamental_data = bundle["fundamental"][0]
            
            factors = self.factor_calculator.calculate_all_factors(tick, fundamental_data)
            context.update(factors)
            
            # 尝试获取新闻事件
            if "news" in bundle and bundle["news"]:
                news_events = bundle["news"]
                if news_events:
                    latest_news = news_events[0]
                    context["latest_news_title"] = latest_news.title
                    context["news_sentiment"] = latest_news.sentiment
                    context["news_relevance"] = latest_news.relevance
        except Exception:
            pass
        
        for template in self.cfg.templates:
            params = {"lookback": random.randint(5, 60), "threshold": round(random.random(), 4)}
            candidates.append(StrategyCandidate(template, params))
        if self.cfg.autogen.enabled:
            prompts = [
                LLMTask(
                    prompt=f"Create A-share or futures strategy from template {name} based on latest market data and news",
                    context=context,
                    task_type="strategy_gen",
                )
                for name in self.cfg.templates
            ]
            outputs = self.router.run(prompts)
            for idx, output in enumerate(outputs):
                candidates.append(
                    StrategyCandidate(
                        name=f"llm_{idx}",
                        params={"confidence": round(random.random(), 4)},
                        origin=output,
                    )
                )
        random.shuffle(candidates)
        return candidates[:limit]

    def next_best(self) -> StrategyCandidate:
        self.refresh_if_needed()
        candidate = self._cache.pop(0)
        candidate.score = random.random()
        return candidate
