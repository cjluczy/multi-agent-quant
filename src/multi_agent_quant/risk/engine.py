from __future__ import annotations

from typing import Any, List

from ..agents.base import AgentSignal
from ..config import ExecutionSettings, RiskEngineSettings
from ..shared.logging import get_logger

LOGGER = get_logger(__name__)


class RiskEngine:
    def __init__(self, cfg: RiskEngineSettings, execution_cfg: ExecutionSettings):
        self.cfg = cfg
        self.execution_cfg = execution_cfg
        self.kill_switch = cfg.controls.get("kill_switch", False)
        self.position_limit = float(cfg.controls.get("position_limit_pct", 0.2))
        self.min_confidence = float(cfg.controls.get("min_confidence", 0.45))
        self.max_volatility = float(cfg.controls.get("max_volatility", 0.8))
        self.max_stock_position_pct = float(cfg.controls.get("max_stock_position_pct", 0.3))
        self.max_futures_contracts_per_symbol = int(
            cfg.controls.get("max_futures_contracts_per_symbol", 3)
        )
        self.max_futures_margin_pct = float(cfg.controls.get("max_futures_margin_pct", 0.35))
        self.max_futures_notional_pct = float(cfg.controls.get("max_futures_notional_pct", 1.0))
        self.max_gross_exposure_pct = float(cfg.controls.get("max_gross_exposure_pct", 1.15))

    def apply(
        self,
        signals: List[AgentSignal],
        account: dict[str, Any] | None = None,
    ) -> List[AgentSignal]:
        if self.kill_switch:
            LOGGER.warning("Kill switch active, blocking signals")
            return []
        snapshot = account or {}
        filtered: List[AgentSignal] = []
        for signal in signals:
            if signal.confidence < self.min_confidence:
                continue
            if signal.metadata.get("volatility", 0.0) > self.max_volatility:
                continue
            
            # 检查是否是减少仓位的交易
            is_reducing_position = False
            if signal.symbol in self.execution_cfg.futures_multiplier:
                positions = snapshot.get("futures_positions", {})
                position = positions.get(signal.symbol, {})
                long_qty = int(position.get("long_qty", 0))
                short_qty = int(position.get("short_qty", 0))
                if (signal.action == "sell" and long_qty > 0) or (signal.action == "buy" and short_qty > 0):
                    is_reducing_position = True
            else:
                stock_positions = snapshot.get("stock_positions", {})
                current_qty = int(stock_positions.get(signal.symbol, 0))
                if signal.action == "sell" and current_qty > 0:
                    is_reducing_position = True
            
            # 对于减少仓位的交易，跳过交易规模比率检查
            if not is_reducing_position and self._trade_size_ratio(signal, snapshot) > self.position_limit:
                continue
            
            exposure_error = self._exposure_error(signal, snapshot)
            if exposure_error:
                LOGGER.warning(
                    "Signal blocked by exposure guardrail",
                    extra={
                        "symbol": signal.symbol,
                        "agent_id": signal.agent_id,
                        "reason": exposure_error,
                    },
                )
                continue
            filtered.append(signal)
        return filtered

    def _trade_size_ratio(self, signal: AgentSignal, account: dict[str, Any]) -> float:
        equity = float(account.get("equity", 0.0))
        target_notional = abs(float(signal.metadata.get("target_notional", 0.0)))
        if equity <= 0 or target_notional <= 0:
            return 0.0
        return target_notional / equity

    def _exposure_error(
        self,
        signal: AgentSignal,
        account: dict[str, Any],
    ) -> str | None:
        price = float(signal.metadata.get("price", 0.0))
        target_notional = float(signal.metadata.get("target_notional", 0.0))
        equity = max(float(account.get("equity", 0.0)), 1.0)
        gross_exposure = self._gross_exposure(account)
        if price <= 0 or target_notional <= 0:
            return None
        if signal.symbol in self.execution_cfg.futures_multiplier:
            # 对于期货，允许卖出以减少多头仓位，或买入以减少空头仓位
            positions = account.get("futures_positions", {})
            position = positions.get(signal.symbol, {})
            long_qty = int(position.get("long_qty", 0))
            short_qty = int(position.get("short_qty", 0))
            
            # 如果是卖出动作且有多头仓位，或者是买入动作且有空头仓位，直接通过
            if (signal.action == "sell" and long_qty > 0) or (signal.action == "buy" and short_qty > 0):
                return None
            
            return self._check_futures_limits(signal, account, equity, gross_exposure, price, target_notional)
        return self._check_stock_limits(signal, account, equity, gross_exposure, price, target_notional)

    def _check_stock_limits(
        self,
        signal: AgentSignal,
        account: dict[str, Any],
        equity: float,
        gross_exposure: float,
        price: float,
        target_notional: float,
    ) -> str | None:
        if signal.action != "buy":
            return None
        stock_positions = account.get("stock_positions", {})
        current_qty = int(stock_positions.get(signal.symbol, 0))
        current_value = current_qty * price
        projected_symbol_value = current_value + target_notional
        if projected_symbol_value / equity > self.max_stock_position_pct:
            return "stock_position_limit"
        if (gross_exposure + target_notional) / equity > self.max_gross_exposure_pct:
            return "gross_exposure_limit"
        return None

    def _check_futures_limits(
        self,
        signal: AgentSignal,
        account: dict[str, Any],
        equity: float,
        gross_exposure: float,
        price: float,
        target_notional: float,
    ) -> str | None:
        multiplier = self.execution_cfg.futures_multiplier.get(signal.symbol, 1)
        contracts = max(1, int(target_notional / (price * multiplier)))
        positions = account.get("futures_positions", {})
        position = positions.get(signal.symbol, {})
        long_qty = int(position.get("long_qty", 0))
        short_qty = int(position.get("short_qty", 0))

        if signal.action == "buy" and short_qty > 0:
            return None
        if signal.action == "sell" and long_qty > 0:
            return None

        projected_contracts = long_qty + contracts if signal.action == "buy" else short_qty + contracts
        if projected_contracts > self.max_futures_contracts_per_symbol:
            return "futures_contract_limit"

        additional_margin = price * multiplier * contracts * self.execution_cfg.futures_margin_rate
        current_margin = float(account.get("futures_margin_in_use", 0.0))
        projected_margin = current_margin + additional_margin
        if projected_margin / equity > self.max_futures_margin_pct:
            return "futures_margin_limit"

        current_futures_notional = self._futures_notional_exposure(account)
        projected_futures_notional = current_futures_notional + price * multiplier * contracts
        if projected_futures_notional / equity > self.max_futures_notional_pct:
            return "futures_notional_limit"

        if (gross_exposure + price * multiplier * contracts) / equity > self.max_gross_exposure_pct:
            return "gross_exposure_limit"
        return None

    def _gross_exposure(self, account: dict[str, Any]) -> float:
        if "gross_exposure" in account:
            return float(account.get("gross_exposure", 0.0))
        return float(account.get("stock_market_value", 0.0)) + self._futures_notional_exposure(account)

    def _futures_notional_exposure(self, account: dict[str, Any]) -> float:
        if "futures_notional_exposure" in account:
            return float(account.get("futures_notional_exposure", 0.0))
        notional = 0.0
        positions = account.get("futures_positions", {})
        for symbol, position in positions.items():
            last_price = float(position.get("last_price", 0.0))
            multiplier = self.execution_cfg.futures_multiplier.get(symbol, 1)
            contracts = int(position.get("long_qty", 0)) + int(position.get("short_qty", 0))
            notional += contracts * last_price * multiplier
        return notional
