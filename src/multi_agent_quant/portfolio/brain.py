from __future__ import annotations

from typing import Any, List

from ..agents.base import AgentSignal
from ..agents.registry import AgentRegistry
from ..config import PortfolioBrainSettings
from ..shared.logging import get_logger

LOGGER = get_logger(__name__)


class PortfolioBrain:
    def __init__(self, cfg: PortfolioBrainSettings, registry: AgentRegistry, capital_base: float):
        self.cfg = cfg
        self.registry = registry
        self.capital_base = capital_base

    def allocate(self, signals: List[AgentSignal], account: dict[str, Any] | None = None) -> List[AgentSignal]:
        account = account or {}
        allocations: List[AgentSignal] = []
        for signal in signals:
            if signal.action == "hold":
                continue
            factor = self._score(signal)
            weight_state = self._agent_weight_state(signal.agent_id, signal.metadata["capital_ratio"], account)
            target_notional = max(
                self.cfg.min_trade_notional,
                weight_state["nav"] * self.cfg.per_trade_nav_pct * factor * weight_state["deweight_multiplier"],
            )
            preferred_notional = signal.metadata.get("preferred_notional")
            if preferred_notional is not None:
                target_notional = max(target_notional, preferred_notional)
            allocations.append(
                AgentSignal(
                    agent_id=signal.agent_id,
                    symbol=signal.symbol,
                    action=signal.action,
                    confidence=min(1.0, signal.confidence * factor),
                    metadata={
                        **signal.metadata,
                        "allocation_factor": factor,
                        "agent_nav": round(weight_state["nav"], 2),
                        "agent_return_pct": round(weight_state["return_pct"], 4),
                        "deweight_multiplier": round(weight_state["deweight_multiplier"], 4),
                        "effective_capital_ratio": round(weight_state["effective_capital_ratio"], 4),
                        "target_notional": round(target_notional, 2),
                    },
                )
            )
        LOGGER.info("Portfolio allocation complete", extra={"count": len(allocations)})
        return allocations

    def describe_agent_weights(self, account: dict[str, Any] | None = None) -> dict[str, dict[str, float]]:
        account = account or {}
        weight_state: dict[str, dict[str, float]] = {}
        for agent in self.registry.agents:
            state = self._agent_weight_state(agent.agent_id, agent.capital_ratio, account)
            weight_state[agent.agent_id] = {
                "initial_capital": round(state["initial_capital"], 2),
                "nav": round(state["nav"], 2),
                "return_pct": round(state["return_pct"], 4),
                "deweight_multiplier": round(state["deweight_multiplier"], 4),
                "effective_capital_ratio": round(state["effective_capital_ratio"], 4),
            }
        return weight_state

    def _score(self, signal: AgentSignal) -> float:
        base = 1.0
        if signal.action == "buy":
            base += 0.1
        if signal.metadata.get("momentum", 0) > 0.6:
            base += 0.1
        return base

    def _agent_weight_state(
        self,
        agent_id: str,
        capital_ratio: float,
        account: dict[str, Any],
    ) -> dict[str, float]:
        initial_capital = max(self.capital_base * capital_ratio, self.cfg.min_trade_notional)
        agent_metrics = account.get("agent_metrics", {}).get(agent_id, {})
        net_pnl = float(agent_metrics.get("net_pnl", 0.0))
        nav = max(initial_capital + net_pnl, self.cfg.min_trade_notional)
        return_pct = ((nav - initial_capital) / initial_capital * 100) if initial_capital > 0 else 0.0
        deweight_multiplier = 1.0
        if self.cfg.loser_deweight_enabled and return_pct < 0:
            deweight_multiplier = max(
                self.cfg.loser_deweight_floor,
                1.0 + (return_pct / 100.0) * self.cfg.loser_deweight_slope,
            )
        effective_capital_ratio = capital_ratio * deweight_multiplier
        return {
            "initial_capital": initial_capital,
            "nav": nav,
            "return_pct": return_pct,
            "deweight_multiplier": deweight_multiplier,
            "effective_capital_ratio": effective_capital_ratio,
        }
