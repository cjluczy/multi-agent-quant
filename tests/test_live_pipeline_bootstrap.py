import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

import multi_agent_quant.main as main_module
from multi_agent_quant.main import bootstrap_system


def test_bootstrap_system_with_csv_replay_market_feed(tmp_path: Path) -> None:
    csv_path = tmp_path / "market.csv"
    csv_path.write_text(
        "symbol,price,volume\n"
        "510300.SH,3.85,100000\n"
        "510300.SH,3.89,120000\n"
        "600519.SH,1480.0,2000\n"
        "600519.SH,1485.0,2200\n",
        encoding="utf-8",
    )

    config = {
        "version": "0.1.0",
        "system": {
            "mode": "simulation",
            "timezone": "Asia/Shanghai",
            "market": "cn",
            "capital_base": 1_000_000,
            "loop_iterations": 4,
            "poll_interval_seconds": 0,
            "risk_budget": {
                "max_drawdown": 0.12,
                "var_limit": 0.08,
                "exposure_limit": 1.0,
            },
        },
        "feeds": {
            "market": {
                "type": "csv_replay",
                "path": str(csv_path),
                "symbols": ["510300.SH", "600519.SH"],
                "feature_window": 5,
            }
        },
        "strategy_factory": {"templates": ["trend_follow"]},
        "agents": {
            "scheduler": {"max_concurrent": 2},
            "registry": [
                {"id": "news-alpha", "role": "news_event", "capital_ratio": 0.5, "enabled": True},
                {"id": "reactive-hft", "role": "reactive", "capital_ratio": 0.5, "enabled": True},
            ],
        },
        "market_simulation": {
            "liquidity_model": "cn_order_book",
            "shock_scenarios": [],
            "adversaries": {"spoofing": False, "momentum_ignition": False},
            "slippage_bps": 4,
        },
        "evolution": {"population": 10, "elitism": 0.2, "refresh_interval": 10},
        "portfolio_brain": {
            "optimizer": "risk_parity",
            "bandit": {},
            "min_trade_notional": 1000,
            "per_trade_nav_pct": 0.1,
            "loser_deweight_enabled": True,
            "loser_deweight_floor": 0.35,
            "loser_deweight_slope": 3.0,
        },
        "risk_engine": {
            "controls": {
                "kill_switch": False,
                "position_limit_pct": 0.4,
                "min_confidence": 0.2,
                "max_volatility": 5.0,
                "max_stock_position_pct": 0.4,
                "max_futures_contracts_per_symbol": 0,
                "max_futures_margin_pct": 0.0,
                "max_futures_notional_pct": 0.0,
                "max_gross_exposure_pct": 1.0,
            }
        },
        "execution": {
            "venues": [{"name": "sim-stock", "type": "paper", "adapter": "stock"}],
            "default_venue": "sim-stock",
            "lot_size": 100,
            "futures_multiplier": {},
            "futures_margin_rate": 0.12,
            "futures_maintenance_margin_rate": 0.1,
            "futures_fee_rate": 0.000023,
            "blotter_path": str(tmp_path / "csv_replay_blotter.jsonl"),
        },
    }
    config_path = tmp_path / "csv_replay.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    summary = bootstrap_system(
        config_path,
        persist_outputs=False,
        append_history_enabled=False,
        runtime_dir=tmp_path / "runtime",
        run_ablation=False,
    )

    assert summary["ticks_processed"] == 4
    assert summary["active_agents"][0]["id"] == "news-alpha"
    assert summary["data_source"]["market_feed_type"] == "csv_replay"
    assert "agent_contribution_curves" in summary


