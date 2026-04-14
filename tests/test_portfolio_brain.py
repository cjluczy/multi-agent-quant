from types import SimpleNamespace

from multi_agent_quant.agents.base import AgentSignal
from multi_agent_quant.config import PortfolioBrainSettings
from multi_agent_quant.portfolio.brain import PortfolioBrain


def test_portfolio_brain_uses_agent_nav_and_deweights_loser() -> None:
    registry = SimpleNamespace(
        agents=[
            SimpleNamespace(agent_id="swing-scout", capital_ratio=0.2),
        ]
    )
    brain = PortfolioBrain(
        PortfolioBrainSettings(
            min_trade_notional=1_000,
            per_trade_nav_pct=0.1,
            loser_deweight_enabled=True,
            loser_deweight_floor=0.35,
            loser_deweight_slope=3.0,
        ),
        registry,
        capital_base=100_000,
    )

    allocated = brain.allocate(
        [
            AgentSignal(
                agent_id="swing-scout",
                symbol="510300.SH",
                action="sell",
                confidence=0.7,
                metadata={"capital_ratio": 0.2, "price": 10.0},
            )
        ],
        account={
            "agent_metrics": {
                "swing-scout": {
                    "net_pnl": -2_000.0,
                }
            }
        },
    )

    assert len(allocated) == 1
    metadata = allocated[0].metadata
    assert metadata["agent_nav"] == 18_000.0
    assert metadata["agent_return_pct"] == -10.0
    assert metadata["deweight_multiplier"] == 0.7
    assert metadata["effective_capital_ratio"] == 0.14
    assert metadata["target_notional"] == 1_260.0


def test_describe_agent_weights_reports_floor_when_losses_are_large() -> None:
    registry = SimpleNamespace(
        agents=[
            SimpleNamespace(agent_id="news-alpha", capital_ratio=0.25),
        ]
    )
    brain = PortfolioBrain(
        PortfolioBrainSettings(
            min_trade_notional=1_000,
            per_trade_nav_pct=0.1,
            loser_deweight_enabled=True,
            loser_deweight_floor=0.35,
            loser_deweight_slope=3.0,
        ),
        registry,
        capital_base=100_000,
    )

    weights = brain.describe_agent_weights(
        {
            "agent_metrics": {
                "news-alpha": {
                    "net_pnl": -20_000.0,
                }
            }
        }
    )

    assert weights["news-alpha"]["initial_capital"] == 25_000.0
    assert weights["news-alpha"]["nav"] == 5_000.0
    assert weights["news-alpha"]["return_pct"] == -80.0
    assert weights["news-alpha"]["deweight_multiplier"] == 0.35
    assert weights["news-alpha"]["effective_capital_ratio"] == 0.0875
