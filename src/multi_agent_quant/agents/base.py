from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Dict

from ..data_layer.feeds import Tick


@dataclass
class AgentSignal:
    agent_id: str
    symbol: str
    action: str
    confidence: float
    metadata: Dict[str, float]


class BaseAgent:
    def __init__(self, agent_id: str, role: str, capital_ratio: float):
        self.agent_id = agent_id
        self.role = role
        self.capital_ratio = capital_ratio
        self._last_signal_tick: dict[tuple[str, str], int] = {}

    def on_tick(self, bundle: Dict[str, Any]) -> AgentSignal | None:
        raise NotImplementedError

    def _base_metadata(self, tick: Tick) -> Dict[str, float]:
        mid_price = tick.price
        bid_price = tick.bid_price or mid_price
        ask_price = tick.ask_price or mid_price
        spread_bps = ((ask_price - bid_price) / mid_price * 10000.0) if mid_price > 0 else 0.0
        return {
            "capital_ratio": self.capital_ratio,
            "price": mid_price,
            "bid_price": bid_price,
            "ask_price": ask_price,
            "spread_bps": round(spread_bps, 4),
            "momentum": tick.features.get("momentum", 0.0),
            "trend_strength": tick.features.get("trend_strength", 0.0),
            "volatility": tick.features.get("volatility", 0.0),
        }

    def _current_tick(self, bundle: Dict[str, Any]) -> Tick:
        # 随机选择一个股票的tick数据
        import random
        return random.choice(bundle["market"])

    def _account(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        return bundle.get("account", {})

    def _agent_book(self, bundle: Dict[str, Any]) -> Dict[str, Any]:
        account = self._account(bundle)
        return account.get("agent_positions", {}).get(self.agent_id, {})

    def _stock_position(self, bundle: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        agent_book = self._agent_book(bundle)
        stock_positions = agent_book.get("stocks", {})
        position = stock_positions.get(symbol)
        if position:
            return position
        account = self._account(bundle)
        quantity = int(account.get("stock_positions", {}).get(symbol, 0))
        return {"quantity": quantity}

    def _futures_position(self, bundle: Dict[str, Any], symbol: str) -> Dict[str, Any]:
        agent_book = self._agent_book(bundle)
        futures_positions = agent_book.get("futures", {})
        position = futures_positions.get(symbol)
        if position:
            return position
        account = self._account(bundle)
        return account.get("futures_positions", {}).get(symbol, {})

    def _is_futures_symbol(self, symbol: str) -> bool:
        return symbol.endswith("CCFX")

    def _fundamental_snapshot(self, bundle: Dict[str, Any]) -> Dict[str, float]:
        snapshot = bundle.get("fundamental", [{}])
        if isinstance(snapshot, list) and snapshot:
            return snapshot[0]
        if isinstance(snapshot, dict):
            return snapshot
        return {}

    def _passes_cooldown(self, tick: Tick, symbol: str, action: str, cooldown_ticks: int) -> bool:
        if cooldown_ticks <= 0:
            return True
        tick_index = int(tick.features.get("tick_index", 0.0))
        key = (symbol, action)
        last_tick = self._last_signal_tick.get(key, -cooldown_ticks)
        if tick_index - last_tick < cooldown_ticks:
            return False
        self._last_signal_tick[key] = tick_index
        return True

    def _build_signal(
        self,
        *,
        tick: Tick,
        action: str,
        confidence: float,
        metadata: Dict[str, float],
        cooldown_ticks: int = 0,
    ) -> AgentSignal | None:
        if not self._passes_cooldown(tick, tick.symbol, action, cooldown_ticks):
            return None
        return AgentSignal(
            agent_id=self.agent_id,
            symbol=tick.symbol,
            action=action,
            confidence=round(max(0.0, min(1.0, confidence)), 4),
            metadata=metadata,
        )


class ReactiveAgent(BaseAgent):
    def on_tick(self, bundle: Dict[str, Any]) -> AgentSignal | None:
        tick = self._current_tick(bundle)
        if self._is_futures_symbol(tick.symbol):
            return None
        held_qty = int(self._stock_position(bundle, tick.symbol).get("quantity", 0))
        momentum = float(tick.features.get("momentum", 0.5))
        trend_strength = float(tick.features.get("trend_strength", 0.5))
        if held_qty > 0 and (momentum <= 0.485 or trend_strength < 0.495):
            action = "sell"
        elif momentum >= 0.52 and trend_strength >= 0.5:
            action = "buy"
        else:
            return None
        confidence = 0.42 + max(0.0, momentum - 0.5) * 1.15 + max(0.0, trend_strength - 0.5) * 0.45
        metadata = self._base_metadata(tick)
        metadata["signal_flavor"] = 1.0
        return self._build_signal(
            tick=tick,
            action=action,
            confidence=confidence,
            metadata=metadata,
            cooldown_ticks=2,
        )


class SwingAgent(BaseAgent):
    def on_tick(self, bundle: Dict[str, Any]) -> AgentSignal | None:
        tick = self._current_tick(bundle)
        if self._is_futures_symbol(tick.symbol):
            return None
        held_qty = int(self._stock_position(bundle, tick.symbol).get("quantity", 0))
        trend_strength = float(tick.features.get("trend_strength", 0.5))
        momentum = float(tick.features.get("momentum", 0.5))
        if held_qty > 0 and (trend_strength <= 0.49 or momentum <= 0.485):
            action = "sell"
        elif trend_strength >= 0.515 and momentum >= 0.495:
            action = "buy"
        else:
            return None
        confidence = 0.41 + max(0.0, trend_strength - 0.5) * 1.1 + abs(momentum - 0.5) * 0.3
        metadata = self._base_metadata(tick)
        metadata["signal_flavor"] = 2.0
        return self._build_signal(
            tick=tick,
            action=action,
            confidence=confidence,
            metadata=metadata,
            cooldown_ticks=4,
        )


class NewsEventAgent(BaseAgent):
    def on_tick(self, bundle: Dict[str, Any]) -> AgentSignal | None:
        tick = self._current_tick(bundle)
        if self._is_futures_symbol(tick.symbol):
            return None
        sentiment = bundle.get("sentiment", [{"sentiment_score": 0.5}])[0]
        score = float(sentiment.get("sentiment_score", 0.5))
        headline_impact = float(sentiment.get("headline_impact", 0.0))
        held_qty = int(self._stock_position(bundle, tick.symbol).get("quantity", 0))
        trend_strength = float(tick.features.get("trend_strength", 0.5))
        momentum = float(tick.features.get("momentum", 0.5))
        if held_qty > 0 and (score <= 0.46 or (trend_strength < 0.49 and momentum < 0.495)):
            action = "sell"
        elif score >= 0.58 and (trend_strength >= 0.505 or momentum >= 0.505):
            action = "buy"
        else:
            return None
        metadata = self._base_metadata(tick)
        metadata["sentiment_score"] = score
        metadata["headline_impact"] = headline_impact
        confidence = 0.34 + score * 0.32 + max(0.0, trend_strength - 0.5) * 0.35 + max(0.0, momentum - 0.5) * 0.2
        return self._build_signal(
            tick=tick,
            action=action,
            confidence=confidence,
            metadata=metadata,
            cooldown_ticks=5,
        )


class FuturesHedgeAgent(BaseAgent):
    def on_tick(self, bundle: Dict[str, Any]) -> AgentSignal | None:
        tick = bundle["market"][0]
        if not tick.symbol.endswith("CCFX"):
            return None
        position = self._futures_position(bundle, tick.symbol)
        long_qty = int(position.get("long_qty", 0))
        short_qty = int(position.get("short_qty", 0))
        low_vol = tick.features["volatility"] < 0.35
        if low_vol:
            action = "buy"
            if long_qty > 0 and tick.features["trend_strength"] > 0.58:
                return None
        else:
            action = "sell"
            if short_qty > 0 and tick.features["trend_strength"] < 0.42:
                return None
        metadata = self._base_metadata(tick)
        metadata["hedge_signal"] = 1.0
        metadata["preferred_notional"] = tick.price * 300
        return AgentSignal(
            agent_id=self.agent_id,
            symbol=tick.symbol,
            action=action,
            confidence=round(0.42 + random.random() * 0.2, 4),
            metadata=metadata,
        )


class MeanReversionAgent(BaseAgent):
    def on_tick(self, bundle: Dict[str, Any]) -> AgentSignal | None:
        tick = self._current_tick(bundle)
        if self._is_futures_symbol(tick.symbol):
            return None
        held_qty = int(self._stock_position(bundle, tick.symbol).get("quantity", 0))
        momentum = float(tick.features.get("momentum", 0.5))
        trend_strength = float(tick.features.get("trend_strength", 0.5))
        volatility = float(tick.features.get("volatility", 0.3))
        if held_qty > 0 and (momentum >= 0.515 or trend_strength >= 0.515):
            action = "sell"
        elif held_qty <= 0 and momentum <= 0.475 and trend_strength <= 0.49 and volatility <= 0.65:
            action = "buy"
        else:
            return None
        confidence = 0.38 + max(0.0, 0.5 - momentum) * 0.95 + max(0.0, 0.5 - trend_strength) * 0.45
        metadata = self._base_metadata(tick)
        metadata["signal_flavor"] = 3.0
        return self._build_signal(
            tick=tick,
            action=action,
            confidence=confidence,
            metadata=metadata,
            cooldown_ticks=3,
        )


class BreakoutAgent(BaseAgent):
    def on_tick(self, bundle: Dict[str, Any]) -> AgentSignal | None:
        tick = self._current_tick(bundle)
        if self._is_futures_symbol(tick.symbol):
            return None
        held_qty = int(self._stock_position(bundle, tick.symbol).get("quantity", 0))
        momentum = float(tick.features.get("momentum", 0.5))
        trend_strength = float(tick.features.get("trend_strength", 0.5))
        volatility = float(tick.features.get("volatility", 0.3))
        if held_qty > 0 and (momentum <= 0.5 or trend_strength <= 0.495):
            action = "sell"
        elif held_qty <= 0 and momentum >= 0.54 and trend_strength >= 0.53 and volatility >= 0.22:
            action = "buy"
        else:
            return None
        confidence = 0.41 + max(0.0, momentum - 0.5) * 1.05 + max(0.0, trend_strength - 0.5) * 0.55
        metadata = self._base_metadata(tick)
        metadata["signal_flavor"] = 4.0
        return self._build_signal(
            tick=tick,
            action=action,
            confidence=confidence,
            metadata=metadata,
            cooldown_ticks=2,
        )


class FundamentalAgent(BaseAgent):
    def on_tick(self, bundle: Dict[str, Any]) -> AgentSignal | None:
        tick = self._current_tick(bundle)
        if self._is_futures_symbol(tick.symbol):
            return None
        held_qty = int(self._stock_position(bundle, tick.symbol).get("quantity", 0))
        fundamentals = self._fundamental_snapshot(bundle)
        roe = float(fundamentals.get("roe", 1.0))
        pe_ttm = float(fundamentals.get("pe_ttm", 1.8))
        revenue_yoy = float(fundamentals.get("revenue_yoy", 2.6))
        momentum = float(tick.features.get("momentum", 0.5))
        trend_strength = float(tick.features.get("trend_strength", 0.5))
        quality_score = roe * 0.22 + revenue_yoy * 0.12 - pe_ttm * 0.08
        if held_qty > 0 and (quality_score < 0.12 or (momentum < 0.49 and trend_strength < 0.495)):
            action = "sell"
        elif held_qty <= 0 and quality_score >= 0.18 and trend_strength >= 0.5:
            action = "buy"
        else:
            return None
        confidence = 0.36 + min(0.28, max(0.0, quality_score)) + max(0.0, trend_strength - 0.5) * 0.25
        metadata = self._base_metadata(tick)
        metadata["roe"] = roe
        metadata["pe_ttm"] = pe_ttm
        metadata["revenue_yoy"] = revenue_yoy
        return self._build_signal(
            tick=tick,
            action=action,
            confidence=confidence,
            metadata=metadata,
            cooldown_ticks=6,
        )


ROLE_TO_CLASS = {
    "reactive": ReactiveAgent,
    "swing": SwingAgent,
    "news_event": NewsEventAgent,
    "futures_hedge": FuturesHedgeAgent,
    "mean_reversion": MeanReversionAgent,
    "breakout": BreakoutAgent,
    "fundamental": FundamentalAgent,
}