def test_bootstrap_system_with_tushare_realtime_market_feed(monkeypatch, tmp_path: Path) -> None:
    class FakeFrame:
        empty = False

        def __init__(self):
            self._calls = 0

        def to_dict(self, orient: str):
            assert orient == "records"
            self._calls += 1
            if self._calls == 1:
                return [{"TS_CODE": "510300.SH", "PRICE": "3.90", "VOLUME": "100000"}]
            return [{"TS_CODE": "510300.SH", "PRICE": "3.93", "VOLUME": "110000"}]

    frame = FakeFrame()
    fake_tushare = SimpleNamespace(
        set_token=lambda token: token,
        realtime_quote=lambda ts_code: frame,
    )
    monkeypatch.setitem(sys.modules, "tushare", fake_tushare)

    config = {
        "version": "0.1.0",
        "system": {
            "mode": "realtime",
            "timezone": "Asia/Shanghai",
            "market": "cn",
            "capital_base": 1_000_000,
            "loop_iterations": 2,
            "poll_interval_seconds": 0,
            "risk_budget": {
                "max_drawdown": 0.12,
                "var_limit": 0.08,
                "exposure_limit": 1.0,
            },
        },
        "feeds": {
            "market": {
                "type": "tushare_realtime",
                "symbols": ["510300.SH"],
                "token": "demo-token",
                "poll_interval_seconds": 0,
                "feature_window": 5,
            }
        },
        "strategy_factory": {"templates": ["trend_follow"]},
        "agents": {
            "scheduler": {"max_concurrent": 1},
            "registry": [
                {"id": "reactive-hft", "role": "reactive", "capital_ratio": 1.0, "enabled": True},
            ],
        },
        "market_simulation": {
            "liquidity_model": "cn_order_book",
            "shock_scenarios": [],
            "adversaries": {"spoofing": False, "momentum_ignition": False},
            "slippage_bps": 0,
        },
        "evolution": {"population": 10, "elitism": 0.2, "refresh_interval": 10},
        "portfolio_brain": {
            "optimizer": "risk_parity",
            "bandit": {},
            "min_trade_notional": 1000,
            "per_trade_nav_pct": 0.1,
            "loser_deweight_enabled": True,
            "loser_deweight_floor": 0.35,
            "loser_deweight_slope": 3.0,
        },
        "risk_engine": {
            "controls": {
                "kill_switch": False,
                "position_limit_pct": 0.4,
                "min_confidence": 0.2,
                "max_volatility": 5.0,
                "max_stock_position_pct": 0.4,
                "max_futures_contracts_per_symbol": 0,
                "max_futures_margin_pct": 0.0,
                "max_futures_notional_pct": 0.0,
                "max_gross_exposure_pct": 1.0,
            }
        },
        "execution": {
            "venues": [{"name": "sim-stock", "type": "paper", "adapter": "stock"}],
            "default_venue": "sim-stock",
            "lot_size": 100,
            "futures_multiplier": {},
            "futures_margin_rate": 0.12,
            "futures_maintenance_margin_rate": 0.1,
            "futures_fee_rate": 0.000023,
            "blotter_path": str(tmp_path / "realtime_blotter.jsonl"),
        },
    }
    config_path = tmp_path / "tushare_realtime.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    summary = bootstrap_system(
        config_path,
        persist_outputs=False,
        append_history_enabled=False,
        runtime_dir=tmp_path / "runtime",
        run_ablation=True,
    )

    assert summary["mode"] == "realtime"
    assert summary["ticks_processed"] == 2
    assert summary["data_source"]["market_feed_type"] == "tushare_realtime"
    assert "ablation_report" not in summary


def test_bootstrap_system_with_easyquotation_realtime_can_generate_trades(monkeypatch, tmp_path: Path) -> None:
    class FakeQuotation:
        def stocks(self, stock_codes, prefix=False):
            return {
                "510300": {
                    "now": 4.60,
                    "volume": 1000000.0,
                }
            }

    class FakeEasyQuotationModule:
        @staticmethod
        def use(name: str):
            assert name == "sina"
            return FakeQuotation()

    monkeypatch.setitem(sys.modules, "easyquotation", FakeEasyQuotationModule())

    config = {
        "version": "0.1.0",
        "system": {
            "mode": "realtime",
            "timezone": "Asia/Shanghai",
            "market": "cn",
            "capital_base": 1_000_000,
            "loop_iterations": 2,
            "poll_interval_seconds": 0,
            "risk_budget": {
                "max_drawdown": 0.12,
                "var_limit": 0.08,
                "exposure_limit": 1.0,
            },
        },
        "feeds": {
            "market": {
                "type": "easyquotation_realtime",
                "provider": "sina",
                "symbols": ["510300.SH"],
                "poll_interval_seconds": 0,
                "feature_window": 5,
            },
            "sentiment": {
                "type": "synthetic_news",
                "languages": ["zh"],
                "llm_summarizer": "qwen2.5:32b",
            },
        },
        "strategy_factory": {"templates": ["trend_follow"]},
        "agents": {
            "scheduler": {"max_concurrent": 1},
            "registry": [
                {"id": "news-alpha", "role": "news_event", "capital_ratio": 0.3, "enabled": True},
            ],
        },
        "market_simulation": {
            "liquidity_model": "cn_order_book",
            "shock_scenarios": [],
            "adversaries": {"spoofing": False, "momentum_ignition": False},
            "slippage_bps": 0,
        },
        "evolution": {"population": 10, "elitism": 0.2, "refresh_interval": 10},
        "portfolio_brain": {
            "optimizer": "risk_parity",
            "bandit": {},
            "min_trade_notional": 1000,
            "per_trade_nav_pct": 0.1,
            "loser_deweight_enabled": True,
            "loser_deweight_floor": 0.35,
            "loser_deweight_slope": 3.0,
        },
        "risk_engine": {
            "controls": {
                "kill_switch": False,
                "position_limit_pct": 1.0,
                "min_confidence": 0.2,
                "max_volatility": 5.0,
                "max_stock_position_pct": 0.4,
                "max_futures_contracts_per_symbol": 0,
                "max_futures_margin_pct": 0.0,
                "max_futures_notional_pct": 0.0,
                "max_gross_exposure_pct": 1.0,
            }
        },
        "execution": {
            "venues": [{"name": "sim-stock", "type": "paper", "adapter": "stock"}],
            "default_venue": "sim-stock",
            "lot_size": 100,
            "futures_multiplier": {},
            "futures_margin_rate": 0.12,
            "futures_maintenance_margin_rate": 0.1,
            "futures_fee_rate": 0.000023,
            "blotter_path": str(tmp_path / "easyquotation_realtime_blotter.jsonl"),
        },
    }
    config_path = tmp_path / "easyquotation_realtime.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    summary = bootstrap_system(
        config_path,
        persist_outputs=False,
        append_history_enabled=False,
        runtime_dir=tmp_path / "runtime",
        run_ablation=False,
    )

    assert summary["data_source"]["market_feed_type"] == "easyquotation_realtime"
    assert summary["kpis"]["trade_count"] > 0


