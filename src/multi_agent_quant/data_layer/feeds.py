from __future__ import annotations

import csv
import math
import os
import random
import statistics
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Deque, Dict, Iterable

from ..shared.logging import get_logger

LOGGER = get_logger(__name__)


@dataclass
class Tick:
    symbol: str
    price: float
    volume: float
    features: Dict[str, float]
    bid_price: float = 0.0
    ask_price: float = 0.0


class BaseFeed:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def stream(self) -> Iterable[Tick]:
        raise NotImplementedError


class BaseMarketFeed(BaseFeed):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.symbols = list(config.get("symbols", []))
        self.feature_window = max(3, int(config.get("feature_window", 20)))
        self._tick_index = 0
        self._price_windows: dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=self.feature_window))
        self._return_windows: dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=self.feature_window))
        self._last_price: dict[str, float] = {}

    def _build_tick(
        self,
        symbol: str,
        price: float,
        volume: float,
        *,
        bid_price: float | None = None,
        ask_price: float | None = None,
    ) -> Tick:
        previous_price = self._last_price.get(symbol, price)
        pct_move = ((price - previous_price) / previous_price) if previous_price > 0 else 0.0
        self._last_price[symbol] = price
        self._price_windows[symbol].append(price)
        self._return_windows[symbol].append(pct_move)
        self._tick_index += 1

        recent_returns = list(self._return_windows[symbol])
        recent_prices = list(self._price_windows[symbol])
        momentum_window = recent_returns[-min(5, len(recent_returns)) :] if recent_returns else [0.0]
        momentum_raw = sum(momentum_window)
        mean_price = sum(recent_prices) / len(recent_prices) if recent_prices else price
        trend_raw = ((price - mean_price) / mean_price) if mean_price > 0 else 0.0
        volatility_raw = statistics.pstdev(recent_returns) if len(recent_returns) > 1 else abs(pct_move)
        default_spread_bps = 8.0 if symbol.endswith("CCFX") else 6.0
        spread = price * default_spread_bps / 10000.0
        bid = float(bid_price) if bid_price and bid_price > 0 else max(0.01, price - spread / 2)
        ask = float(ask_price) if ask_price and ask_price > 0 else max(bid, price + spread / 2)

        return Tick(
            symbol=symbol,
            price=round(price, 2),
            volume=round(volume, 2),
            features={
                "momentum": round(_clamp(0.5 + momentum_raw * 25.0), 4),
                "volatility": round(max(0.0, volatility_raw) * 100.0, 4),
                "trend_strength": round(_clamp(0.5 + trend_raw * 18.0), 4),
                "tick_index": float(self._tick_index),
            },
            bid_price=round(bid, 4),
            ask_price=round(ask, 4),
        )


class SyntheticMarketDataFeed(BaseMarketFeed):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        seed = int(config.get("seed", 7))
        self.random = random.Random(seed)
        if not self.symbols:
            self.symbols = ["510300.SH", "IF9999.CCFX"]
        self.state = {
            symbol: {
                "price": float(config.get("initial_price", {}).get(symbol, self._default_price(symbol))),
                "phase": self.random.uniform(0.0, math.pi),
            }
            for symbol in self.symbols
        }

    def _default_price(self, symbol: str) -> float:
        return 3800.0 if symbol.endswith("CCFX") else 4.8

    def stream(self) -> Iterable[Tick]:
        while True:
            for symbol in self.symbols:
                snapshot = self.state[symbol]
                snapshot["phase"] += 0.17
                drift = 0.0008 if symbol.endswith(".SH") else 0.0012
                wave = math.sin(snapshot["phase"]) * 0.012
                noise = self.random.uniform(-0.006, 0.006)
                move = drift + wave + noise
                snapshot["price"] = max(0.5, snapshot["price"] * (1 + move))
                volume = 120_000 * (1 + abs(wave) * 20 + self.random.random() * 5)
                spread = max(snapshot["price"] * (0.0004 if symbol.endswith(".SH") else 0.0008), 0.002)
                yield self._build_tick(
                    symbol,
                    snapshot["price"],
                    volume,
                    bid_price=snapshot["price"] - spread / 2,
                    ask_price=snapshot["price"] + spread / 2,
                )
            # 为了与其他数据源保持一致，添加一个小延迟
            poll_interval = float(self.config.get("poll_interval_seconds", 0.1))
            if poll_interval > 0:
                import time
                time.sleep(poll_interval)


