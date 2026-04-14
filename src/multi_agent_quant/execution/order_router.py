from __future__ import annotations

import json
import pathlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, List

from ..agents.base import AgentSignal
from ..config import ExecutionSettings
from ..risk.engine import RiskEngine
from ..shared.logging import get_logger

LOGGER = get_logger(__name__)


@dataclass
class Fill:
    symbol: str
    stock_name: str
    action: str
    quantity: int
    price: float
    notional: float
    effect: str
    fee: float
    realized_pnl: float
    venue: str
    agent_id: str
    initiator_id: str
    timestamp: str = ""


@dataclass
class StockPosition:
    quantity: int = 0
    avg_price: float = 0.0


@dataclass
class FuturesPosition:
    long_qty: int = 0
    long_avg_price: float = 0.0
    short_qty: int = 0
    short_avg_price: float = 0.0


@dataclass
class AgentStats:
    trade_count: int = 0
    total_notional: float = 0.0
    fees: float = 0.0
    realized_pnl: float = 0.0
    effect_breakdown: Dict[str, int] | None = None

    def __post_init__(self) -> None:
        if self.effect_breakdown is None:
            self.effect_breakdown = {}


class PaperBroker:
    def __init__(self, cfg: ExecutionSettings, initial_cash: float):
        self.cfg = cfg
        self.cash = initial_cash
        self.stock_positions: Dict[str, StockPosition] = {}
        self.futures_positions: Dict[str, FuturesPosition] = {}
        self.agent_stock_positions: Dict[str, Dict[str, StockPosition]] = {}
        self.agent_futures_positions: Dict[str, Dict[str, FuturesPosition]] = {}
        self.agent_stats: Dict[str, AgentStats] = {}
        self.last_prices: Dict[str, float] = {}
        self.realized_pnl = 0.0
        self.total_fees = 0.0
        self.trade_count = 0
        self.blotter_path = pathlib.Path(cfg.blotter_path)
        self.blotter_path.parent.mkdir(parents=True, exist_ok=True)
        self.blotter_path.write_text("", encoding="utf-8")
        self.stock_names = {
            "600519.SH": "贵州茅台",
            "000001.SZ": "平安银行",
            "000002.SZ": "万科A",
            "000003.SZ": "PT金田A",
            "510300.SH": "沪深300ETF",
            "IH9999.CCFX": "沪深300指数期货"
        }
        self.stock_names = {
            "600519.SH": "贵州茅台",
            "000001.SZ": "平安银行",
            "000002.SZ": "万科A",
            "000003.SZ": "PT金田A",
            "510300.SH": "沪深300ETF",
            "IH9999.CCFX": "沪深300指数期货",
        }

    def _get_stock_name(self, symbol: str) -> str:
        return self.stock_names.get(symbol, symbol)

    def execute(self, signal: AgentSignal, venue: str, initiator_id: str | None = None) -> Fill | None:
        price = float(signal.metadata.get("price", 0.0))
        target_notional = float(signal.metadata.get("target_notional", 0.0))
        if price <= 0 or target_notional <= 0:
            return None
        self.last_prices[signal.symbol] = price
        multiplier = self.cfg.futures_multiplier.get(signal.symbol, 1)
        if multiplier > 1:
            return self._execute_futures(signal, venue, price, target_notional, multiplier, initiator_id)
        return self._execute_stock(signal, venue, price, target_notional, initiator_id)

    def _stock_execution_price(self, signal: AgentSignal, reference_price: float) -> float:
        bid_price = float(signal.metadata.get("bid_price", 0.0))
        ask_price = float(signal.metadata.get("ask_price", 0.0))
        if signal.action == "buy" and ask_price > 0:
            return ask_price
        if signal.action == "sell" and bid_price > 0:
            return bid_price
        spread_bps = float(signal.metadata.get("spread_bps", self.cfg.stock_bid_ask_spread_bps))
        spread = reference_price * spread_bps / 10000.0
        if signal.action == "buy":
            return round(reference_price + spread / 2, 4)
        if signal.action == "sell":
            return round(max(0.01, reference_price - spread / 2), 4)
        return reference_price

    def _stock_fee(self, *, notional: float, is_sell: bool) -> float:
        commission = max(self.cfg.stock_min_commission, notional * self.cfg.stock_commission_rate) if notional > 0 else 0.0
        transfer_fee = notional * self.cfg.stock_transfer_fee_rate
        stamp_duty = notional * self.cfg.stock_stamp_duty_rate if is_sell else 0.0
        return round(commission + transfer_fee + stamp_duty, 2)

    def _get_agent_stock_position(self, agent_id: str, symbol: str) -> StockPosition:
        return self.agent_stock_positions.setdefault(agent_id, {}).setdefault(symbol, StockPosition())

    def _get_agent_futures_position(self, agent_id: str, symbol: str) -> FuturesPosition:
        return self.agent_futures_positions.setdefault(agent_id, {}).setdefault(symbol, FuturesPosition())

    def _get_agent_stats(self, agent_id: str) -> AgentStats:
        return self.agent_stats.setdefault(agent_id, AgentStats())

    def _rebuild_stock_position(self, symbol: str) -> None:
        total_qty = 0
        total_cost = 0.0
        for positions in self.agent_stock_positions.values():
            position = positions.get(symbol)
            if not position or position.quantity <= 0:
                continue
            total_qty += position.quantity
            total_cost += position.avg_price * position.quantity
        if total_qty <= 0:
            self.stock_positions.pop(symbol, None)
            return
        self.stock_positions[symbol] = StockPosition(quantity=total_qty, avg_price=total_cost / total_qty)

    def _rebuild_futures_position(self, symbol: str) -> None:
        long_qty = 0
        long_cost = 0.0
        short_qty = 0
        short_cost = 0.0
        for positions in self.agent_futures_positions.values():
            position = positions.get(symbol)
            if not position:
                continue
            if position.long_qty > 0:
                long_qty += position.long_qty
                long_cost += position.long_avg_price * position.long_qty
            if position.short_qty > 0:
                short_qty += position.short_qty
                short_cost += position.short_avg_price * position.short_qty
        if long_qty == 0 and short_qty == 0:
            self.futures_positions.pop(symbol, None)
            return
        self.futures_positions[symbol] = FuturesPosition(
            long_qty=long_qty,
            long_avg_price=(long_cost / long_qty) if long_qty > 0 else 0.0,
            short_qty=short_qty,
            short_avg_price=(short_cost / short_qty) if short_qty > 0 else 0.0,
        )

    def _execute_stock(
        self,
        signal: AgentSignal,
        venue: str,
        price: float,
        target_notional: float,
        initiator_id: str | None,
    ) -> Fill | None:
        trade_price = self._stock_execution_price(signal, price)
        raw_qty = int(target_notional / trade_price)
        quantity = max(self.cfg.lot_size, (raw_qty // self.cfg.lot_size) * self.cfg.lot_size)
        if quantity <= 0:
            return None
        position = self.stock_positions.setdefault(signal.symbol, StockPosition())
        agent_position = self._get_agent_stock_position(signal.agent_id, signal.symbol)
        notional = round(quantity * trade_price, 2)
        realized_pnl = 0.0
        fee = 0.0
        if signal.action == "buy":
            fee = self._stock_fee(notional=notional, is_sell=False)
            total_cash_cost = round(notional + fee, 2)
            if total_cash_cost > self.cash:
                return None
            self.cash -= total_cash_cost
            total_cost = agent_position.avg_price * agent_position.quantity + total_cash_cost
            agent_position.quantity += quantity
            agent_position.avg_price = total_cost / agent_position.quantity if agent_position.quantity > 0 else 0.0
            self._rebuild_stock_position(signal.symbol)
            effect = "buy_stock"
        elif signal.action == "sell":
            current = position.quantity
            owned_quantity = agent_position.quantity
            if current <= 0 or owned_quantity <= 0:
                return None
            quantity = min(quantity, current, owned_quantity)
            if quantity <= 0:
                return None
            notional = round(quantity * trade_price, 2)
            fee = self._stock_fee(notional=notional, is_sell=True)
            net_proceeds = round(notional - fee, 2)
            realized_pnl = round(net_proceeds - agent_position.avg_price * quantity, 2)
            self.cash += net_proceeds
            agent_position.quantity = owned_quantity - quantity
            if agent_position.quantity == 0:
                agent_position.avg_price = 0.0
            self.realized_pnl += realized_pnl
            self._rebuild_stock_position(signal.symbol)
            effect = "sell_stock"
        else:
            return None
        fill = Fill(
            symbol=signal.symbol,
            stock_name=self._get_stock_name(signal.symbol),
            action=signal.action,
            quantity=quantity,
            price=trade_price,
            notional=notional,
            effect=effect,
            fee=fee,
            realized_pnl=realized_pnl,
            venue=venue,
            agent_id=signal.agent_id,
            initiator_id=initiator_id or signal.agent_id,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        )
        self._write_fill(fill)
        return fill

    def _execute_futures(
        self,
        signal: AgentSignal,
        venue: str,
        price: float,
        target_notional: float,
        multiplier: int,
        initiator_id: str | None,
    ) -> Fill | None:
        quantity = max(1, int(target_notional / (price * multiplier)))
        position = self.futures_positions.setdefault(signal.symbol, FuturesPosition())
        if signal.action == "buy":
            if position.short_qty > 0:
                return self._close_short(signal, venue, price, quantity, multiplier, position, initiator_id)
            return self._open_long(signal, venue, price, quantity, multiplier, position, initiator_id)
        if signal.action == "sell":
            if position.long_qty > 0:
                return self._close_long(signal, venue, price, quantity, multiplier, position, initiator_id)
            return self._open_short(signal, venue, price, quantity, multiplier, position, initiator_id)
        return None

    def _open_long(
        self,
        signal: AgentSignal,
        venue: str,
        price: float,
        quantity: int,
        multiplier: int,
        position: FuturesPosition,
        initiator_id: str | None,
    ) -> Fill | None:
        margin = quantity * price * multiplier * self.cfg.futures_margin_rate
        notional = round(quantity * price * multiplier, 2)
        fee = round(notional * self.cfg.futures_fee_rate, 2)
        required_cash = round(margin + fee, 2)
        if required_cash > self.cash:
            return None
        agent_position = self._get_agent_futures_position(signal.agent_id, signal.symbol)
        total_cost = agent_position.long_avg_price * agent_position.long_qty + price * quantity
        agent_position.long_qty += quantity
        agent_position.long_avg_price = total_cost / agent_position.long_qty
        self._rebuild_futures_position(signal.symbol)
        self.cash -= required_cash
        fill = Fill(
            symbol=signal.symbol,
            stock_name=self._get_stock_name(signal.symbol),
            action=signal.action,
            quantity=quantity,
            price=price,
            notional=notional,
            effect="open_long",
            fee=fee,
            realized_pnl=0.0,
            venue=venue,
            agent_id=signal.agent_id,
            initiator_id=initiator_id or signal.agent_id,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        )
        self._write_fill(fill)
        return fill

    def _open_short(
        self,
        signal: AgentSignal,
        venue: str,
        price: float,
        quantity: int,
        multiplier: int,
        position: FuturesPosition,
        initiator_id: str | None,
    ) -> Fill | None:
        margin = quantity * price * multiplier * self.cfg.futures_margin_rate
        notional = round(quantity * price * multiplier, 2)
        fee = round(notional * self.cfg.futures_fee_rate, 2)
        required_cash = round(margin + fee, 2)
        if required_cash > self.cash:
            return None
        agent_position = self._get_agent_futures_position(signal.agent_id, signal.symbol)
        total_cost = agent_position.short_avg_price * agent_position.short_qty + price * quantity
        agent_position.short_qty += quantity
        agent_position.short_avg_price = total_cost / agent_position.short_qty
        self._rebuild_futures_position(signal.symbol)
        self.cash -= required_cash
        fill = Fill(
            symbol=signal.symbol,
            stock_name=self._get_stock_name(signal.symbol),
            action=signal.action,
            quantity=quantity,
            price=price,
            notional=notional,
            effect="open_short",
            fee=fee,
            realized_pnl=0.0,
            venue=venue,
            agent_id=signal.agent_id,
            initiator_id=initiator_id or signal.agent_id,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        )
        self._write_fill(fill)
        return fill

    def _close_long(
        self,
        signal: AgentSignal,
        venue: str,
        price: float,
        quantity: int,
        multiplier: int,
        position: FuturesPosition,
        initiator_id: str | None,
    ) -> Fill | None:
        agent_position = self._get_agent_futures_position(signal.agent_id, signal.symbol)
        close_qty = min(quantity, position.long_qty, agent_position.long_qty)
        if close_qty <= 0:
            return None
        notional = round(close_qty * price * multiplier, 2)
        fee = round(notional * self.cfg.futures_fee_rate, 2)
        released_margin = round(
            close_qty * agent_position.long_avg_price * multiplier * self.cfg.futures_margin_rate,
            2,
        )
        pnl = round((price - agent_position.long_avg_price) * multiplier * close_qty, 2)
        self.cash += released_margin + pnl - fee
        self.realized_pnl += pnl
        agent_position.long_qty -= close_qty
        if agent_position.long_qty == 0:
            agent_position.long_avg_price = 0.0
        self._rebuild_futures_position(signal.symbol)
        fill = Fill(
            symbol=signal.symbol,
            stock_name=self._get_stock_name(signal.symbol),
            action=signal.action,
            quantity=close_qty,
            price=price,
            notional=notional,
            effect="close_long",
            fee=fee,
            realized_pnl=pnl,
            venue=venue,
            agent_id=signal.agent_id,
            initiator_id=initiator_id or signal.agent_id,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        )
        self._write_fill(fill)
        return fill

    def _close_short(
        self,
        signal: AgentSignal,
        venue: str,
        price: float,
        quantity: int,
        multiplier: int,
        position: FuturesPosition,
        initiator_id: str | None,
    ) -> Fill | None:
        agent_position = self._get_agent_futures_position(signal.agent_id, signal.symbol)
        close_qty = min(quantity, position.short_qty, agent_position.short_qty)
        if close_qty <= 0:
            return None
        notional = round(close_qty * price * multiplier, 2)
        fee = round(notional * self.cfg.futures_fee_rate, 2)
        released_margin = round(
            close_qty * agent_position.short_avg_price * multiplier * self.cfg.futures_margin_rate,
            2,
        )
        pnl = round((agent_position.short_avg_price - price) * multiplier * close_qty, 2)
        self.cash += released_margin + pnl - fee
        self.realized_pnl += pnl
        agent_position.short_qty -= close_qty
        if agent_position.short_qty == 0:
            agent_position.short_avg_price = 0.0
        self._rebuild_futures_position(signal.symbol)
        fill = Fill(
            symbol=signal.symbol,
            stock_name=self._get_stock_name(signal.symbol),
            action=signal.action,
            quantity=close_qty,
            price=price,
            notional=notional,
            effect="close_short",
            fee=fee,
            realized_pnl=pnl,
            venue=venue,
            agent_id=signal.agent_id,
            initiator_id=initiator_id or signal.agent_id,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        )
        self._write_fill(fill)
        return fill

    def _write_fill(self, fill: Fill) -> None:
        self.trade_count += 1
        self.total_fees += fill.fee
        stats = self._get_agent_stats(fill.agent_id)
        stats.trade_count += 1
        stats.total_notional += fill.notional
        stats.fees += fill.fee
        stats.realized_pnl += fill.realized_pnl
        stats.effect_breakdown[fill.effect] = stats.effect_breakdown.get(fill.effect, 0) + 1
        with self.blotter_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(fill), ensure_ascii=True) + "\n")

    def enforce_maintenance_margin(self, venue: str) -> List[Fill]:
        forced_fills: List[Fill] = []
        while True:
            snapshot = self.snapshot()
            required_cash = snapshot["futures_margin_in_use"] * self.cfg.futures_maintenance_margin_rate
            if snapshot["futures_margin_in_use"] <= 0 or snapshot["cash_available"] >= required_cash:
                break
            agent_id, symbol, direction = self._pick_forced_liquidation_target()
            if not agent_id or not symbol or not direction:
                break
            last_price = self.last_prices.get(symbol, 0.0)
            if last_price <= 0:
                break
            action = "sell" if direction == "long" else "buy"
            fill = self.execute(
                AgentSignal(
                    agent_id=agent_id,
                    symbol=symbol,
                    action=action,
                    confidence=1.0,
                    metadata={
                        "price": last_price,
                        "target_notional": last_price * self.cfg.futures_multiplier[symbol],
                    },
                ),
                venue,
                initiator_id="risk-engine",
            )
            if not fill:
                break
            forced_fills.append(fill)
        return forced_fills

    def _pick_forced_liquidation_target(self) -> tuple[str | None, str | None, str | None]:
        worst_agent_id: str | None = None
        worst_symbol: str | None = None
        worst_direction: str | None = None
        worst_pnl = 0.0
        for agent_id, positions in self.agent_futures_positions.items():
            for symbol, position in positions.items():
                last_price = self.last_prices.get(symbol, 0.0)
                multiplier = self.cfg.futures_multiplier.get(symbol, 1)
                if position.long_qty > 0:
                    pnl = (last_price - position.long_avg_price) * multiplier * position.long_qty
                    if worst_symbol is None or pnl < worst_pnl:
                        worst_agent_id = agent_id
                        worst_symbol = symbol
                        worst_direction = "long"
                        worst_pnl = pnl
                if position.short_qty > 0:
                    pnl = (position.short_avg_price - last_price) * multiplier * position.short_qty
                    if worst_symbol is None or pnl < worst_pnl:
                        worst_agent_id = agent_id
                        worst_symbol = symbol
                        worst_direction = "short"
                        worst_pnl = pnl
        return worst_agent_id, worst_symbol, worst_direction

    def _build_agent_snapshot(self) -> tuple[Dict[str, Dict[str, object]], Dict[str, Dict[str, object]]]:
        agent_positions: Dict[str, Dict[str, object]] = {}
        agent_metrics: Dict[str, Dict[str, object]] = {}
        agent_ids = set(self.agent_stats) | set(self.agent_stock_positions) | set(self.agent_futures_positions)

        for agent_id in sorted(agent_ids):
            stock_detail: Dict[str, Dict[str, float]] = {}
            stock_market_value = 0.0
            stock_unrealized = 0.0
            for symbol, position in self.agent_stock_positions.get(agent_id, {}).items():
                if position.quantity <= 0:
                    continue
                last_price = self.last_prices.get(symbol, 0.0)
                market_value = position.quantity * last_price
                unrealized_pnl = (last_price - position.avg_price) * position.quantity
                stock_market_value += market_value
                stock_unrealized += unrealized_pnl
                stock_detail[symbol] = {
                    "quantity": position.quantity,
                    "avg_price": round(position.avg_price, 2),
                    "last_price": round(last_price, 2),
                    "market_value": round(market_value, 2),
                    "unrealized_pnl": round(unrealized_pnl, 2),
                }

            futures_detail: Dict[str, Dict[str, float]] = {}
            futures_margin = 0.0
            futures_unrealized = 0.0
            futures_notional = 0.0
            for symbol, position in self.agent_futures_positions.get(agent_id, {}).items():
                if position.long_qty == 0 and position.short_qty == 0:
                    continue
                last_price = self.last_prices.get(symbol, 0.0)
                multiplier = self.cfg.futures_multiplier.get(symbol, 1)
                long_margin = position.long_qty * position.long_avg_price * multiplier * self.cfg.futures_margin_rate
                short_margin = position.short_qty * position.short_avg_price * multiplier * self.cfg.futures_margin_rate
                long_pnl = (last_price - position.long_avg_price) * multiplier * position.long_qty
                short_pnl = (position.short_avg_price - last_price) * multiplier * position.short_qty
                futures_margin += long_margin + short_margin
                futures_unrealized += long_pnl + short_pnl
                futures_notional += (position.long_qty + position.short_qty) * last_price * multiplier
                futures_detail[symbol] = {
                    "long_qty": position.long_qty,
                    "long_avg_price": round(position.long_avg_price, 2),
                    "short_qty": position.short_qty,
                    "short_avg_price": round(position.short_avg_price, 2),
                    "last_price": round(last_price, 2),
                    "unrealized_pnl": round(long_pnl + short_pnl, 2),
                }

            stats = self._get_agent_stats(agent_id)
            unrealized_pnl = stock_unrealized + futures_unrealized
            net_pnl = stats.realized_pnl + unrealized_pnl - stats.fees
            agent_positions[agent_id] = {
                "stocks": stock_detail,
                "futures": futures_detail,
            }
            agent_metrics[agent_id] = {
                "trade_count": stats.trade_count,
                "total_notional": round(stats.total_notional, 2),
                "fees": round(stats.fees, 2),
                "realized_pnl": round(stats.realized_pnl, 2),
                "stock_unrealized_pnl": round(stock_unrealized, 2),
                "futures_unrealized_pnl": round(futures_unrealized, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "net_pnl": round(net_pnl, 2),
                "stock_market_value": round(stock_market_value, 2),
                "futures_margin_in_use": round(futures_margin, 2),
                "futures_notional_exposure": round(futures_notional, 2),
                "effect_breakdown": dict(stats.effect_breakdown),
            }
        return agent_positions, agent_metrics

    def snapshot(self) -> dict[str, object]:
        stock_market_value = 0.0
        stock_unrealized_total = 0.0
        stock_positions = {
            symbol: position.quantity
            for symbol, position in self.stock_positions.items()
            if position.quantity > 0
        }
        stock_position_detail: Dict[str, Dict[str, float]] = {}
        for symbol, quantity in stock_positions.items():
            position = self.stock_positions[symbol]
            last_price = self.last_prices.get(symbol, 0.0)
            market_value = quantity * last_price
            unrealized_pnl = (last_price - position.avg_price) * quantity
            stock_market_value += market_value
            stock_unrealized_total += unrealized_pnl
            stock_position_detail[symbol] = {
                "quantity": quantity,
                "avg_price": round(position.avg_price, 2),
                "last_price": round(last_price, 2),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
            }

        futures_margin = 0.0
        futures_unrealized = 0.0
        futures_notional_exposure = 0.0
        futures_net_notional_exposure = 0.0
        futures_snapshot: Dict[str, Dict[str, float]] = {}
        for symbol, position in self.futures_positions.items():
            if position.long_qty == 0 and position.short_qty == 0:
                continue
            last_price = self.last_prices.get(symbol, 0.0)
            multiplier = self.cfg.futures_multiplier.get(symbol, 1)
            long_margin = position.long_qty * position.long_avg_price * multiplier * self.cfg.futures_margin_rate
            short_margin = position.short_qty * position.short_avg_price * multiplier * self.cfg.futures_margin_rate
            long_pnl = (last_price - position.long_avg_price) * multiplier * position.long_qty
            short_pnl = (position.short_avg_price - last_price) * multiplier * position.short_qty
            futures_margin += long_margin + short_margin
            futures_unrealized += long_pnl + short_pnl
            futures_notional_exposure += (position.long_qty + position.short_qty) * last_price * multiplier
            futures_net_notional_exposure += (position.long_qty - position.short_qty) * last_price * multiplier
            futures_snapshot[symbol] = {
                "long_qty": position.long_qty,
                "long_avg_price": round(position.long_avg_price, 2),
                "short_qty": position.short_qty,
                "short_avg_price": round(position.short_avg_price, 2),
                "last_price": round(last_price, 2),
                "unrealized_pnl": round(long_pnl + short_pnl, 2),
            }

        agent_positions, agent_metrics = self._build_agent_snapshot()
        equity = self.cash + stock_market_value + futures_margin + futures_unrealized
        gross_exposure = stock_market_value + futures_notional_exposure
        leverage_ratio = gross_exposure / equity if equity > 0 else 0.0
        return {
            "cash_available": round(self.cash, 2),
            "stock_positions": stock_positions,
            "stock_position_detail": stock_position_detail,
            "stock_market_value": round(stock_market_value, 2),
            "stock_unrealized_pnl": round(stock_unrealized_total, 2),
            "futures_positions": futures_snapshot,
            "futures_margin_in_use": round(futures_margin, 2),
            "futures_notional_exposure": round(futures_notional_exposure, 2),
            "futures_net_notional_exposure": round(futures_net_notional_exposure, 2),
            "futures_unrealized_pnl": round(futures_unrealized, 2),
            "gross_exposure": round(gross_exposure, 2),
            "leverage_ratio": round(leverage_ratio, 4),
            "realized_pnl": round(self.realized_pnl, 2),
            "total_fees": round(self.total_fees, 2),
            "trade_count": self.trade_count,
            "equity": round(equity, 2),
            "last_prices": {symbol: round(price, 2) for symbol, price in self.last_prices.items()},
            "agent_positions": agent_positions,
            "agent_metrics": agent_metrics,
        }


class OrderRouter:
    def __init__(self, cfg: ExecutionSettings, risk_engine: RiskEngine, initial_cash: float):
        self.cfg = cfg
        self.risk_engine = risk_engine
        self.default_venue = cfg.default_venue
        self.broker = PaperBroker(cfg, initial_cash)

    def route(self, signals: List[AgentSignal]) -> List[Fill]:
        fills: List[Fill] = []
        for signal in signals:
            fill = self.broker.execute(signal, self.default_venue)
            if not fill:
                continue
            fills.append(fill)
            LOGGER.info(
                "Routing order",
                extra={
                    "symbol": signal.symbol,
                    "action": signal.action,
                    "venue": self.default_venue,
                    "quantity": fill.quantity,
                },
            )
        forced_fills = self.broker.enforce_maintenance_margin(self.default_venue)
        for fill in forced_fills:
            fills.append(fill)
            LOGGER.warning(
                "Forced liquidation",
                extra={
                    "symbol": fill.symbol,
                    "effect": fill.effect,
                    "quantity": fill.quantity,
                },
            )
        return fills

    def snapshot(self) -> dict[str, object]:
        return self.broker.snapshot()
