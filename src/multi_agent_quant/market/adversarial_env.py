from __future__ import annotations

import random
from typing import List

from ..agents.base import AgentSignal
from ..config import MarketSimulationSettings
from ..shared.logging import get_logger

LOGGER = get_logger(__name__)


class MarketEnvironment:
    def __init__(self, cfg: MarketSimulationSettings):
        self.cfg = cfg

    def apply_shocks(self, signals: List[AgentSignal]) -> List[AgentSignal]:
        adjusted: List[AgentSignal] = []
        for signal in signals:
            shock = random.uniform(-0.05, 0.05)
            confidence = max(0.0, min(1.0, signal.confidence + shock))
            adjusted.append(
                AgentSignal(
                    agent_id=signal.agent_id,
                    symbol=signal.symbol,
                    action=signal.action,
                    confidence=confidence,
                    metadata={**signal.metadata, "shock": shock},
                )
            )
        LOGGER.info("Applied adversarial shocks", extra={"count": len(adjusted)})
        return adjusted
