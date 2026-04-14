from __future__ import annotations

import argparse
import copy
import json
import pathlib
from datetime import datetime
from typing import Iterable

import yaml

from .agents.registry import AgentRegistry
from .config import SystemConfig, load_config
from .data_layer.pipelines import DataPipeline
from .data_layer.trading_calendar import TradingCalendar
from .evolution.evaluator import EvolutionEngine
from .execution.order_router import OrderRouter
from .market.adversarial_env import MarketEnvironment
from .portfolio.brain import PortfolioBrain
from .reporting.dashboard import append_run_history, build_dashboard_summary, write_dashboard_assets
from .reporting.ops import enrich_summary_with_ops, write_ops_assets
from .risk.engine import RiskEngine
from .shared.logging import get_logger
from .strategy.factory import StrategyFactory

LOGGER = get_logger(__name__)


def bootstrap_system(
    config_path: pathlib.Path | str,
    *,
    persist_outputs: bool = True,
    append_history_enabled: bool = True,
    runtime_dir: pathlib.Path | None = None,
    run_ablation: bool = False,
) -> dict[str, object]:
    path = pathlib.Path(config_path)
    cfg = load_config(path)
    LOGGER.info("Bootstrapping system", extra={"config": str(path)})
    
    # 检查是否为交易日
    if cfg.system.mode == "realtime":
        calendar = TradingCalendar(cfg.system.market)
        if not calendar.is_trading_day():
            LOGGER.warning("Today is not a trading day, exiting...")
            return {"error": "Not a trading day"}
    
    runtime_dir = runtime_dir or (path.parent.parent / "runtime")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    should_run_ablation = run_ablation and cfg.system.mode != "realtime"
    if run_ablation and cfg.system.mode == "realtime":
        LOGGER.info("Skipping ablation in realtime mode", extra={"config": str(path)})

    data_pipeline = DataPipeline(cfg.feeds, poll_interval_seconds=cfg.system.poll_interval_seconds)
    llm_factory = StrategyFactory(cfg.strategy_factory, data_pipeline)
    agent_registry = AgentRegistry(cfg.agents, llm_factory)
    adversarial_env = MarketEnvironment(cfg.market_simulation)
    evolution_engine = EvolutionEngine(cfg.evolution, llm_factory)
    portfolio_brain = PortfolioBrain(cfg.portfolio_brain, agent_registry, cfg.system.capital_base)
    risk_engine = RiskEngine(cfg.risk_engine, cfg.execution)
    order_router = OrderRouter(cfg.execution, risk_engine, cfg.system.capital_base)

    summary = _run_event_loop(
        cfg,
        pipeline=data_pipeline,
        agents=agent_registry,
        strategy_factory=llm_factory,
        market=adversarial_env,
        evolution=evolution_engine,
        portfolio=portfolio_brain,
        risk=risk_engine,
        router=order_router,
        runtime_dir=runtime_dir,
        persist_outputs=persist_outputs,
        append_history_enabled=append_history_enabled,
    )
    if should_run_ablation and persist_outputs:
        report = _run_ablation_study(path, runtime_dir, baseline_summary=summary)
        summary["ablation_report"] = report
        write_dashboard_assets(runtime_dir, summary)
    return summary


