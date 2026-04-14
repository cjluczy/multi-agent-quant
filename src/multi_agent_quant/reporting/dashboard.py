from __future__ import annotations

import json
import pathlib
from html import escape
from typing import Any

RUN_HISTORY_FILE_NAME = "run_history.jsonl"


def build_dashboard_summary(
    *,
    run_id: str,
    generated_at: str,
    mode: str,
    market: str,
    ticks_processed: int,
    account: dict[str, Any],
    blotter_path: pathlib.Path,
    equity_curve: list[dict[str, Any]],
    active_agents: list[dict[str, Any]] | None = None,
    agent_contribution_curves: dict[str, list[dict[str, Any]]] | None = None,
    data_source: dict[str, Any] | None = None,
    recent_fill_limit: int = 12,
) -> dict[str, Any]:
    all_fills = _load_fills(blotter_path)
    recent_fills = list(reversed(all_fills[-recent_fill_limit:]))
    forced_fills = [
        fill
        for fill in all_fills
        if fill.get("initiator_id") == "risk-engine" or fill.get("agent_id") == "risk-engine"
    ]
    recent_forced_fills = list(reversed(forced_fills[-recent_fill_limit:]))
    performance = _build_performance_metrics(account, equity_curve, all_fills)
    execution_breakdown = _build_execution_breakdown(all_fills)
    agent_attribution = _build_agent_attribution(account, active_agents or [])

    stock_positions = []
    for symbol, detail in sorted(account.get("stock_position_detail", {}).items()):
        stock_positions.append(
            {
                "symbol": symbol,
                "quantity": int(detail.get("quantity", 0)),
                "avg_price": round(float(detail.get("avg_price", 0.0)), 2),
                "last_price": round(float(detail.get("last_price", 0.0)), 2),
                "market_value": round(float(detail.get("market_value", 0.0)), 2),
                "unrealized_pnl": round(float(detail.get("unrealized_pnl", 0.0)), 2),
            }
        )

    futures_positions = []
    for symbol, detail in sorted(account.get("futures_positions", {}).items()):
        futures_positions.append(
            {
                "symbol": symbol,
                "long_qty": int(detail.get("long_qty", 0)),
                "short_qty": int(detail.get("short_qty", 0)),
                "last_price": round(float(detail.get("last_price", 0.0)), 2),
                "unrealized_pnl": round(float(detail.get("unrealized_pnl", 0.0)), 2),
            }
        )

    return {
        "run_id": run_id,
        "generated_at": generated_at,
        "mode": mode,
        "market": market,
        "ticks_processed": ticks_processed,
        "kpis": {
            "equity": round(float(account.get("equity", 0.0)), 2),
            "cash_available": round(float(account.get("cash_available", 0.0)), 2),
            "stock_market_value": round(float(account.get("stock_market_value", 0.0)), 2),
            "stock_unrealized_pnl": round(float(account.get("stock_unrealized_pnl", 0.0)), 2),
            "futures_margin_in_use": round(float(account.get("futures_margin_in_use", 0.0)), 2),
            "futures_notional_exposure": round(float(account.get("futures_notional_exposure", 0.0)), 2),
            "gross_exposure": round(float(account.get("gross_exposure", 0.0)), 2),
            "leverage_ratio": round(float(account.get("leverage_ratio", 0.0)), 4),
            "realized_pnl": round(float(account.get("realized_pnl", 0.0)), 2),
            "futures_unrealized_pnl": round(float(account.get("futures_unrealized_pnl", 0.0)), 2),
            "unrealized_pnl_total": round(
                float(account.get("stock_unrealized_pnl", 0.0)) + float(account.get("futures_unrealized_pnl", 0.0)),
                2,
            ),
            "total_fees": round(float(account.get("total_fees", 0.0)), 2),
            "trade_count": int(account.get("trade_count", 0)),
        },
        "positions": {
            "stocks": stock_positions,
            "futures": futures_positions,
        },
        "recent_fills": recent_fills,
        "risk_events": {
            "forced_liquidation_count": len(forced_fills),
            "recent_forced_liquidations": recent_forced_fills,
        },
        "performance": performance,
        "execution_breakdown": execution_breakdown,
        "agent_attribution": agent_attribution,
        "agent_weight_state": account.get("agent_weight_state", {}),
        "agent_metrics": account.get("agent_metrics", {}),
        "agent_contribution_curves": agent_contribution_curves or {},
        "equity_curve": equity_curve,
        "active_agents": active_agents or [],
        "data_source": data_source or {},
        "account": account,
    }