class CsvReplayMarketFeed(BaseMarketFeed):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.path = Path(str(config.get("path", "")))
        if not self.path.exists():
            raise FileNotFoundError(f"CSV market data file not found: {self.path}")
        self.replay_interval_seconds = max(0.0, float(config.get("replay_interval_seconds", 0.0)))
        self.price_field = str(config.get("price_field", "price"))
        self.volume_field = str(config.get("volume_field", "volume"))
        self.symbol_field = str(config.get("symbol_field", "symbol"))

    def stream(self) -> Iterable[Tick]:
        with self.path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = list(reader)
        if not rows:
            raise RuntimeError(f"CSV market data file is empty: {self.path}")
        for row in rows:
            normalized = {str(key).strip().lower(): value for key, value in row.items()}
            symbol = str(normalized.get(self.symbol_field.lower(), "")).strip()
            if not symbol:
                continue
            if self.symbols and symbol not in self.symbols:
                continue
            price = _as_float(normalized.get(self.price_field.lower()), default=0.0)
            volume = _as_float(normalized.get(self.volume_field.lower()), default=0.0)
            if price <= 0:
                continue
            yield self._build_tick(symbol, price, volume)
            if self.replay_interval_seconds > 0:
                time.sleep(self.replay_interval_seconds)


class TushareRealtimeMarketFeed(BaseMarketFeed):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.original_symbols = list(self.symbols)
        self.symbols = _filter_tushare_symbols(self.symbols)
        if not self.symbols:
            raise ValueError("tushare_realtime requires at least one symbol")
        self.poll_interval_seconds = max(0.0, float(config.get("poll_interval_seconds", 15.0)))
        token_env = str(config.get("token_env", "TUSHARE_TOKEN"))
        self.token = str(config.get("token") or os.getenv(token_env) or "").strip()
        self._ts_module = None
        self.fallback_provider = str(config.get("fallback_provider", "easyquotation")).strip().lower()
        self._fallback_quote = None

    def _get_tushare(self):
        if self._ts_module is not None:
            return self._ts_module
        try:
            import tushare as ts
        except ImportError as exc:  # pragma: no cover - depends on local environment
            raise RuntimeError(
                "tushare_realtime 需要安装 tushare 包；请先 `pip install tushare`。"
            ) from exc
        if not self.token:
            raise RuntimeError("tushare_realtime 缺少 token；请配置 token 或设置 TUSHARE_TOKEN 环境变量。")
        os.environ["TUSHARE_TOKEN"] = self.token
        os.environ["TS_TOKEN"] = self.token
        self._ts_module = ts
        return ts

    def _fetch_rows(self) -> list[dict[str, Any]]:
        ts = self._get_tushare()
        quote_frame = ts.realtime_quote(ts_code=",".join(self.symbols))
        if quote_frame is None:
            return []
        if hasattr(quote_frame, "empty") and quote_frame.empty:
            return []
        if hasattr(quote_frame, "to_dict"):
            return list(quote_frame.to_dict("records"))
        return list(quote_frame)

    def _get_easyquotation(self):
        if self._fallback_quote is not None:
            return self._fallback_quote
        try:
            import easyquotation
        except ImportError as exc:  # pragma: no cover - depends on local environment
            raise RuntimeError(
                "fallback_provider=easyquotation 需要安装 easyquotation；请先 `pip install easyquotation`。"
            ) from exc
        self._fallback_quote = easyquotation.use("sina")
        return self._fallback_quote

    def _fetch_rows_from_fallback(self) -> list[dict[str, Any]]:
        if self.fallback_provider != "easyquotation":
            return []
        fallback_symbols = _filter_easyquotation_symbols(self.symbols)
        if not fallback_symbols:
            return []
        codes = [_to_easyquotation_code(symbol) for symbol in fallback_symbols]
        quote = self._get_easyquotation()
        payload = _fetch_easyquotation_payload(quote, codes)
        rows: list[dict[str, Any]] = []
        for symbol in fallback_symbols:
            fallback_key = _easyquotation_key(symbol)
            detail = payload.get(fallback_key)
            if not detail:
                continue
            rows.append(
                {
                    "ts_code": symbol,
                    "price": detail.get("now") or detail.get("close") or detail.get("open"),
                    "volume": detail.get("volume") or detail.get("turnover") or 0.0,
                }
            )
        return rows

    def stream(self) -> Iterable[Tick]:
        while True:
            try:
                rows = self._fetch_rows()
            except Exception as exc:
                LOGGER.warning(
                    "Tushare realtime fetch failed, switching to fallback provider",
                    extra={"provider": self.fallback_provider, "error": str(exc)},
                )
                rows = self._fetch_rows_from_fallback()
            emitted = 0
            for row in rows:
                normalized = {str(key).strip().lower(): value for key, value in row.items()}
                symbol = str(
                    normalized.get("ts_code")
                    or normalized.get("symbol")
                    or normalized.get("code")
                    or ""
                ).strip()
                price = _first_float(normalized, ["price", "current", "close", "last", "bid1"], default=0.0)
                volume = _first_float(normalized, ["vol", "volume", "amount"], default=0.0)
                bid_price = _first_float(normalized, ["bid1", "b1_p", "bid_price", "buy1"], default=0.0)
                ask_price = _first_float(normalized, ["ask1", "a1_p", "ask_price", "sell1"], default=0.0)
                if not symbol or price <= 0:
                    continue
                emitted += 1
                yield self._build_tick(symbol, price, volume, bid_price=bid_price, ask_price=ask_price)
            if emitted == 0:
                raise RuntimeError("tushare_realtime 没有返回有效行情，请检查 symbol 或 token 配置。")
            if self.poll_interval_seconds > 0:
                time.sleep(self.poll_interval_seconds)