def _run_event_loop(
    cfg: SystemConfig,
    *,
    pipeline: DataPipeline,
    agents: AgentRegistry,
    strategy_factory: StrategyFactory,
    market: MarketEnvironment,
    evolution: EvolutionEngine,
    portfolio: PortfolioBrain,
    risk: RiskEngine,
    router: OrderRouter,
    runtime_dir: pathlib.Path,
    persist_outputs: bool,
    append_history_enabled: bool,
) -> dict[str, object]:
    LOGGER.info("Starting event loop", extra={"mode": cfg.system.mode})
    ticks = pipeline.stream(max_iterations=cfg.system.loop_iterations)
    current_run_time = datetime.now()
    generated_at = current_run_time.isoformat(timespec="seconds")
    run_id = current_run_time.strftime("%Y%m%d-%H%M%S-%f")
    processed = 0
    active_agents = [
        {
            "id": spec.id,
            "role": spec.role,
            "capital_ratio": spec.capital_ratio,
        }
        for spec in cfg.agents.registry
        if spec.enabled
    ]
    agent_contribution_curves: dict[str, list[dict[str, float | int]]] = {
        agent["id"]: [
            {
                "tick": 0,
                "nav": round(float(agent["capital_ratio"]) * cfg.system.capital_base, 2),
                "net_pnl": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
            }
        ]
        for agent in active_agents
    }
    equity_curve: list[dict[str, float | int]] = [
        {"tick": 0, "equity": round(cfg.system.capital_base, 2)}
    ]
    latest_summary: dict[str, object] | None = None
    for tick in ticks:
        bundle = {
            **tick,
            "account": router.snapshot(),
        }
        signals = agents.dispatch(bundle)
        enriched = market.apply_shocks(signals)
        selected = portfolio.allocate(enriched, bundle["account"])
        risked = risk.apply(selected, account=bundle["account"])
        router.route(risked)
        account_after = router.snapshot()
        agent_weight_state = portfolio.describe_agent_weights(account_after)
        equity_curve.append(
            {
                "tick": processed + 1,
                "equity": round(float(account_after.get("equity", 0.0)), 2),
                "cash_available": round(float(account_after.get("cash_available", 0.0)), 2),
                "gross_exposure": round(float(account_after.get("gross_exposure", 0.0)), 2),
            }
        )
        agent_metrics = account_after.get("agent_metrics", {})
        for agent in active_agents:
            metrics = agent_metrics.get(agent["id"], {})
            weights = agent_weight_state.get(agent["id"], {})
            agent_contribution_curves[agent["id"]].append(
                {
                    "tick": processed + 1,
                    "nav": round(float(weights.get("nav", agent["capital_ratio"] * cfg.system.capital_base)), 2),
                    "net_pnl": round(float(metrics.get("net_pnl", 0.0)), 2),
                    "realized_pnl": round(float(metrics.get("realized_pnl", 0.0)), 2),
                    "unrealized_pnl": round(float(metrics.get("unrealized_pnl", 0.0)), 2),
                }
            )
        evolution.update(history=risked)
        strategy_factory.refresh_if_needed()
        processed += 1
        account_after["agent_weight_state"] = agent_weight_state
        if persist_outputs:
            latest_summary = _persist_runtime_outputs(
                cfg,
                runtime_dir=runtime_dir,
                run_id=run_id,
                generated_at=generated_at,
                ticks_processed=processed,
                account_snapshot=account_after,
                equity_curve=equity_curve,
                active_agents=active_agents,
                agent_contribution_curves=agent_contribution_curves,
                blotter_path=router.broker.blotter_path,
            )

    account_snapshot = router.snapshot()
    account_snapshot["agent_weight_state"] = portfolio.describe_agent_weights(account_snapshot)
    if persist_outputs:
        if latest_summary is None:
            latest_summary = _persist_runtime_outputs(
                cfg,
                runtime_dir=runtime_dir,
                run_id=run_id,
                generated_at=generated_at,
                ticks_processed=processed,
                account_snapshot=account_snapshot,
                equity_curve=equity_curve,
                active_agents=active_agents,
                agent_contribution_curves=agent_contribution_curves,
                blotter_path=router.broker.blotter_path,
            )
        dashboard_summary = latest_summary
    else:
        _, dashboard_summary = _build_runtime_outputs(
            cfg,
            run_id=run_id,
            generated_at=generated_at,
            ticks_processed=processed,
            account_snapshot=account_snapshot,
            equity_curve=equity_curve,
            active_agents=active_agents,
            agent_contribution_curves=agent_contribution_curves,
            blotter_path=router.broker.blotter_path,
        )

    if persist_outputs and append_history_enabled:
        append_run_history(runtime_dir, dashboard_summary)
    LOGGER.info("Simulation complete")
    return dashboard_summary


def _build_runtime_outputs(
    cfg: SystemConfig,
    *,
    run_id: str,
    generated_at: str,
    ticks_processed: int,
    account_snapshot: dict[str, object],
    equity_curve: list[dict[str, float | int]],
    active_agents: list[dict[str, object]],
    agent_contribution_curves: dict[str, list[dict[str, float | int]]],
    blotter_path: pathlib.Path,
) -> tuple[dict[str, object], dict[str, object]]:
    snapshot = {
        "run_id": run_id,
        "generated_at": generated_at,
        "mode": cfg.system.mode,
        "market": cfg.system.market,
        "ticks_processed": ticks_processed,
        "equity_curve": equity_curve,
        "account": account_snapshot,
    }
    dashboard_summary = build_dashboard_summary(
        run_id=run_id,
        generated_at=generated_at,
        mode=cfg.system.mode,
        market=cfg.system.market,
        ticks_processed=ticks_processed,
        account=account_snapshot,
        blotter_path=blotter_path,
        equity_curve=equity_curve,
        active_agents=active_agents,
        agent_contribution_curves=agent_contribution_curves,
        data_source={
            "market_feed_type": cfg.feeds.market.type,
            "market_symbols": list(cfg.feeds.market.payload().get("symbols", [])),
            "poll_interval_seconds": float(
                cfg.feeds.market.payload().get("poll_interval_seconds", cfg.system.poll_interval_seconds)
            ),
        },
    )
    enrich_summary_with_ops(dashboard_summary, cfg)
    return snapshot, dashboard_summary


