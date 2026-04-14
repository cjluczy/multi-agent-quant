from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from ..agents.base import AgentSignal
from ..config import EvolutionSettings
from ..shared.logging import get_logger
from ..strategy import StrategyFactory

LOGGER = get_logger(__name__)


@dataclass
class EvolutionHistory:
    buffer: List[AgentSignal] = field(default_factory=list)

    def push(self, signals: List[AgentSignal]) -> None:
        self.buffer.extend(signals)
        self.buffer = self.buffer[-200:]


class EvolutionEngine:
    def __init__(self, cfg: EvolutionSettings, factory: StrategyFactory):
        self.cfg = cfg
        self.history = EvolutionHistory()
        self.factory = factory
        self.update_count = 0

    def update(self, history: List[AgentSignal]) -> None:
        self.history.push(history)
        self.update_count += 1
        if (
            len(self.history.buffer) >= self.cfg.population
            and self.update_count % self.cfg.refresh_interval == 0
        ):
            LOGGER.info("Running evolutionary step")
            self.factory.generate_candidates(limit=5)
