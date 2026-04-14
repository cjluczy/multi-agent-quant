import pathlib
import threading
import time

import yaml

import multi_agent_quant.console.service as console_service_module
from multi_agent_quant.console.service import (
    ConsoleService,
    apply_console_overrides,
    build_market_feed_capabilities,
    build_market_feed_status,
    build_run_comparison,
    extract_controls,
)


def _sample_payload() -> dict:
    return {
        "version": "0.1.0",
        "system": {
            "mode": "simulation",
            "timezone": "Asia/Shanghai",
            "market": "cn",
            "capital_base": 1000000,
            "loop_iterations": 80,
            "risk_budget": {
                "max_drawdown": 0.12,
                "var_limit": 0.08,
                "exposure_limit": 1.0,
            },
        },
        "feeds": {
            "market": {"type": "synthetic_cn", "symbols": ["510300.SH"]},
        },
        "strategy_factory": {"templates": ["trend_follow"]},
        "agents": {
            "scheduler": {"max_concurrent": 2},
            "registry": [
                {"id": "news-alpha", "role": "news_event", "capital_ratio": 0.25, "enabled": True},
                {"id": "index-hedge", "role": "futures_hedge", "capital_ratio": 0.2, "enabled": True},
            ],
        },
        "risk_engine": {
            "controls": {
                "kill_switch": False,
                "position_limit_pct": 0.35,
                "min_confidence": 0.45,
                "max_volatility": 0.8,
                "max_stock_position_pct": 0.3,
                "max_futures_contracts_per_symbol": 2,
                "max_futures_margin_pct": 0.28,
                "max_futures_notional_pct": 0.7,
                "max_gross_exposure_pct": 0.95,
            }
        },
        "execution": {
            "venues": [{"name": "sim-ctp", "type": "paper", "adapter": "ctp"}],
            "default_venue": "sim-ctp",
            "lot_size": 100,
            "futures_multiplier": {"IH9999.CCFX": 300},
            "futures_margin_rate": 0.12,
            "futures_maintenance_margin_rate": 0.1,
            "futures_fee_rate": 0.000023,
            "blotter_path": "runtime/blotter.jsonl",
        },
    }


def test_apply_console_overrides_updates_risk_and_agents() -> None:
    payload = _sample_payload()
    updated = apply_console_overrides(
        payload,
        {
            "system": {"loop_iterations": 120},
            "risk_controls": {
                "max_stock_position_pct": 0.22,
                "max_futures_contracts_per_symbol": 1,
            },
            "agents": [
                {"id": "news-alpha", "enabled": False, "capital_ratio": 0.1},
            ],
        },
    )

    assert updated["system"]["loop_iterations"] == 120
    assert updated["risk_engine"]["controls"]["max_stock_position_pct"] == 0.22
    assert updated["risk_engine"]["controls"]["max_futures_contracts_per_symbol"] == 1
    assert updated["agents"]["registry"][0]["enabled"] is False
    assert updated["agents"]["registry"][0]["capital_ratio"] == 0.1


def test_apply_console_overrides_updates_market_feed_and_runtime_settings() -> None:
    payload = _sample_payload()
    updated = apply_console_overrides(
        payload,
        {
            "system": {
                "mode": "realtime",
                "market": "cn",
                "timezone": "Asia/Shanghai",
                "capital_base": 1500000,
                "poll_interval_seconds": 5,
                "loop_iterations": 40,
                "risk_budget": {
                    "max_drawdown": 0.1,
                    "var_limit": 0.06,
                    "exposure_limit": 0.9,
                },
            },
            "market_feed": {
                "type": "csv_replay",
                "symbols": ["510300.SH", "600519.SH"],
                "path": "data/live_ticks.csv",
                "replay_interval_seconds": 0.5,
                "symbol_field": "ts_code",
                "price_field": "last_price",
                "volume_field": "vol",
                "feature_window": 12,
            },
            "strategy_factory": {
                "templates": ["trend_follow", "event_driven"],
                "autogen": {"enabled": True, "max_candidates": 16},
                "genetic": {"population": 20, "elitism": 0.25},
            },
            "agents": [
                {"id": "news-alpha", "role": "breakout", "enabled": True, "capital_ratio": 0.35},
            ],
        },
    )

    assert updated["system"]["mode"] == "realtime"
    assert updated["system"]["capital_base"] == 1500000.0
    assert updated["system"]["poll_interval_seconds"] == 5.0
    assert updated["system"]["risk_budget"]["max_drawdown"] == 0.1
    assert updated["feeds"]["market"]["type"] == "csv_replay"
    assert updated["feeds"]["market"]["path"] == "data/live_ticks.csv"
    assert updated["feeds"]["market"]["feature_window"] == 12
    assert updated["strategy_factory"]["autogen"]["max_candidates"] == 16
    assert updated["strategy_factory"]["genetic"]["population"] == 20
    assert updated["agents"]["registry"][0]["role"] == "breakout"


def test_extract_controls_returns_console_shape() -> None:
    controls = extract_controls(_sample_payload())

    assert controls["loop_iterations"] == 80
    assert controls["risk_controls"]["max_gross_exposure_pct"] == 0.95
    assert controls["market_feed"]["type"] == "synthetic_cn"
    assert controls["agents"][0]["id"] == "news-alpha"
    assert controls["agents"][1]["enabled"] is True


