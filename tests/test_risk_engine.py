from multi_agent_quant.agents.base import AgentSignal
from multi_agent_quant.config import ExecutionSettings, ExecutionVenue, RiskEngineSettings
from multi_agent_quant.risk.engine import RiskEngine


def _build_engine() -> RiskEngine:
    return RiskEngine(
        RiskEngineSettings(
            controls={
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
        ),
        ExecutionSettings(
            venues=[ExecutionVenue(name="sim-ctp", type="paper", adapter="ctp")],
            default_venue="sim-ctp",
            futures_multiplier={"IH9999.CCFX": 300},
            futures_margin_rate=0.12,
        ),
    )


def test_blocks_stock_buy_above_symbol_limit() -> None:
    engine = _build_engine()
    account = {
        "equity": 100_000.0,
        "stock_positions": {"510300.SH": 6_000},
        "stock_market_value": 24_000.0,
        "gross_exposure": 24_000.0,
    }
    signals = [
        AgentSignal(
            agent_id="reactive-hft",
            symbol="510300.SH",
            action="buy",
            confidence=0.8,
            metadata={
                "price": 4.0,
                "volatility": 0.3,
                "capital_ratio": 0.2,
                "target_notional": 10_000.0,
            },
        )
    ]

    assert engine.apply(signals, account=account) == []


def test_allows_trade_when_capital_ratio_is_large_but_trade_size_is_small() -> None:
    engine = _build_engine()
    account = {
        "equity": 100_000.0,
        "stock_positions": {},
        "stock_market_value": 0.0,
        "gross_exposure": 0.0,
    }
    signal = AgentSignal(
        agent_id="reactive-hft",
        symbol="510300.SH",
        action="buy",
        confidence=0.8,
        metadata={
            "price": 4.0,
            "volatility": 0.3,
            "capital_ratio": 0.5,
            "target_notional": 10_000.0,
        },
    )

    assert engine.apply([signal], account=account) == [signal]


def test_blocks_futures_buy_above_contract_limit() -> None:
    engine = _build_engine()
    account = {
        "equity": 1_000_000.0,
        "futures_positions": {
            "IH9999.CCFX": {
                "long_qty": 2,
                "short_qty": 0,
                "last_price": 2_400.0,
            }
        },
        "futures_margin_in_use": 180_000.0,
        "futures_notional_exposure": 1_440_000.0,
        "gross_exposure": 1_440_000.0,
    }
    signals = [
        AgentSignal(
            agent_id="index-hedge",
            symbol="IH9999.CCFX",
            action="buy",
            confidence=0.8,
            metadata={
                "price": 2_400.0,
                "volatility": 0.3,
                "capital_ratio": 0.2,
                "target_notional": 720_000.0,
            },
        )
    ]

    assert engine.apply(signals, account=account) == []


def test_allows_futures_sell_to_reduce_existing_long() -> None:
    engine = _build_engine()
    account = {
        "equity": 1_000_000.0,
        "futures_positions": {
            "IH9999.CCFX": {
                "long_qty": 2,
                "short_qty": 0,
                "last_price": 2_400.0,
            }
        },
        "futures_margin_in_use": 180_000.0,
        "futures_notional_exposure": 1_440_000.0,
        "gross_exposure": 1_440_000.0,
    }
    signal = AgentSignal(
        agent_id="index-hedge",
        symbol="IH9999.CCFX",
        action="sell",
        confidence=0.8,
        metadata={
            "price": 2_400.0,
            "volatility": 0.3,
            "capital_ratio": 0.2,
            "target_notional": 720_000.0,
        },
    )

    assert engine.apply([signal], account=account) == [signal]