class EasyQuotationRealtimeMarketFeed(BaseMarketFeed):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.original_symbols = list(self.symbols)
        self.symbols = _filter_easyquotation_symbols(self.symbols)
        if not self.symbols:
            raise ValueError("easyquotation_realtime requires at least one symbol")
        self.poll_interval_seconds = max(0.0, float(config.get("poll_interval_seconds", 15.0)))
        self.provider = str(config.get("provider", "sina")).strip().lower()
        self._quote = None

    def _get_quote(self):
        if self._quote is not None:
            return self._quote
        try:
            import easyquotation
        except ImportError as exc:  # pragma: no cover - depends on local environment
            raise RuntimeError(
                "easyquotation_realtime 需要安装 easyquotation；请先 `pip install easyquotation`。"
            ) from exc
        self._quote = easyquotation.use(self.provider)
        return self._quote

    def _fetch_rows(self) -> list[dict[str, Any]]:
        quote = self._get_quote()
        codes = [_to_easyquotation_code(symbol) for symbol in self.symbols]
        payload = _fetch_easyquotation_payload(quote, codes)
        rows: list[dict[str, Any]] = []
        for symbol in self.symbols:
            detail = payload.get(_easyquotation_key(symbol))
            if not detail:
                continue
            rows.append(
                {
                    "ts_code": symbol,
                    "price": detail.get("now") or detail.get("close") or detail.get("open"),
                    "volume": detail.get("volume") or detail.get("turnover") or 0.0,
                }
            )
        return rows

    def stream(self) -> Iterable[Tick]:
        while True:
            rows = self._fetch_rows()
            emitted = 0
            for row in rows:
                normalized = {str(key).strip().lower(): value for key, value in row.items()}
                symbol = str(normalized.get("ts_code") or normalized.get("symbol") or normalized.get("code") or "").strip()
                price = _first_float(normalized, ["price", "current", "close", "last", "bid1"], default=0.0)
                volume = _first_float(normalized, ["vol", "volume", "amount"], default=0.0)
                bid_price = _first_float(normalized, ["bid1", "b1_p", "bid_price", "buy1"], default=0.0)
                ask_price = _first_float(normalized, ["ask1", "a1_p", "ask_price", "sell1"], default=0.0)
                if not symbol or price <= 0:
                    continue
                emitted += 1
                yield self._build_tick(symbol, price, volume, bid_price=bid_price, ask_price=ask_price)
            if emitted == 0:
                raise RuntimeError("easyquotation_realtime 没有返回有效行情，请检查 symbol 或 provider 配置。")
            if self.poll_interval_seconds > 0:
                time.sleep(self.poll_interval_seconds)


