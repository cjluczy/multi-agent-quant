import pathlib

from multi_agent_quant.agents.base import AgentSignal
from multi_agent_quant.config import ExecutionSettings
from multi_agent_quant.execution.order_router import PaperBroker
from multi_agent_quant.reporting.dashboard import build_dashboard_summary


def _execution_settings(blotter_path: pathlib.Path) -> ExecutionSettings:
    return ExecutionSettings(
        venues=[{"name": "sim-ctp", "type": "paper", "adapter": "ctp"}],
        default_venue="sim-ctp",
        lot_size=100,
        futures_multiplier={"IH9999.CCFX": 300},
        futures_margin_rate=0.12,
        futures_maintenance_margin_rate=0.1,
        futures_fee_rate=0.000023,
        blotter_path=str(blotter_path),
    )


def test_build_dashboard_summary_includes_agent_attribution(tmp_path: pathlib.Path) -> None:
    blotter_path = tmp_path / "blotter.jsonl"
    broker = PaperBroker(_execution_settings(blotter_path), initial_cash=1_000_000)

    broker.execute(
        AgentSignal(
            agent_id="news-alpha",
            symbol="510300.SH",
            action="buy",
            confidence=0.8,
            metadata={"price": 10.0, "target_notional": 1_000.0},
        ),
        "sim-ctp",
    )
    broker.execute(
        AgentSignal(
            agent_id="news-alpha",
            symbol="510300.SH",
            action="sell",
            confidence=0.8,
            metadata={"price": 12.0, "target_notional": 1_200.0},
        ),
        "sim-ctp",
    )
    broker.execute(
        AgentSignal(
            agent_id="reactive-hft",
            symbol="600519.SH",
            action="buy",
            confidence=0.7,
            metadata={"price": 100.0, "target_notional": 10_000.0},
        ),
        "sim-ctp",
    )

    account = broker.snapshot()
    account["agent_weight_state"] = {
        "news-alpha": {
            "initial_capital": 300_000.0,
            "nav": 300_200.0,
            "return_pct": 0.0667,
            "deweight_multiplier": 1.0,
            "effective_capital_ratio": 0.3,
        },
        "reactive-hft": {
            "initial_capital": 300_000.0,
            "nav": 300_000.0,
            "return_pct": 0.0,
            "deweight_multiplier": 1.0,
            "effective_capital_ratio": 0.3,
        },
        "swing-scout": {
            "initial_capital": 300_000.0,
            "nav": 285_000.0,
            "return_pct": -5.0,
            "deweight_multiplier": 0.85,
            "effective_capital_ratio": 0.255,
        },
    }
    summary = build_dashboard_summary(
        run_id="run-1",
        generated_at="2026-03-18T18:30:00",
        mode="simulation",
        market="cn",
        ticks_processed=3,
        account=account,
        blotter_path=blotter_path,
        equity_curve=[
            {"tick": 0, "equity": 1_000_000.0},
            {"tick": 1, "equity": float(account["equity"])},
        ],
        active_agents=[
            {"id": "news-alpha", "role": "news_event", "capital_ratio": 0.3},
            {"id": "reactive-hft", "role": "reactive", "capital_ratio": 0.3},
            {"id": "swing-scout", "role": "swing", "capital_ratio": 0.3},
        ],
        agent_contribution_curves={
            "news-alpha": [
                {"tick": 0, "nav": 300_000.0, "net_pnl": 0.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0},
                {"tick": 1, "nav": 300_200.0, "net_pnl": 200.0, "realized_pnl": 200.0, "unrealized_pnl": 0.0},
            ],
            "reactive-hft": [
                {"tick": 0, "nav": 300_000.0, "net_pnl": 0.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0},
                {"tick": 1, "nav": 300_000.0, "net_pnl": 0.0, "realized_pnl": 0.0, "unrealized_pnl": 0.0},
            ],
        },
    )

    ranking = summary["agent_attribution"]["ranking"]
    assert [row["agent_id"] for row in ranking] == ["news-alpha", "reactive-hft", "swing-scout"]
    assert ranking[0]["realized_pnl"] == 200.0
    assert ranking[0]["unrealized_pnl"] == 0.0
    assert ranking[0]["net_pnl"] == 200.0
    assert ranking[0]["nav"] == 300_200.0
    assert ranking[2]["deweight_multiplier"] == 0.85
    assert ranking[0]["effect_breakdown"] == {"buy_stock": 1, "sell_stock": 1}
    assert ranking[1]["total_notional"] == 10_000.0
    assert ranking[2]["trade_count"] == 0
    assert summary["agent_attribution"]["top_winner"]["agent_id"] == "news-alpha"
    assert summary["agent_attribution"]["top_loser"]["agent_id"] == "swing-scout"
    assert summary["positions"]["stocks"][0]["avg_price"] == 100.0
    assert summary["positions"]["stocks"][0]["unrealized_pnl"] == 0.0
    assert summary["kpis"]["unrealized_pnl_total"] == 0.0
    assert summary["agent_contribution_curves"]["news-alpha"][-1]["nav"] == 300_200.0
    assert summary["agent_contribution_curves"]["news-alpha"][-1]["net_pnl"] == 200.0


def test_paper_broker_tracks_stock_realized_pnl(tmp_path: pathlib.Path) -> None:
    blotter_path = tmp_path / "blotter.jsonl"
    broker = PaperBroker(_execution_settings(blotter_path), initial_cash=100_000)

    broker.execute(
        AgentSignal(
            agent_id="swing-scout",
            symbol="510300.SH",
            action="buy",
            confidence=0.9,
            metadata={"price": 10.0, "target_notional": 2_000.0},
        ),
        "sim-ctp",
    )
    sell_fill = broker.execute(
        AgentSignal(
            agent_id="swing-scout",
            symbol="510300.SH",
            action="sell",
            confidence=0.9,
            metadata={"price": 11.0, "target_notional": 1_000.0},
        ),
        "sim-ctp",
    )

    assert sell_fill is not None
    assert sell_fill.realized_pnl == 100.0
    assert broker.snapshot()["realized_pnl"] == 100.0


def test_paper_broker_tracks_agent_specific_positions(tmp_path: pathlib.Path) -> None:
    blotter_path = tmp_path / "blotter.jsonl"
    broker = PaperBroker(_execution_settings(blotter_path), initial_cash=100_000)

    broker.execute(
        AgentSignal(
            agent_id="news-alpha",
            symbol="510300.SH",
            action="buy",
            confidence=0.9,
            metadata={"price": 10.0, "target_notional": 1_000.0},
        ),
        "sim-ctp",
    )
    blocked_sell = broker.execute(
        AgentSignal(
            agent_id="reactive-hft",
            symbol="510300.SH",
            action="sell",
            confidence=0.9,
            metadata={"price": 10.5, "target_notional": 1_000.0},
        ),
        "sim-ctp",
    )

    snapshot = broker.snapshot()
    assert blocked_sell is None
    assert snapshot["agent_positions"]["news-alpha"]["stocks"]["510300.SH"]["quantity"] == 100
    assert snapshot["agent_metrics"]["reactive-hft"]["trade_count"] == 0
