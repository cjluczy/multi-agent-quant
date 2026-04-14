from __future__ import annotations

import copy
import importlib.util
import json
import os
import pathlib
import threading
from typing import Any

import yaml

from ..config import SystemConfig
from ..main import bootstrap_system
from ..reporting.dashboard import load_run_history

RUNTIME_CONFIG_NAME = "console_runtime.yaml"
SUMMARY_FILE_NAME = "dashboard_summary.json"
CONFIG_KEYS = [
    "max_stock_position_pct",
    "max_futures_contracts_per_symbol",
    "max_futures_margin_pct",
    "max_futures_notional_pct",
    "max_gross_exposure_pct",
]
RISK_CONTROL_BOOL_KEYS = {"kill_switch"}
RISK_CONTROL_INT_KEYS = {"max_futures_contracts_per_symbol"}
MARKET_FEED_STR_KEYS = {
    "type",
    "token",
    "token_env",
    "fallback_provider",
    "provider",
    "path",
    "symbol_field",
    "price_field",
    "volume_field",
}
MARKET_FEED_FLOAT_KEYS = {"poll_interval_seconds", "replay_interval_seconds"}
MARKET_FEED_INT_KEYS = {"feature_window"}


class ConsoleService:
    def __init__(self, root_dir: pathlib.Path, config_path: pathlib.Path):
        self.root_dir = root_dir
        self.config_path = config_path
        self.runtime_dir = root_dir / "runtime"
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_config_path = self.runtime_dir / RUNTIME_CONFIG_NAME
        self._run_lock = threading.Lock()
        self._run_thread: threading.Thread | None = None
        self.status = "idle"
        self.last_error = ""

    def build_state(self) -> dict[str, Any]:
        active_config_path = self.runtime_config_path if self.runtime_config_path.exists() else self.config_path
        payload = load_yaml(active_config_path)
        base_config = load_yaml(self.config_path)
        summary = self._load_summary()
        history = load_run_history(self.runtime_dir, limit=12)
        return {
            "status": self.status,
            "last_error": self.last_error,
            "config_path": str(self.config_path),
            "active_config_path": str(active_config_path),
            "config": base_config,
            "active_config": payload,
            "market_feed_status": build_market_feed_status(payload),
            "market_feed_capabilities": build_market_feed_capabilities(),
            "controls": extract_controls(payload),
            "summary": summary,
            "history": history,
            "comparison": build_run_comparison(history),
        }

    def load_config(self) -> dict[str, Any]:
        return load_yaml(self.config_path)

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        validate_config_payload(payload)
        self.config_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        self.runtime_config_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        return self.build_state()

    def run_simulation(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Simulation is already running")
        self.status = "running"
        self.last_error = ""
        try:
            base_payload = load_yaml(self.config_path)
            merged_payload = apply_console_overrides(base_payload, overrides or {})
            self.runtime_config_path.write_text(
                yaml.safe_dump(merged_payload, sort_keys=False, allow_unicode=False),
                encoding="utf-8",
            )
            bootstrap_system(self.runtime_config_path, run_ablation=True)
            self.status = "idle"
            return self.build_state()
        except Exception as exc:
            self.status = "error"
            self.last_error = str(exc)
            raise
        finally:
            self._run_lock.release()

    def start_simulation(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            raise RuntimeError("Simulation is already running")
        self.status = "running"
        self.last_error = ""
        self._run_thread = threading.Thread(
            target=self._run_worker,
            args=(overrides or {},),
            daemon=True,
        )
        self._run_thread.start()
        return self.build_state()

    def _run_worker(self, overrides: dict[str, Any]) -> None:
        try:
            base_payload = load_yaml(self.config_path)
            merged_payload = apply_console_overrides(base_payload, overrides)
            self.runtime_config_path.write_text(
                yaml.safe_dump(merged_payload, sort_keys=False, allow_unicode=False),
                encoding="utf-8",
            )
            bootstrap_system(self.runtime_config_path, run_ablation=True)
            self.status = "idle"
        except Exception as exc:  # pragma: no cover - background error path
            self.status = "error"
            self.last_error = str(exc)
        finally:
            self._run_lock.release()

    def _load_summary(self) -> dict[str, Any] | None:
        summary_path = self.runtime_dir / SUMMARY_FILE_NAME
        if not summary_path.exists():
            return None
        return json.loads(summary_path.read_text(encoding="utf-8"))


def load_yaml(path: pathlib.Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def validate_config_payload(payload: dict[str, Any]) -> None:
    cfg = SystemConfig(**payload)
    if cfg.agents.total_ratio > 1.0:
        raise ValueError("Sum of enabled agent capital_ratio must be <= 1.0")
    ids = [agent.id for agent in cfg.agents.registry]
    if len(ids) != len(set(ids)):
        raise ValueError("Agent ids must be unique")


def build_market_feed_status(payload: dict[str, Any]) -> dict[str, Any]:
    market_cfg = payload.get("feeds", {}).get("market", {})
    feed_type = str(market_cfg.get("type", "synthetic_cn")).strip().lower()
    symbols = list(market_cfg.get("symbols", []))
    if feed_type == "synthetic_cn":
        return {
            "type": feed_type,
            "is_live": False,
            "ready": True,
            "message": "当前使用模拟行情，可用于流程验证，但不代表真实市场深度。",
            "symbols": symbols,
        }
    if feed_type == "tushare_realtime":
        token_env = str(market_cfg.get("token_env", "TUSHARE_TOKEN")).strip() or "TUSHARE_TOKEN"
        token = str(market_cfg.get("token") or os.getenv(token_env) or "").strip()
        has_pkg = importlib.util.find_spec("tushare") is not None
        fallback_provider = str(market_cfg.get("fallback_provider", "easyquotation")).strip().lower() or "easyquotation"
        has_fallback_pkg = importlib.util.find_spec("easyquotation") is not None if fallback_provider == "easyquotation" else False
        supported_symbols = _filter_market_symbols(symbols, allowed_markets={"SH", "SSE", "SZ", "SZSE"})
        unsupported_symbols = [symbol for symbol in symbols if symbol not in supported_symbols]
        direct_ready = has_pkg and bool(token) and bool(supported_symbols)
        fallback_ready = fallback_provider == "easyquotation" and has_fallback_pkg and bool(supported_symbols)
        ready = direct_ready or fallback_ready
        if direct_ready:
            message = "已具备 Tushare 实时行情运行条件。"
        elif fallback_ready:
            message = "当前缺少可用的 Tushare 直连条件，运行时将回退到 EasyQuotation。"
        else:
            message = f"缺少 {'tushare 包' if not has_pkg else 'Tushare Token'}，当前无法稳定切到真实行情。"
        return {
            "type": feed_type,
            "is_live": True,
            "ready": ready,
            "token_env": token_env,
            "has_package": has_pkg,
            "has_token": bool(token),
            "ready_mode": "direct" if direct_ready else "fallback" if fallback_ready else "unavailable",
            "supported_symbols": supported_symbols,
            "unsupported_symbols": unsupported_symbols,
            "fallback_provider": fallback_provider,
            "fallback_ready": fallback_ready,
            "message": message,
            "symbols": symbols,
        }
    if feed_type == "easyquotation_realtime":
        has_pkg = importlib.util.find_spec("easyquotation") is not None
        provider = str(market_cfg.get("provider", "sina")).strip().lower() or "sina"
        supported_symbols = _filter_market_symbols(symbols, allowed_markets={"SH", "SSE", "SZ", "SZSE"})
        unsupported_symbols = [symbol for symbol in symbols if symbol not in supported_symbols]
        ready = has_pkg and bool(supported_symbols)
        if ready and unsupported_symbols:
            message = f"EasyQuotation 可运行，但会忽略不支持的标的: {', '.join(unsupported_symbols)}"
        elif ready:
            message = "已具备 EasyQuotation 实时行情运行条件。"
        elif not has_pkg:
            message = "缺少 easyquotation 包，当前无法切到该实时行情源。"
        else:
            message = "当前标的中没有 EasyQuotation 支持的 A 股代码。"
        return {
            "type": feed_type,
            "is_live": True,
            "ready": ready,
            "provider": provider,
            "has_package": has_pkg,
            "supported_symbols": supported_symbols,
            "unsupported_symbols": unsupported_symbols,
            "message": message,
            "symbols": symbols,
        }
    if feed_type == "csv_replay":
        raw_path = str(market_cfg.get("path", "")).strip()
        path = pathlib.Path(raw_path)
        exists = path.exists()
        return {
            "type": feed_type,
            "is_live": False,
            "ready": exists,
            "path": raw_path,
            "replay_interval_seconds": float(market_cfg.get("replay_interval_seconds", 0.0) or 0.0),
            "message": "CSV 回放文件存在，可用于接近实盘节奏的复盘。" if exists else "CSV 回放文件不存在，当前无法启动该行情源。",
            "symbols": symbols,
        }
    return {
        "type": feed_type,
        "is_live": False,
        "ready": False,
        "message": f"未知行情源类型: {feed_type}",
        "symbols": symbols,
    }


def build_market_feed_capabilities() -> dict[str, Any]:
    token_env = "TUSHARE_TOKEN"
    env_token = str(os.getenv(token_env) or os.getenv("TS_TOKEN") or "").strip()
    return {
        "tushare": {
            "has_package": importlib.util.find_spec("tushare") is not None,
            "token_env": token_env,
            "has_env_token": bool(env_token),
        },
        "easyquotation": {
            "has_package": importlib.util.find_spec("easyquotation") is not None,
            "providers": ["sina", "tencent"],
        },
        "csv_replay": {
            "requires_existing_path": True,
        },
    }


def extract_controls(payload: dict[str, Any]) -> dict[str, Any]:
    risk_controls = payload.get("risk_engine", {}).get("controls", {})
    market_cfg = payload.get("feeds", {}).get("market", {})
    return {
        "loop_iterations": int(payload.get("system", {}).get("loop_iterations", 0)),
        "risk_controls": {
            key: risk_controls.get(key)
            for key in CONFIG_KEYS
        },
        "market_feed": {
            "type": market_cfg.get("type", "synthetic_cn"),
            "symbols": list(market_cfg.get("symbols", [])),
            "poll_interval_seconds": market_cfg.get("poll_interval_seconds"),
            "provider": market_cfg.get("provider"),
            "path": market_cfg.get("path"),
        },
        "agents": [
            {
                "id": agent["id"],
                "role": agent["role"],
                "capital_ratio": float(agent["capital_ratio"]),
                "enabled": bool(agent.get("enabled", True)),
            }
            for agent in payload.get("agents", {}).get("registry", [])
        ],
    }


def apply_console_overrides(
    payload: dict[str, Any],
    overrides: dict[str, Any],
) -> dict[str, Any]:
    merged = copy.deepcopy(payload)
    if not overrides:
        return merged

    system_overrides = overrides.get("system", {})
    if system_overrides:
        system_cfg = merged.setdefault("system", {})
        for key in ("mode", "market", "timezone"):
            if key in system_overrides:
                system_cfg[key] = str(system_overrides[key])
        for key in ("capital_base", "poll_interval_seconds"):
            if key in system_overrides:
                system_cfg[key] = float(system_overrides[key])
        if "loop_iterations" in system_overrides:
            system_cfg["loop_iterations"] = int(system_overrides["loop_iterations"])
        risk_budget_overrides = system_overrides.get("risk_budget", {})
        if risk_budget_overrides:
            risk_budget = system_cfg.setdefault("risk_budget", {})
            for key in ("max_drawdown", "var_limit", "exposure_limit"):
                if key in risk_budget_overrides:
                    risk_budget[key] = float(risk_budget_overrides[key])

    market_feed_overrides = overrides.get("market_feed", {})
    if market_feed_overrides:
        market_feed_cfg = merged.setdefault("feeds", {}).setdefault("market", {})
        for key in MARKET_FEED_STR_KEYS:
            if key in market_feed_overrides:
                market_feed_cfg[key] = str(market_feed_overrides[key]).strip()
        for key in MARKET_FEED_FLOAT_KEYS:
            if key in market_feed_overrides:
                market_feed_cfg[key] = float(market_feed_overrides[key])
        for key in MARKET_FEED_INT_KEYS:
            if key in market_feed_overrides:
                market_feed_cfg[key] = int(market_feed_overrides[key])
        if "symbols" in market_feed_overrides:
            market_feed_cfg["symbols"] = _normalize_string_list(market_feed_overrides["symbols"])

    risk_overrides = overrides.get("risk_controls", {})
    if risk_overrides:
        controls = merged.setdefault("risk_engine", {}).setdefault("controls", {})
        for key, value in risk_overrides.items():
            if key in RISK_CONTROL_BOOL_KEYS:
                controls[key] = bool(value)
            elif key in RISK_CONTROL_INT_KEYS:
                controls[key] = int(value)
            else:
                controls[key] = float(value)

    strategy_factory_overrides = overrides.get("strategy_factory", {})
    if strategy_factory_overrides:
        strategy_factory = merged.setdefault("strategy_factory", {})
        if "templates" in strategy_factory_overrides:
            strategy_factory["templates"] = _normalize_string_list(strategy_factory_overrides["templates"])
        autogen_overrides = strategy_factory_overrides.get("autogen", {})
        if autogen_overrides:
            autogen_cfg = strategy_factory.setdefault("autogen", {})
            if "enabled" in autogen_overrides:
                autogen_cfg["enabled"] = bool(autogen_overrides["enabled"])
            if "max_candidates" in autogen_overrides:
                autogen_cfg["max_candidates"] = int(autogen_overrides["max_candidates"])
        genetic_overrides = strategy_factory_overrides.get("genetic", {})
        if genetic_overrides:
            genetic_cfg = strategy_factory.setdefault("genetic", {})
            if "population" in genetic_overrides:
                genetic_cfg["population"] = int(genetic_overrides["population"])
            if "elitism" in genetic_overrides:
                genetic_cfg["elitism"] = float(genetic_overrides["elitism"])

    agent_overrides = {
        str(agent["id"]): agent
        for agent in overrides.get("agents", [])
        if "id" in agent
    }
    for agent in merged.get("agents", {}).get("registry", []):
        current = agent_overrides.get(str(agent["id"]))
        if not current:
            continue
        if "enabled" in current:
            agent["enabled"] = bool(current["enabled"])
        if "capital_ratio" in current:
            agent["capital_ratio"] = float(current["capital_ratio"])
        if "role" in current:
            agent["role"] = str(current["role"])

    return merged


def build_run_comparison(history: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(history) < 2:
        return None
    latest = history[0]
    previous = history[1]
    return {
        "latest_run_id": latest.get("run_id"),
        "previous_run_id": previous.get("run_id"),
        "equity_delta": _safe_delta(latest, previous, "equity", digits=2),
        "return_pct_delta": _safe_delta(latest, previous, "total_return_pct", digits=4),
        "max_drawdown_pct_delta": _safe_delta(latest, previous, "max_drawdown_pct", digits=4),
        "trade_count_delta": _safe_delta(latest, previous, "trade_count", digits=0),
        "leverage_ratio_delta": _safe_delta(latest, previous, "leverage_ratio", digits=4),
    }


def _safe_delta(
    latest: dict[str, Any],
    previous: dict[str, Any],
    key: str,
    *,
    digits: int,
) -> float | int | None:
    if key not in latest or key not in previous:
        return None
    delta = float(latest[key]) - float(previous[key])
    if digits == 0:
        return int(delta)
    return round(delta, digits)


def _normalize_string_list(values: Any) -> list[str]:
    if isinstance(values, str):
        iterable = values.split(",")
    elif isinstance(values, (list, tuple, set)):
        iterable = values
    else:
        iterable = []
    return [str(item).strip() for item in iterable if str(item).strip()]


def _filter_market_symbols(symbols: list[str], *, allowed_markets: set[str]) -> list[str]:
    filtered: list[str] = []
    for symbol in symbols:
        text = str(symbol).strip()
        if not text:
            continue
        if "." not in text:
            filtered.append(text)
            continue
        _, market = text.split(".", 1)
        if market.upper() in allowed_markets:
            filtered.append(text)
    return filtered