class MarketDataFeed(BaseFeed):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        feed_type = str(config.get("type", "synthetic_cn")).strip().lower()
        if feed_type == "synthetic_cn":
            self.impl: BaseFeed = SyntheticMarketDataFeed(config)
        elif feed_type == "csv_replay":
            self.impl = CsvReplayMarketFeed(config)
        elif feed_type == "tushare_realtime":
            self.impl = TushareRealtimeMarketFeed(config)
        elif feed_type == "easyquotation_realtime":
            self.impl = EasyQuotationRealtimeMarketFeed(config)
        else:
            raise ValueError(f"Unsupported market feed type: {feed_type}")

    def stream(self) -> Iterable[Tick]:
        return self.impl.stream()


class StaticFundamentalFeed(BaseFeed):
    def stream(self) -> Iterable[dict[str, float]]:
        fields = self.config.get("fields", ["roe", "pe_ttm"])
        yield {
            field: round(1.0 + idx * 0.8, 3)
            for idx, field in enumerate(fields)
        }


class FundamentalFeed(BaseFeed):
    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.impl = StaticFundamentalFeed(config)
        feed_type = str(config.get("type", "static")).strip().lower()
        if feed_type == "tushare":
            LOGGER.warning("FundamentalFeed.tushare 暂未接入真实财务接口，当前退回静态骨架。")

    def stream(self) -> Iterable[dict[str, float]]:
        return self.impl.stream()


class SentimentFeed(BaseFeed):
    def stream(self) -> Iterable[dict[str, float]]:
        yield {
            "sentiment_score": 0.58,
            "headline_impact": 0.42,
        }


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _as_float(value: Any, *, default: float = 0.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_float(row: dict[str, Any], keys: list[str], *, default: float = 0.0) -> float:
    for key in keys:
        value = _as_float(row.get(key), default=float("nan"))
        if not math.isnan(value):
            return value
    return default


def _to_easyquotation_code(symbol: str) -> str:
    if "." not in symbol:
        return symbol
    code, market = symbol.split(".", 1)
    market = market.upper()
    if market in {"SH", "SSE"}:
        return f"sh{code}"
    if market in {"SZ", "SZSE"}:
        return f"sz{code}"
    return code


def _easyquotation_key(symbol: str) -> str:
    if "." not in symbol:
        return symbol
    code, _ = symbol.split(".", 1)
    return code


def _filter_tushare_symbols(symbols: list[str]) -> list[str]:
    supported_markets = {"SH", "SSE", "SZ", "SZSE"}
    filtered: list[str] = []
    for symbol in symbols:
        if "." not in symbol:
            filtered.append(symbol)
            continue
        _, market = symbol.split(".", 1)
        if market.upper() in supported_markets:
            filtered.append(symbol)
    return filtered


def _filter_easyquotation_symbols(symbols: list[str]) -> list[str]:
    supported_markets = {"SH", "SSE", "SZ", "SZSE"}
    filtered: list[str] = []
    for symbol in symbols:
        if "." not in symbol:
            if symbol.isdigit():
                filtered.append(symbol)
            continue
        _, market = symbol.split(".", 1)
        if market.upper() in supported_markets:
            filtered.append(symbol)
    return filtered


def _fetch_easyquotation_payload(quote: Any, codes: list[str]) -> dict[str, Any]:
    if not codes:
        return {}
    if not (
        hasattr(quote, "gen_stock_list")
        and hasattr(quote, "get_stocks_by_range")
        and hasattr(quote, "format_response_data")
    ):
        return quote.stocks(codes)
    requests = quote.gen_stock_list(codes)
    responses: list[str] = []
    for request_args in requests:
        payload = quote.get_stocks_by_range(request_args)
        if payload:
            responses.append(payload)
    return quote.format_response_data(responses, prefix=False)