def test_bootstrap_system_persists_runtime_progress_each_tick(monkeypatch, tmp_path: Path) -> None:
    config = {
        "version": "0.1.0",
        "system": {
            "mode": "simulation",
            "timezone": "Asia/Shanghai",
            "market": "cn",
            "capital_base": 1_000_000,
            "loop_iterations": 2,
            "poll_interval_seconds": 0,
            "risk_budget": {
                "max_drawdown": 0.12,
                "var_limit": 0.08,
                "exposure_limit": 1.0,
            },
        },
        "feeds": {
            "market": {
                "type": "synthetic_cn",
                "symbols": ["510300.SH"],
                "initial_price": {"510300.SH": 3.85},
                "seed": 7,
                "feature_window": 5,
            }
        },
        "strategy_factory": {"templates": ["trend_follow"]},
        "agents": {
            "scheduler": {"max_concurrent": 1},
            "registry": [
                {"id": "reactive-hft", "role": "reactive", "capital_ratio": 1.0, "enabled": True},
            ],
        },
        "market_simulation": {
            "liquidity_model": "cn_order_book",
            "shock_scenarios": [],
            "adversaries": {"spoofing": False, "momentum_ignition": False},
            "slippage_bps": 0,
        },
        "evolution": {"population": 10, "elitism": 0.2, "refresh_interval": 10},
        "portfolio_brain": {
            "optimizer": "risk_parity",
            "bandit": {},
            "min_trade_notional": 1000,
            "per_trade_nav_pct": 0.1,
            "loser_deweight_enabled": True,
            "loser_deweight_floor": 0.35,
            "loser_deweight_slope": 3.0,
        },
        "risk_engine": {
            "controls": {
                "kill_switch": False,
                "position_limit_pct": 0.4,
                "min_confidence": 0.2,
                "max_volatility": 5.0,
                "max_stock_position_pct": 0.4,
                "max_futures_contracts_per_symbol": 0,
                "max_futures_margin_pct": 0.0,
                "max_futures_notional_pct": 0.0,
                "max_gross_exposure_pct": 1.0,
            }
        },
        "execution": {
            "venues": [{"name": "sim-stock", "type": "paper", "adapter": "stock"}],
            "default_venue": "sim-stock",
            "lot_size": 100,
            "futures_multiplier": {},
            "futures_margin_rate": 0.12,
            "futures_maintenance_margin_rate": 0.1,
            "futures_fee_rate": 0.000023,
            "blotter_path": str(tmp_path / "progress_blotter.jsonl"),
        },
    }
    config_path = tmp_path / "progress.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    persisted_ticks: list[int] = []
    original_persist = main_module._persist_runtime_outputs

    def capture_persist(*args, **kwargs):
        summary = original_persist(*args, **kwargs)
        persisted_ticks.append(int(summary["ticks_processed"]))
        return summary

    monkeypatch.setattr(main_module, "_persist_runtime_outputs", capture_persist)

    summary = bootstrap_system(
        config_path,
        persist_outputs=True,
        append_history_enabled=False,
        runtime_dir=tmp_path / "runtime",
        run_ablation=False,
    )

    assert summary["ticks_processed"] == 2
    assert persisted_ticks == [1, 2]