def write_dashboard_assets(runtime_dir: pathlib.Path, summary: dict[str, Any]) -> None:
    summary_path = runtime_dir / "dashboard_summary.json"
    html_path = runtime_dir / "dashboard.html"
    equity_curve_path = runtime_dir / "equity_curve.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")
    equity_curve_path.write_text(
        json.dumps(summary.get("equity_curve", []), indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    html_path.write_text(_render_dashboard_html(summary), encoding="utf-8")


def append_run_history(runtime_dir: pathlib.Path, summary: dict[str, Any]) -> None:
    history_path = runtime_dir / RUN_HISTORY_FILE_NAME
    entry = {
        "run_id": summary.get("run_id"),
        "generated_at": summary.get("generated_at"),
        "mode": summary.get("mode"),
        "market": summary.get("market"),
        "ticks_processed": summary.get("ticks_processed"),
        "equity": summary.get("kpis", {}).get("equity", 0.0),
        "total_return_pct": summary.get("performance", {}).get("total_return_pct", 0.0),
        "max_drawdown_pct": summary.get("performance", {}).get("max_drawdown_pct", 0.0),
        "realized_pnl": summary.get("kpis", {}).get("realized_pnl", 0.0),
        "futures_unrealized_pnl": summary.get("kpis", {}).get("futures_unrealized_pnl", 0.0),
        "gross_exposure": summary.get("kpis", {}).get("gross_exposure", 0.0),
        "leverage_ratio": summary.get("kpis", {}).get("leverage_ratio", 0.0),
        "trade_count": summary.get("kpis", {}).get("trade_count", 0),
        "forced_liquidation_count": summary.get("risk_events", {}).get("forced_liquidation_count", 0),
        "active_agents": [agent.get("id") for agent in summary.get("active_agents", [])],
    }
    with history_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True) + "\n")


def load_run_history(runtime_dir: pathlib.Path, limit: int = 10) -> list[dict[str, Any]]:
    history_path = runtime_dir / RUN_HISTORY_FILE_NAME
    if not history_path.exists():
        return []
    rows = []
    for raw_line in history_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    rows = rows[-limit:]
    rows.reverse()
    return rows


def _load_fills(blotter_path: pathlib.Path) -> list[dict[str, Any]]:
    if not blotter_path.exists():
        return []
    fills: list[dict[str, Any]] = []
    for raw_line in blotter_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        fills.append(json.loads(line))
    return fills


