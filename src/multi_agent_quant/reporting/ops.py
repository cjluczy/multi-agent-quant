from __future__ import annotations

from datetime import datetime, time
import json
import pathlib
from typing import Any
from zoneinfo import ZoneInfo

from ..config import SystemConfig


def enrich_summary_with_ops(summary: dict[str, Any], cfg: SystemConfig) -> dict[str, Any]:
    alerts = build_runtime_alerts(summary, cfg)
    summary["alerts"] = alerts
    summary["ops_report"] = build_ops_report(summary, alerts)
    return summary


def write_ops_assets(runtime_dir: pathlib.Path, summary: dict[str, Any]) -> None:
    alerts_path = runtime_dir / "alerts.json"
    report_path = runtime_dir / "ops_report.md"
    alerts_path.write_text(json.dumps(summary.get("alerts", []), indent=2, ensure_ascii=True), encoding="utf-8")
    report_path.write_text(str(summary.get("ops_report", "")), encoding="utf-8")


def build_runtime_alerts(summary: dict[str, Any], cfg: SystemConfig) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    risk_budget = cfg.system.risk_budget
    kpis = summary.get("kpis", {})
    performance = summary.get("performance", {})
    risk_events = summary.get("risk_events", {})
    data_source = summary.get("data_source", {})
    ranking = summary.get("agent_attribution", {}).get("ranking", [])

    forced_count = int(risk_events.get("forced_liquidation_count", 0))
    if forced_count > 0:
        alerts.append(
            _alert(
                severity="critical",
                code="FORCED_LIQUIDATION",
                message=f"发生强平 {forced_count} 次，说明风险控制已被动介入。",
            )
        )

    leverage_ratio = float(kpis.get("leverage_ratio", 0.0))
    gross_limit = float(cfg.risk_engine.controls.get("max_gross_exposure_pct", 1.0))
    if gross_limit > 0 and leverage_ratio >= gross_limit * 0.9:
        alerts.append(
            _alert(
                severity="warning",
                code="HIGH_LEVERAGE",
                message=f"当前杠杆率 {leverage_ratio:.4f} 已接近总敞口上限 {gross_limit:.4f}。",
            )
        )

    max_drawdown_pct = float(performance.get("max_drawdown_pct", 0.0))
    drawdown_limit_pct = float(risk_budget.max_drawdown) * 100.0
    if drawdown_limit_pct > 0 and max_drawdown_pct >= drawdown_limit_pct:
        alerts.append(
            _alert(
                severity="critical",
                code="DRAWDOWN_LIMIT_BREACH",
                message=f"最大回撤 {max_drawdown_pct:.2f}% 已超过预算上限 {drawdown_limit_pct:.2f}%。",
            )
        )
    elif drawdown_limit_pct > 0 and max_drawdown_pct >= drawdown_limit_pct * 0.8:
        alerts.append(
            _alert(
                severity="warning",
                code="DRAWDOWN_NEAR_LIMIT",
                message=f"最大回撤 {max_drawdown_pct:.2f}% 已达到预算上限的 80%。",
            )
        )

    for row in ranking:
        deweight = float(row.get("deweight_multiplier", 1.0))
        if deweight < 0.9999:
            alerts.append(
                _alert(
                    severity="warning",
                    code="AGENT_DEWEIGHTED",
                    message=(
                        f"智能体 {row.get('agent_id')} 已被自动降权到 {deweight:.4f}，"
                        f"当前收益率 {float(row.get('return_pct', 0.0)):.2f}%。"
                    ),
                    agent_id=str(row.get("agent_id", "")),
                )
            )

    if summary.get("mode") == "realtime":
        alerts.append(
            _alert(
                severity="info",
                code="REALTIME_MODE",
                message=(
                    f"系统当前运行于实时模式，数据源 {data_source.get('market_feed_type', '-')}, "
                    f"symbols={data_source.get('market_symbols', [])}。"
                ),
            )
        )
        market_hours_alert = _build_market_hours_alert(summary, cfg)
        if market_hours_alert is not None:
            alerts.append(market_hours_alert)

    if not alerts:
        alerts.append(
            _alert(
                severity="info",
                code="SYSTEM_HEALTHY",
                message="当前未发现强平、回撤越界或降权告警。",
            )
        )
    return alerts


def build_ops_report(summary: dict[str, Any], alerts: list[dict[str, Any]]) -> str:
    kpis = summary.get("kpis", {})
    performance = summary.get("performance", {})
    winner = summary.get("agent_attribution", {}).get("top_winner") or {}
    loser = summary.get("agent_attribution", {}).get("top_loser") or {}
    data_source = summary.get("data_source", {})

    lines = [
        "# 运行摘要",
        "",
        f"- 运行 ID: {summary.get('run_id', '-')}",
        f"- 生成时间: {summary.get('generated_at', '-')}",
        f"- 模式: {summary.get('mode', '-')}",
        f"- 市场: {summary.get('market', '-')}",
        f"- 数据源: {data_source.get('market_feed_type', '-')}",
        f"- Symbols: {data_source.get('market_symbols', [])}",
        "",
        "## 组合概况",
        f"- 总权益: {kpis.get('equity', 0.0)}",
        f"- 收益率: {performance.get('total_return_pct', 0.0)}%",
        f"- 最大回撤: {performance.get('max_drawdown_pct', 0.0)}%",
        f"- 杠杆率: {kpis.get('leverage_ratio', 0.0)}",
        f"- 成交笔数: {kpis.get('trade_count', 0)}",
        "",
        "## 智能体概况",
        f"- 当前最优: {winner.get('agent_id', '-')} ({winner.get('net_pnl', 0.0)})",
        f"- 当前最差: {loser.get('agent_id', '-')} ({loser.get('net_pnl', 0.0)})",
        "",
        "## 告警",
    ]
    for alert in alerts:
        lines.append(f"- [{alert.get('severity', 'info')}] {alert.get('code', '-')}: {alert.get('message', '')}")
    return "\n".join(lines) + "\n"


def _alert(*, severity: str, code: str, message: str, agent_id: str | None = None) -> dict[str, Any]:
    payload = {
        "severity": severity,
        "code": code,
        "message": message,
    }
    if agent_id:
        payload["agent_id"] = agent_id
    return payload


def _build_market_hours_alert(summary: dict[str, Any], cfg: SystemConfig) -> dict[str, Any] | None:
    if str(summary.get("market", "")).lower() != "cn":
        return None

    generated_at = str(summary.get("generated_at", "")).strip()
    if not generated_at:
        return None

    try:
        tz = ZoneInfo(cfg.system.timezone)
        timestamp = datetime.fromisoformat(generated_at)
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=tz)
        else:
            timestamp = timestamp.astimezone(tz)
    except Exception:
        return None

    is_weekday = timestamp.weekday() < 5
    current = timestamp.time()
    in_morning = time(9, 30) <= current < time(11, 30)
    in_afternoon = time(13, 0) <= current < time(15, 0)
    if is_weekday and (in_morning or in_afternoon):
        return None

    return _alert(
        severity="warning",
        code="OUTSIDE_MARKET_HOURS",
        message=(
            f"当前时间 {timestamp.strftime('%Y-%m-%d %H:%M:%S %Z')} 不在 A 股连续竞价时段 "
            "(09:30-11:30, 13:00-15:00)，实时行情可能静态，收益/回撤验证参考价值有限。"
        ),
    )