def _persist_runtime_outputs(
    cfg: SystemConfig,
    *,
    runtime_dir: pathlib.Path,
    run_id: str,
    generated_at: str,
    ticks_processed: int,
    account_snapshot: dict[str, object],
    equity_curve: list[dict[str, float | int]],
    active_agents: list[dict[str, object]],
    agent_contribution_curves: dict[str, list[dict[str, float | int]]],
    blotter_path: pathlib.Path,
) -> dict[str, object]:
    snapshot, dashboard_summary = _build_runtime_outputs(
        cfg,
        run_id=run_id,
        generated_at=generated_at,
        ticks_processed=ticks_processed,
        account_snapshot=account_snapshot,
        equity_curve=equity_curve,
        active_agents=active_agents,
        agent_contribution_curves=agent_contribution_curves,
        blotter_path=blotter_path,
    )
    snapshot_path = runtime_dir / "account_snapshot.json"
    snapshot_path.write_text(
        json.dumps(snapshot, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    write_dashboard_assets(runtime_dir, dashboard_summary)
    write_ops_assets(runtime_dir, dashboard_summary)
    return dashboard_summary


def _run_ablation_study(
    config_path: pathlib.Path,
    runtime_dir: pathlib.Path,
    *,
    baseline_summary: dict[str, object],
) -> dict[str, object]:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    agents = [agent for agent in payload.get("agents", {}).get("registry", []) if agent.get("enabled", True)]
    scenarios = []
    ablation_root = runtime_dir / "ablation"
    ablation_root.mkdir(parents=True, exist_ok=True)

    baseline_perf = baseline_summary.get("performance", {})
    baseline_attr = baseline_summary.get("agent_attribution", {})
    baseline_return = float(baseline_perf.get("total_return_pct", 0.0))
    baseline_drawdown = float(baseline_perf.get("max_drawdown_pct", 0.0))
    baseline_trades = int(baseline_summary.get("kpis", {}).get("trade_count", 0))

    for agent in agents:
        scenario_payload = copy.deepcopy(payload)
        for candidate in scenario_payload.get("agents", {}).get("registry", []):
            if candidate.get("id") == agent.get("id"):
                candidate["enabled"] = False
        scenario_dir = ablation_root / str(agent.get("id"))
        scenario_dir.mkdir(parents=True, exist_ok=True)
        scenario_payload.setdefault("execution", {})["blotter_path"] = str(
            (scenario_dir / "blotter.jsonl").resolve()
        )
        scenario_config_path = scenario_dir / "config.yaml"
        scenario_config_path.write_text(
            yaml.safe_dump(scenario_payload, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        summary = bootstrap_system(
            scenario_config_path,
            persist_outputs=False,
            append_history_enabled=False,
            runtime_dir=scenario_dir,
            run_ablation=False,
        )
        performance = summary.get("performance", {})
        attribution = summary.get("agent_attribution", {})
        scenarios.append(
            {
                "disabled_agent_id": agent.get("id"),
                "disabled_role": agent.get("role"),
                "total_return_pct": round(float(performance.get("total_return_pct", 0.0)), 4),
                "return_pct_delta": round(float(performance.get("total_return_pct", 0.0)) - baseline_return, 4),
                "max_drawdown_pct": round(float(performance.get("max_drawdown_pct", 0.0)), 4),
                "max_drawdown_pct_delta": round(float(performance.get("max_drawdown_pct", 0.0)) - baseline_drawdown, 4),
                "trade_count": int(summary.get("kpis", {}).get("trade_count", 0)),
                "trade_count_delta": int(summary.get("kpis", {}).get("trade_count", 0)) - baseline_trades,
                "top_winner_after_disable": attribution.get("top_winner", {}).get("agent_id"),
                "top_loser_after_disable": attribution.get("top_loser", {}).get("agent_id"),
            }
        )

    scenarios.sort(key=lambda item: (float(item["return_pct_delta"]), -float(item["max_drawdown_pct_delta"])), reverse=True)
    report = {
        "baseline": {
            "run_id": baseline_summary.get("run_id"),
            "total_return_pct": round(baseline_return, 4),
            "max_drawdown_pct": round(baseline_drawdown, 4),
            "trade_count": baseline_trades,
            "top_winner": baseline_attr.get("top_winner", {}).get("agent_id"),
            "top_loser": baseline_attr.get("top_loser", {}).get("agent_id"),
        },
        "best_disable_candidate": scenarios[0] if scenarios else None,
        "scenarios": scenarios,
    }
    report_path = runtime_dir / "ablation_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")
    return report


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Multi-agent quant system")
    parser.add_argument("--config", required=True, help="Path to YAML config")
    args = parser.parse_args(list(argv) if argv is not None else None)
    bootstrap_system(args.config, run_ablation=False)


if __name__ == "__main__":
    main()
