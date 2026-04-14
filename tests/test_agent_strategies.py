from multi_agent_quant.agents.base import NewsEventAgent, ReactiveAgent, SwingAgent
from multi_agent_quant.data_layer.feeds import Tick


def _bundle(*, symbol: str = "510300.SH", momentum: float = 0.5, trend_strength: float = 0.5, quantity: int = 0):
    return {
        "market": [
            Tick(
                symbol=symbol,
                price=4.58,
                volume=1_000_000.0,
                features={
                    "momentum": momentum,
                    "trend_strength": trend_strength,
                    "volatility": 0.2,
                    "tick_index": 10.0,
                },
            )
        ],
        "account": {
            "agent_positions": {
                "agent-1": {
                    "stocks": {
                        symbol: {
                            "quantity": quantity,
                        }
                    }
                }
            }
        },
        "sentiment": [
            {
                "sentiment_score": 0.6,
                "headline_impact": 0.5,
            }
        ],
    }


def test_reactive_agent_skips_futures_symbol() -> None:
    agent = ReactiveAgent("agent-1", "reactive", 0.4)

    signal = agent.on_tick(_bundle(symbol="IH9999.CCFX", momentum=0.62, trend_strength=0.56))

    assert signal is None


def test_news_agent_requires_market_confirmation_for_buy() -> None:
    agent = NewsEventAgent("agent-1", "news_event", 0.3)

    flat_signal = agent.on_tick(_bundle(momentum=0.5, trend_strength=0.5))
    bullish_signal = agent.on_tick(_bundle(momentum=0.53, trend_strength=0.51))

    assert flat_signal is None
    assert bullish_signal is not None
    assert bullish_signal.action == "buy"


def test_swing_agent_has_cooldown_for_repeated_same_side_signals() -> None:
    agent = SwingAgent("agent-1", "swing", 0.3)
    first_bundle = _bundle(momentum=0.51, trend_strength=0.53)
    second_bundle = _bundle(momentum=0.52, trend_strength=0.54)
    second_bundle["market"][0].features["tick_index"] = 12.0

    first = agent.on_tick(first_bundle)
    second = agent.on_tick(second_bundle)

    assert first is not None
    assert first.action == "buy"
    assert second is None
