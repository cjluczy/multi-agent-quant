from pathlib import Path

from multi_agent_quant.config import load_config
from multi_agent_quant.reporting.ops import build_runtime_alerts, enrich_summary_with_ops


def test_build_runtime_alerts_detects_forced_liquidation_and_deweight() -> None:
    cfg = load_config(Path("configs/system.example.yaml"))
    summary = {
        "mode": "simulation",
        "run_id": "run-1",
        "generated_at": "2026-03-20T10:00:00",
        "market": "cn",
        "kpis": {
            "equity": 950000.0,
            "leverage_ratio": 0.94,
            "trade_count": 10,
        },
        "performance": {
            "total_return_pct": -5.0,
            "max_drawdown_pct": 13.0,
        },
        "risk_events": {
            "forced_liquidation_count": 1,
        },
        "agent_attribution": {
            "ranking": [
                {
                    "agent_id": "news-alpha",
                    "return_pct": -8.0,
                    "deweight_multiplier": 0.76,
                }
            ]
        },
        "data_source": {
            "market_feed_type": "csv_replay",
            "market_symbols": ["510300.SH"],
        },
    }

    alerts = build_runtime_alerts(summary, cfg)
    codes = {item["code"] for item in alerts}

    assert "FORCED_LIQUIDATION" in codes
    assert "DRAWDOWN_LIMIT_BREACH" in codes
    assert "AGENT_DEWEIGHTED" in codes


def test_enrich_summary_with_ops_adds_report_and_alerts() -> None:
    cfg = load_config(Path("configs/system.realtime.example.yaml"))
    summary = {
        "mode": "realtime",
        "run_id": "run-2",
        "generated_at": "2026-03-20T10:00:00",
        "market": "cn",
        "kpis": {
            "equity": 1000000.0,
            "leverage_ratio": 0.2,
            "trade_count": 0,
        },
        "performance": {
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
        },
        "risk_events": {
            "forced_liquidation_count": 0,
        },
        "agent_attribution": {
            "ranking": [],
            "top_winner": {},
            "top_loser": {},
        },
        "data_source": {
            "market_feed_type": "tushare_realtime",
            "market_symbols": ["510300.SH"],
        },
    }

    enrich_summary_with_ops(summary, cfg)

    assert "alerts" in summary
    assert "ops_report" in summary
    assert any(item["code"] == "REALTIME_MODE" for item in summary["alerts"])
    assert "运行摘要" in summary["ops_report"]


def test_build_runtime_alerts_warns_outside_cn_market_hours() -> None:
    cfg = load_config(Path("configs/system.easyquotation.example.yaml"))
    summary = {
        "mode": "realtime",
        "run_id": "run-3",
        "generated_at": "2026-03-20T22:48:59",
        "market": "cn",
        "kpis": {
            "equity": 1000000.0,
            "leverage_ratio": 0.2,
            "trade_count": 2,
        },
        "performance": {
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
        },
        "risk_events": {
            "forced_liquidation_count": 0,
        },
        "agent_attribution": {
            "ranking": [],
            "top_winner": {},
            "top_loser": {},
        },
        "data_source": {
            "market_feed_type": "easyquotation_realtime",
            "market_symbols": ["510300.SH"],
        },
    }

    alerts = build_runtime_alerts(summary, cfg)
    codes = {item["code"] for item in alerts}

    assert "REALTIME_MODE" in codes
    assert "OUTSIDE_MARKET_HOURS" in codes