def test_build_market_feed_status_marks_tushare_fallback_ready(monkeypatch) -> None:
    payload = _sample_payload()
    payload["feeds"]["market"] = {
        "type": "tushare_realtime",
        "symbols": ["510300.SH", "600519.SH", "IH9999.CCFX"],
        "token_env": "TUSHARE_TOKEN",
        "fallback_provider": "easyquotation",
    }

    def fake_find_spec(name: str):
        return object() if name in {"tushare", "easyquotation"} else None

    monkeypatch.setattr(console_service_module.importlib.util, "find_spec", fake_find_spec)
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)

    status = build_market_feed_status(payload)

    assert status["ready"] is True
    assert status["ready_mode"] == "fallback"
    assert status["supported_symbols"] == ["510300.SH", "600519.SH"]
    assert status["unsupported_symbols"] == ["IH9999.CCFX"]


def test_build_market_feed_status_marks_easyquotation_unsupported_symbols(monkeypatch) -> None:
    payload = _sample_payload()
    payload["feeds"]["market"] = {
        "type": "easyquotation_realtime",
        "symbols": ["510300.SH", "IH9999.CCFX"],
        "provider": "sina",
    }

    monkeypatch.setattr(console_service_module.importlib.util, "find_spec", lambda name: object() if name == "easyquotation" else None)

    status = build_market_feed_status(payload)

    assert status["ready"] is True
    assert status["supported_symbols"] == ["510300.SH"]
    assert status["unsupported_symbols"] == ["IH9999.CCFX"]


def test_build_market_feed_capabilities_reads_packages_and_env(monkeypatch) -> None:
    monkeypatch.setenv("TUSHARE_TOKEN", "demo-token")

    def fake_find_spec(name: str):
        return object() if name in {"tushare", "easyquotation"} else None

    monkeypatch.setattr(console_service_module.importlib.util, "find_spec", fake_find_spec)

    capabilities = build_market_feed_capabilities()

    assert capabilities["tushare"]["has_package"] is True
    assert capabilities["tushare"]["has_env_token"] is True
    assert capabilities["easyquotation"]["has_package"] is True


def test_console_service_reads_summary_when_available(tmp_path: pathlib.Path) -> None:
    project_dir = tmp_path
    config_path = project_dir / "config.yaml"
    runtime_dir = project_dir / "runtime"
    runtime_dir.mkdir()
    config_path.write_text(yaml.safe_dump(_sample_payload(), sort_keys=False), encoding="utf-8")
    (runtime_dir / "dashboard_summary.json").write_text(
        '{"kpis":{"equity":12345},"positions":{"stocks":[],"futures":[]},"recent_fills":[]}',
        encoding="utf-8",
    )
    (runtime_dir / "run_history.jsonl").write_text(
        '{"run_id":"r1","equity":12345,"trade_count":10}\n',
        encoding="utf-8",
    )

    service = ConsoleService(project_dir, config_path)
    state = service.build_state()

    assert state["summary"]["kpis"]["equity"] == 12345
    assert state["controls"]["agents"][0]["role"] == "news_event"
    assert state["history"][0]["run_id"] == "r1"


def test_build_run_comparison_uses_latest_two_runs() -> None:
    comparison = build_run_comparison(
        [
            {
                "run_id": "r2",
                "equity": 110.0,
                "total_return_pct": 10.0,
                "max_drawdown_pct": 2.0,
                "trade_count": 12,
                "leverage_ratio": 0.4,
            },
            {
                "run_id": "r1",
                "equity": 100.0,
                "total_return_pct": 5.0,
                "max_drawdown_pct": 1.5,
                "trade_count": 10,
                "leverage_ratio": 0.3,
            },
        ]
    )

    assert comparison["equity_delta"] == 10.0
    assert comparison["return_pct_delta"] == 5.0
    assert comparison["trade_count_delta"] == 2


def test_console_service_can_start_simulation_in_background(tmp_path: pathlib.Path, monkeypatch) -> None:
    project_dir = tmp_path
    config_path = project_dir / "config.yaml"
    runtime_dir = project_dir / "runtime"
    runtime_dir.mkdir()
    config_path.write_text(yaml.safe_dump(_sample_payload(), sort_keys=False), encoding="utf-8")

    started = threading.Event()
    release = threading.Event()

    def fake_bootstrap_system(config_path_arg, *, run_ablation):
        assert run_ablation is True
        started.set()
        (runtime_dir / "dashboard_summary.json").write_text(
            '{"kpis":{"equity":45678},"positions":{"stocks":[],"futures":[]},"recent_fills":[]}',
            encoding="utf-8",
        )
        release.wait(timeout=2)
        return {"kpis": {"equity": 45678}}

    monkeypatch.setattr(console_service_module, "bootstrap_system", fake_bootstrap_system)

    service = ConsoleService(project_dir, config_path)
    state = service.start_simulation({"system": {"loop_iterations": 3}})

    assert state["status"] == "running"
    assert started.wait(timeout=1)

    release.set()
    deadline = time.time() + 2
    while service.status == "running" and time.time() < deadline:
        time.sleep(0.02)

    final_state = service.build_state()
    assert final_state["status"] == "idle"
    assert final_state["summary"]["kpis"]["equity"] == 45678
