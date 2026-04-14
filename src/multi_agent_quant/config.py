from __future__ import annotations

import pathlib
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class RiskBudget(BaseModel):
    max_drawdown: float = Field(0.12, ge=0, le=1)
    var_limit: float = Field(0.08, ge=0, le=1)
    exposure_limit: float = Field(1.0, ge=0)


class SystemSettings(BaseModel):
    mode: str = Field("simulation")
    timezone: str = Field("Asia/Shanghai")
    market: str = Field("cn")
    capital_base: float = 1_000_000
    loop_iterations: int = 60
    poll_interval_seconds: float = Field(0.0, ge=0)
    risk_budget: RiskBudget = Field(default_factory=RiskBudget)


class FeedConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str

    def payload(self) -> dict[str, Any]:
        return self.model_dump()


class FeedsSettings(BaseModel):
    market: FeedConfig
    fundamental: FeedConfig | None = None
    sentiment: FeedConfig | None = None


class StrategyAutoGenSettings(BaseModel):
    enabled: bool = True
    max_candidates: int = 12


class StrategyGeneticSettings(BaseModel):
    population: int = 24
    elitism: float = 0.2


class StrategyFactorySettings(BaseModel):
    templates: list[str]
    autogen: StrategyAutoGenSettings = Field(default_factory=StrategyAutoGenSettings)
    genetic: StrategyGeneticSettings = Field(default_factory=StrategyGeneticSettings)


class AgentConfig(BaseModel):
    id: str
    role: str
    capital_ratio: float
    enabled: bool = True

    @field_validator("capital_ratio")
    @classmethod
    def _check_ratio(cls, value: float) -> float:
        if not 0 < value <= 1:
            raise ValueError("capital_ratio must be within (0, 1]")
        return value


class AgentSettings(BaseModel):
    scheduler: dict[str, Any]
    registry: list[AgentConfig]

    @property
    def total_ratio(self) -> float:
        return sum(agent.capital_ratio for agent in self.registry if agent.enabled)


class MarketSimulationSettings(BaseModel):
    liquidity_model: str = "cn_order_book"
    shock_scenarios: list[str] = Field(default_factory=list)
    adversaries: dict[str, Any] = Field(default_factory=dict)
    slippage_bps: float = 8.0


class EvolutionSettings(BaseModel):
    population: int = 20
    elitism: float = 0.2
    refresh_interval: int = 10


class PortfolioBrainSettings(BaseModel):
    optimizer: str = "risk_parity"
    bandit: dict[str, Any] = Field(default_factory=dict)
    min_trade_notional: float = 2_000
    per_trade_nav_pct: float = Field(0.1, gt=0, le=1)
    loser_deweight_enabled: bool = True
    loser_deweight_floor: float = Field(0.35, gt=0, le=1)
    loser_deweight_slope: float = Field(3.0, ge=0)


class RiskEngineSettings(BaseModel):
    controls: dict[str, Any]


class ExecutionVenue(BaseModel):
    name: str
    type: str
    adapter: str


class ExecutionSettings(BaseModel):
    venues: list[ExecutionVenue]
    default_venue: str
    lot_size: int = 100
    futures_multiplier: dict[str, int] = Field(default_factory=dict)
    futures_margin_rate: float = 0.12
    futures_maintenance_margin_rate: float = 0.1
    futures_fee_rate: float = 0.000023
    stock_commission_rate: float = 0.00025
    stock_min_commission: float = 5.0
    stock_stamp_duty_rate: float = 0.0005
    stock_transfer_fee_rate: float = 0.00001
    stock_bid_ask_spread_bps: float = 6.0
    blotter_path: str = "runtime/blotter.jsonl"


class LoggingSettings(BaseModel):
    level: str = "INFO"
    sink: str = "logs/system.log"


class SystemConfig(BaseModel):
    version: str
    system: SystemSettings
    feeds: FeedsSettings
    reasoning: dict[str, Any] = Field(default_factory=dict)
    strategy_factory: StrategyFactorySettings
    agents: AgentSettings
    market_simulation: MarketSimulationSettings = Field(default_factory=MarketSimulationSettings)
    evolution: EvolutionSettings = Field(default_factory=EvolutionSettings)
    portfolio_brain: PortfolioBrainSettings = Field(default_factory=PortfolioBrainSettings)
    risk_engine: RiskEngineSettings
    execution: ExecutionSettings
    logging: LoggingSettings = Field(default_factory=LoggingSettings)


def load_config(path: pathlib.Path) -> SystemConfig:
    with path.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh)
    cfg = SystemConfig(**payload)
    if cfg.agents.total_ratio > 1.0:
        raise ValueError("Sum of agent capital_ratio must be <= 1.0")
    return cfg
