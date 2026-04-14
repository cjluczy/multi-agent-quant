from __future__ import annotations

from typing import Any, Iterable, List

from ..config import AgentSettings
from ..shared.logging import get_logger
from .base import AgentSignal, BaseAgent, ROLE_TO_CLASS

LOGGER = get_logger(__name__)


class AgentRegistry:
    def __init__(self, cfg: AgentSettings, strategy_factory):
        self.cfg = cfg
        self.strategy_factory = strategy_factory
        self.agents: List[BaseAgent] = []
        for spec in cfg.registry:
            if not spec.enabled:
                continue
            agent_cls = ROLE_TO_CLASS.get(spec.role, BaseAgent)
            if agent_cls is BaseAgent:
                raise ValueError(f"Unknown agent role: {spec.role}")
            self.agents.append(agent_cls(spec.id, spec.role, spec.capital_ratio))

    def dispatch(self, bundle: dict[str, Any]) -> List[AgentSignal]:
        signals: List[AgentSignal] = []
        for agent in self.agents:
            signal = agent.on_tick(bundle)
            if signal:
                LOGGER.info("Agent signal", extra={"agent": agent.agent_id, "action": signal.action})
                signals.append(signal)
        return signals

    def __iter__(self) -> Iterable[BaseAgent]:
        return iter(self.agents)