def _render_dashboard_html(summary: dict[str, Any]) -> str:
    kpis = summary["kpis"]
    performance = summary.get("performance", {})
    agent_attribution = summary.get("agent_attribution", {})
    ranking = agent_attribution.get("ranking", [])
    curve_svg = _equity_curve_svg(summary.get("equity_curve", []))
    agent_curve_svg = _agent_nav_curve_svg(summary.get("agent_contribution_curves", {}), ranking)
    ablation_html = _render_ablation_section(summary.get("ablation_report"))
    alerts_html = _render_alerts_section(summary.get("alerts", []))
    agent_rows = _table_rows(
        [
            {
                **row,
                "role": _translate_role(str(row.get("role", ""))),
                "effect_summary": _format_effect_breakdown(row.get("effect_breakdown", {})),
            }
            for row in ranking
        ],
        [
            "rank",
            "agent_id",
            "role",
            "nav",
            "return_pct",
            "deweight_multiplier",
            "effective_capital_ratio",
            "net_pnl",
            "realized_pnl",
            "unrealized_pnl",
            "fees",
            "trade_count",
            "total_notional",
            "notional_share_pct",
            "effect_summary",
        ],
    )
    stock_rows = _table_rows(
        summary["positions"]["stocks"],
        ["symbol", "quantity", "avg_price", "last_price", "market_value", "unrealized_pnl"],
    )
    futures_rows = _table_rows(
        summary["positions"]["futures"],
        ["symbol", "long_qty", "short_qty", "last_price", "unrealized_pnl"],
    )
    fill_rows = _table_rows(
        summary["recent_fills"],
        ["symbol", "effect", "quantity", "price", "notional", "agent_id"],
    )
    forced_rows = _table_rows(
        summary["risk_events"]["recent_forced_liquidations"],
        ["symbol", "effect", "quantity", "price", "notional", "agent_id"],
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>????????</title>
  <style>
    body {{
      margin: 0;
      font-family: Arial, sans-serif;
      background: #0b1020;
      color: #e5e7eb;
    }}
    .page {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 20px;
    }}
    .card {{
      background: #121a2f;
      border: 1px solid #24314d;
      border-radius: 16px;
      padding: 16px;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.18);
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-bottom: 20px;
    }}
    .two-col {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      margin-bottom: 20px;
    }}
    .metric-label {{
      color: #94a3b8;
      font-size: 13px;
      margin-bottom: 6px;
    }}
    .metric-value {{
      font-size: 24px;
      font-weight: 700;
    }}
    .section {{
      margin-bottom: 20px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
    }}
    th, td {{
      padding: 10px 8px;
      border-bottom: 1px solid #24314d;
      text-align: left;
      font-size: 14px;
    }}
    th {{
      color: #93c5fd;
      font-weight: 600;
    }}
    .empty {{
      color: #94a3b8;
      padding: 8px 0 0;
    }}
    .muted {{
      color: #94a3b8;
      font-size: 14px;
    }}
    .chart {{
      width: 100%;
      height: 240px;
      background: #0f172a;
      border: 1px solid #24314d;
      border-radius: 12px;
      padding: 8px;
      box-sizing: border-box;
    }}
    @media (max-width: 900px) {{
      .two-col {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <div>
        <h1>????????</h1>
        <div class="muted">?? ID?{escape(str(summary["run_id"]))} | ???{escape(_translate_mode(summary["mode"]))} | ???{escape(_translate_market(summary["market"]))} | Tick ??{summary["ticks_processed"]}</div>
        <div class="muted">?????{escape(str(summary["generated_at"]))}</div>
      </div>
      <div class="card">
        <div class="metric-label">????</div>
        <div class="metric-value">{summary["risk_events"]["forced_liquidation_count"]}</div>
      </div>
    </div>

    <div class="grid">
      {_metric_card("???", kpis["equity"])}
      {_metric_card("????", kpis["cash_available"])}
      {_metric_card("????", kpis["stock_market_value"])}
      {_metric_card("?????", kpis["futures_margin_in_use"])}
      {_metric_card("???", kpis["gross_exposure"])}
      {_metric_card("???", kpis["leverage_ratio"])}
      {_metric_card("?????", kpis["realized_pnl"])}
      {_metric_card("??????", kpis["unrealized_pnl_total"])}
      {_metric_card("???", kpis["total_fees"])}
      {_metric_card("????", kpis["trade_count"])}
    </div>

    <div class="grid">
      {_metric_card("???? %", performance.get("total_return_pct", 0.0))}
      {_metric_card("???? %", performance.get("max_drawdown_pct", 0.0))}
      {_metric_card("??? %", performance.get("volatility_pct", 0.0))}
      {_metric_card("?????", performance.get("avg_trade_notional", 0.0))}
      {_metric_card("???", performance.get("turnover_ratio", 0.0))}
      {_metric_card("????", performance.get("pnl_per_trade", 0.0))}
    </div>

    <div class="grid">
      {_leader_card("???????", agent_attribution.get("top_winner"))}
      {_leader_card("????????", agent_attribution.get("top_loser"))}
    </div>

    {alerts_html}

    <div class="two-col">
      <div class="section card">
        <h2>????</h2>
        <div class="chart">{curve_svg}</div>
      </div>
      <div class="section card">
        <h2>??? NAV ??</h2>
        <div class="chart">{agent_curve_svg}</div>
      </div>
    </div>

    <div class="section card">
      <h2>???????</h2>
      {_table_or_empty(
          agent_rows,
          [
              "??",
              "???",
              "??",
              "NAV",
              "??? %",
              "????",
              "??????",
              "???",
              "?????",
              "?????",
              "???",
              "????",
              "???",
              "???? %",
              "????",
          ],
      )}
    </div>

    {ablation_html}

    <div class="two-col">
      <div class="section card">
        <h2>????</h2>
        {_table_or_empty(stock_rows, ["??", "??", "????", "???", "??", "?????"])}
      </div>
      <div class="section card">
        <h2>????</h2>
        {_table_or_empty(futures_rows, ["??", "??", "??", "???", "?????"])}
      </div>
    </div>

    <div class="two-col">
      <div class="section card">
        <h2>????</h2>
        {_table_or_empty(fill_rows, ["??", "??", "??", "??", "????", "???"])}
      </div>
      <div class="section card">
        <h2>????</h2>
        {_table_or_empty(forced_rows, ["??", "??", "??", "??", "????", "???"])}
      </div>
    </div>
  </div>
</body>
</html>
"""


def _render_ablation_section(report: dict[str, Any] | None) -> str:
    if not report:
        return ""
    baseline = report.get("baseline", {})
    best = report.get("best_disable_candidate")
    rows = _table_rows(
        report.get("scenarios", []),
        [
            "disabled_agent_id",
            "disabled_role",
            "total_return_pct",
            "return_pct_delta",
            "max_drawdown_pct",
            "max_drawdown_pct_delta",
            "trade_count",
            "trade_count_delta",
            "top_winner_after_disable",
            "top_loser_after_disable",
        ],
    )
    best_html = ""
    if best:
        best_html = (
            f'<div class="muted">???????{escape(str(best.get("disabled_agent_id", "-")))} '
            f'| ??????{escape(_format_signed_number(best.get("return_pct_delta", 0.0)))} '
            f'| ?????{escape(_format_signed_number(best.get("max_drawdown_pct_delta", 0.0)))} '
            f'| ???????{escape(_format_signed_number(best.get("trade_count_delta", 0)))}</div>'
        )
    return (
        '<div class="section card">'
        '<h2>Ablation ??</h2>'
        f'<div class="muted">??????{escape(_format_number(baseline.get("total_return_pct", 0.0)))}% | '
        f'???????{escape(_format_number(baseline.get("max_drawdown_pct", 0.0)))}% | '
        f'???????{escape(_format_number(baseline.get("trade_count", 0)))}</div>'
        f'{best_html}'
        + _table_or_empty(
            rows,
            [
                "?????",
                "??",
                "??? %",
                "?????",
                "???? %",
                "????",
                "????",
                "??????",
                "?????",
                "?????",
            ],
        )
        + '</div>'
    )


def _render_alerts_section(alerts: list[dict[str, Any]]) -> str:
    if not alerts:
        return ""
    rows = _table_rows(alerts, ["severity", "code", "agent_id", "message"])
    return (
        '<div class="section card">'
        '<h2>运行告警</h2>'
        + _table_or_empty(rows, ["级别", "代码", "智能体", "说明"])
        + '</div>'
    )


def _metric_card(label: str, value: float | int) -> str:
    return (
        '<div class="card">'
        f'<div class="metric-label">{escape(label)}</div>'
        f'<div class="metric-value">{escape(_format_number(value))}</div>'
        '</div>'
    )


def _leader_card(title: str, leader: dict[str, Any] | None) -> str:
    if not leader:
        return (
            '<div class="card">'
            f'<div class="metric-label">{escape(title)}</div>'
            '<div class="metric-value">????</div>'
            '</div>'
        )
    return (
        '<div class="card">'
        f'<div class="metric-label">{escape(title)}</div>'
        f'<div class="metric-value">{escape(str(leader.get("agent_id", "-")))}</div>'
        f'<div class="muted">???{escape(_translate_role(str(leader.get("role", ""))))}</div>'
        f'<div class="muted">????{escape(_format_signed_number(leader.get("net_pnl", 0.0)))}</div>'
        f'<div class="muted">NAV?{escape(_format_number(leader.get("nav", 0.0)))}</div>'
        f'<div class="muted">?????{escape(_format_number(leader.get("deweight_multiplier", 1.0)))}</div>'
        '</div>'
    )


def _format_number(value: float | int) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    return f"{float(value):,.2f}"


def _format_signed_number(value: float | int) -> str:
    numeric = float(value)
    rendered = _format_number(numeric)
    if numeric > 0:
        return f"+{rendered}"
    return rendered


def _table_rows(rows: list[dict[str, Any]], keys: list[str]) -> str:
    rendered = []
    for row in rows:
        cells = ''.join(f'<td>{escape(_format_cell(row.get(key)))}</td>' for key in keys)
        rendered.append(f'<tr>{cells}</tr>')
    return ''.join(rendered)


def _table_or_empty(body: str, headers: list[str]) -> str:
    if not body:
        return '<div class="empty">?????</div>'
    header_html = ''.join(f'<th>{escape(header)}</th>' for header in headers)
    return f'<table><thead><tr>{header_html}</tr></thead><tbody>{body}</tbody></table>'


def _format_cell(value: Any) -> str:
    if isinstance(value, str):
        value = _translate_effect(value)
        value = _translate_mode(value)
        value = _translate_market(value)
        value = _translate_role(value)
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def _translate_effect(value: str) -> str:
    mapping = {
        "buy_stock": "????",
        "sell_stock": "????",
        "open_long": "??",
        "close_long": "??",
        "open_short": "??",
        "close_short": "??",
    }
    return mapping.get(value, value)


def _translate_mode(value: str) -> str:
    mapping = {
        "simulation": "???",
    }
    return mapping.get(value, value)


def _translate_market(value: str) -> str:
    mapping = {
        "cn": "????",
    }
    return mapping.get(value, value)


def _translate_role(value: str) -> str:
    mapping = {
        "news_event": "????",
        "reactive": "????",
        "swing": "????",
        "futures_hedge": "????",
        "risk_engine": "????",
    }
    return mapping.get(value, value)


def _format_effect_breakdown(value: dict[str, Any]) -> str:
    if not value:
        return "-"
    parts = []
    for effect, count in sorted(value.items()):
        parts.append(f"{_translate_effect(str(effect))} x{int(count)}")
    return " / ".join(parts)


def _build_performance_metrics(
    account: dict[str, Any],
    equity_curve: list[dict[str, Any]],
    fills: list[dict[str, Any]],
) -> dict[str, float]:
    start_equity = float(equity_curve[0].get("equity", 0.0)) if equity_curve else float(account.get("equity", 0.0))
    end_equity = float(account.get("equity", start_equity))
    total_return_pct = ((end_equity - start_equity) / start_equity * 100) if start_equity > 0 else 0.0

    peak_equity = start_equity
    max_drawdown_pct = 0.0
    returns: list[float] = []
    previous_equity = None
    for point in equity_curve:
        equity = float(point.get("equity", 0.0))
        if equity > peak_equity:
            peak_equity = equity
        if peak_equity > 0:
            drawdown_pct = (peak_equity - equity) / peak_equity * 100
            max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
        if previous_equity and previous_equity > 0:
            returns.append((equity - previous_equity) / previous_equity)
        previous_equity = equity

    avg_return = sum(returns) / len(returns) if returns else 0.0
    variance = (
        sum((period_return - avg_return) ** 2 for period_return in returns) / len(returns)
        if returns
        else 0.0
    )
    volatility_pct = variance ** 0.5 * 100
    total_notional = sum(float(fill.get("notional", 0.0)) for fill in fills)
    trade_count = max(int(account.get("trade_count", 0)), 0)
    avg_trade_notional = total_notional / len(fills) if fills else 0.0
    turnover_ratio = total_notional / start_equity if start_equity > 0 else 0.0
    total_pnl = (
        float(account.get("realized_pnl", 0.0))
        + float(account.get("stock_unrealized_pnl", 0.0))
        + float(account.get("futures_unrealized_pnl", 0.0))
    )
    pnl_per_trade = total_pnl / trade_count if trade_count > 0 else 0.0

    return {
        "start_equity": round(start_equity, 2),
        "end_equity": round(end_equity, 2),
        "total_return_pct": round(total_return_pct, 4),
        "max_drawdown_pct": round(max_drawdown_pct, 4),
        "volatility_pct": round(volatility_pct, 4),
        "avg_trade_notional": round(avg_trade_notional, 2),
        "turnover_ratio": round(turnover_ratio, 4),
        "pnl_per_trade": round(pnl_per_trade, 2),
    }


def _build_execution_breakdown(fills: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for fill in fills:
        effect = str(fill.get("effect", "unknown"))
        counts[effect] = counts.get(effect, 0) + 1
    return counts


def _build_agent_attribution(
    account: dict[str, Any],
    active_agents: list[dict[str, Any]],
) -> dict[str, Any]:
    role_by_agent = {
        str(agent.get("id")): str(agent.get("role", ""))
        for agent in active_agents
        if agent.get("id")
    }
    ratio_by_agent = {
        str(agent.get("id")): float(agent.get("capital_ratio", 0.0))
        for agent in active_agents
        if agent.get("id")
    }
    account_metrics = account.get("agent_metrics", {})
    weight_state = account.get("agent_weight_state", {})
    rows: dict[str, dict[str, Any]] = {
        agent_id: {
            "agent_id": agent_id,
            "role": role,
            "capital_ratio": ratio_by_agent.get(agent_id, 0.0),
            "trade_count": 0,
            "total_notional": 0.0,
            "fees": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "net_pnl": 0.0,
            "notional_share_pct": 0.0,
            "initial_capital": float(weight_state.get(agent_id, {}).get("initial_capital", 0.0)),
            "nav": float(weight_state.get(agent_id, {}).get("nav", 0.0)),
            "return_pct": float(weight_state.get(agent_id, {}).get("return_pct", 0.0)),
            "deweight_multiplier": float(weight_state.get(agent_id, {}).get("deweight_multiplier", 1.0)),
            "effective_capital_ratio": float(
                weight_state.get(agent_id, {}).get("effective_capital_ratio", ratio_by_agent.get(agent_id, 0.0))
            ),
            "effect_breakdown": {},
        }
        for agent_id, role in role_by_agent.items()
    }

    total_notional = 0.0
    total_fees = 0.0
    total_realized_pnl = 0.0
    total_unrealized_pnl = 0.0
    total_trade_count = 0

    for agent_id, metrics in account_metrics.items():
        agent_id = str(agent_id)
        role = role_by_agent.get(agent_id, "risk_engine" if agent_id == "risk-engine" else "")
        state = weight_state.get(agent_id, {})
        row = rows.setdefault(
            agent_id,
            {
                "agent_id": agent_id,
                "role": role,
                "capital_ratio": ratio_by_agent.get(agent_id, 0.0),
                "trade_count": 0,
                "total_notional": 0.0,
                "fees": 0.0,
                "realized_pnl": 0.0,
                "unrealized_pnl": 0.0,
                "net_pnl": 0.0,
                "notional_share_pct": 0.0,
                "initial_capital": 0.0,
                "nav": 0.0,
                "return_pct": 0.0,
                "deweight_multiplier": 1.0,
                "effective_capital_ratio": ratio_by_agent.get(agent_id, 0.0),
                "effect_breakdown": {},
            },
        )
        row["trade_count"] = int(metrics.get("trade_count", 0))
        row["total_notional"] = float(metrics.get("total_notional", 0.0))
        row["fees"] = float(metrics.get("fees", 0.0))
        row["realized_pnl"] = float(metrics.get("realized_pnl", 0.0))
        row["unrealized_pnl"] = float(metrics.get("unrealized_pnl", 0.0))
        row["net_pnl"] = float(metrics.get("net_pnl", 0.0))
        row["effect_breakdown"] = dict(metrics.get("effect_breakdown", {}))
        row["initial_capital"] = float(state.get("initial_capital", 0.0))
        row["nav"] = float(state.get("nav", 0.0))
        row["return_pct"] = float(state.get("return_pct", 0.0))
        row["deweight_multiplier"] = float(state.get("deweight_multiplier", 1.0))
        row["effective_capital_ratio"] = float(
            state.get("effective_capital_ratio", row.get("capital_ratio", 0.0))
        )

        total_notional += row["total_notional"]
        total_fees += row["fees"]
        total_realized_pnl += row["realized_pnl"]
        total_unrealized_pnl += row["unrealized_pnl"]
        total_trade_count += row["trade_count"]

    ranking = sorted(
        rows.values(),
        key=lambda item: (
            float(item.get("net_pnl", 0.0)),
            float(item.get("realized_pnl", 0.0)),
            float(item.get("unrealized_pnl", 0.0)),
            float(item.get("nav", 0.0)),
            float(item.get("total_notional", 0.0)),
        ),
        reverse=True,
    )

    for rank, row in enumerate(ranking, start=1):
        row["rank"] = rank
        row["total_notional"] = round(float(row["total_notional"]), 2)
        row["fees"] = round(float(row["fees"]), 2)
        row["realized_pnl"] = round(float(row["realized_pnl"]), 2)
        row["unrealized_pnl"] = round(float(row["unrealized_pnl"]), 2)
        row["net_pnl"] = round(float(row["net_pnl"]), 2)
        row["initial_capital"] = round(float(row["initial_capital"]), 2)
        row["nav"] = round(float(row["nav"]), 2)
        row["return_pct"] = round(float(row["return_pct"]), 4)
        row["deweight_multiplier"] = round(float(row["deweight_multiplier"]), 4)
        row["effective_capital_ratio"] = round(float(row["effective_capital_ratio"]), 4)
        row["notional_share_pct"] = round(
            (float(row["total_notional"]) / total_notional * 100) if total_notional > 0 else 0.0,
            2,
        )

    top_winner = ranking[0] if ranking else None
    top_loser = ranking[-1] if ranking else None

    return {
        "ranking": ranking,
        "top_winner": top_winner,
        "top_loser": top_loser,
        "totals": {
            "trade_count": total_trade_count,
            "total_notional": round(total_notional, 2),
            "fees": round(total_fees, 2),
            "realized_pnl": round(total_realized_pnl, 2),
            "unrealized_pnl": round(total_unrealized_pnl, 2),
            "net_pnl": round(total_realized_pnl + total_unrealized_pnl - total_fees, 2),
        },
    }


def _equity_curve_svg(points: list[dict[str, Any]]) -> str:
    if not points:
        return '<div class="empty">?????????</div>'
    width = 960
    height = 200
    padding = 20
    equities = [float(point.get("equity", 0.0)) for point in points]
    min_equity = min(equities)
    max_equity = max(equities)
    spread = max(max_equity - min_equity, 1.0)
    step = (width - padding * 2) / max(len(points) - 1, 1)
    path_points = []
    for idx, point in enumerate(points):
        x = padding + idx * step
        y = height - padding - ((float(point.get("equity", 0.0)) - min_equity) / spread) * (height - padding * 2)
        path_points.append(f"{x:.1f},{y:.1f}")
    labels = (
        f'<text x="{padding}" y="16" fill="#94a3b8" font-size="12">?? {max_equity:,.2f}</text>'
        f'<text x="{padding}" y="{height - 4}" fill="#94a3b8" font-size="12">?? {min_equity:,.2f}</text>'
    )
    polyline = ' '.join(path_points)
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="100%" preserveAspectRatio="none">'
        f'<polyline fill="none" stroke="#38bdf8" stroke-width="3" points="{polyline}" />'
        f'{labels}'
        '</svg>'
    )


def _agent_nav_curve_svg(
    curves: dict[str, list[dict[str, Any]]],
    ranking: list[dict[str, Any]],
) -> str:
    if not curves:
        return '<div class="empty">????? NAV ?????</div>'

    selected_agents = [str(row.get("agent_id", "")) for row in ranking[:4] if row.get("agent_id")]
    if not selected_agents:
        selected_agents = list(curves.keys())[:4]
    selected_curves = {
        agent_id: curves.get(agent_id, [])
        for agent_id in selected_agents
        if curves.get(agent_id)
    }
    if not selected_curves:
        return '<div class="empty">????? NAV ?????</div>'

    width = 960
    height = 220
    padding = 24
    palette = ["#38bdf8", "#22c55e", "#f59e0b", "#f43f5e", "#a78bfa"]
    all_values = [
        float(point.get("nav", point.get("net_pnl", 0.0)))
        for points in selected_curves.values()
        for point in points
    ]
    min_value = min(all_values)
    max_value = max(all_values)
    if min_value == max_value:
        min_value -= 1.0
        max_value += 1.0
    spread = max(max_value - min_value, 1.0)
    max_points = max(len(points) for points in selected_curves.values())
    step = (width - padding * 2) / max(max_points - 1, 1)

    polyline_parts = []
    legend_parts = []
    for index, agent_id in enumerate(selected_agents):
        points = selected_curves.get(agent_id, [])
        if not points:
            continue
        color = palette[index % len(palette)]
        polyline = []
        for point_index, point in enumerate(points):
            value = float(point.get("nav", point.get("net_pnl", 0.0)))
            x = padding + point_index * step
            y = height - padding - ((value - min_value) / spread) * (height - padding * 2)
            polyline.append(f"{x:.1f},{y:.1f}")
        polyline_parts.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2.5" points="{" ".join(polyline)}" />'
        )
        legend_y = 18 + index * 18
        legend_parts.append(
            f'<text x="{padding}" y="{legend_y}" fill="{color}" font-size="12">{escape(agent_id)}</text>'
        )

    labels = (
        f'<text x="{width - 180}" y="16" fill="#94a3b8" font-size="12">?? NAV {max_value:,.2f}</text>'
        f'<text x="{width - 180}" y="{height - 6}" fill="#94a3b8" font-size="12">?? NAV {min_value:,.2f}</text>'
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" height="100%" preserveAspectRatio="none">'
        f'{"".join(polyline_parts)}'
        f'{"".join(legend_parts)}'
        f'{labels}'
        '</svg>'
    )
