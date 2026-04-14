import sys
from pathlib import Path
from types import SimpleNamespace

from multi_agent_quant.data_layer.feeds import MarketDataFeed


def test_csv_replay_market_feed_imports_real_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / "ticks.csv"
    csv_path.write_text(
        "symbol,price,volume\n"
        "510300.SH,3.85,100000\n"
        "510300.SH,3.88,120000\n"
        "600519.SH,1492.5,3000\n",
        encoding="utf-8",
    )

    feed = MarketDataFeed(
        {
            "type": "csv_replay",
            "path": str(csv_path),
            "symbols": ["510300.SH", "600519.SH"],
            "feature_window": 5,
        }
    )

    stream = feed.stream()
    first = next(stream)
    second = next(stream)
    third = next(stream)

    assert first.symbol == "510300.SH"
    assert first.price == 3.85
    assert second.symbol == "510300.SH"
    assert second.features["momentum"] > 0.5
    assert third.symbol == "600519.SH"
    assert third.volume == 3000.0


def test_tushare_realtime_market_feed_builds_ticks(monkeypatch) -> None:
    class FakeFrame:
        empty = False

        def to_dict(self, orient: str):
            assert orient == "records"
            return [
                {"TS_CODE": "510300.SH", "PRICE": "3.91", "VOLUME": "123456"},
                {"TS_CODE": "600519.SH", "PRICE": "1500.50", "VOLUME": "4321"},
            ]

    fake_tushare = SimpleNamespace(
        set_token=lambda token: token,
        realtime_quote=lambda ts_code: FakeFrame(),
    )
    monkeypatch.setitem(sys.modules, "tushare", fake_tushare)

    feed = MarketDataFeed(
        {
            "type": "tushare_realtime",
            "symbols": ["510300.SH", "600519.SH"],
            "token": "demo-token",
            "poll_interval_seconds": 0,
            "feature_window": 5,
        }
    )

    stream = feed.stream()
    first = next(stream)
    second = next(stream)

    assert first.symbol == "510300.SH"
    assert first.price == 3.91
    assert second.symbol == "600519.SH"
    assert second.price == 1500.5


def test_tushare_realtime_market_feed_falls_back_to_easyquotation(monkeypatch) -> None:
    class FailingTushare:
        @staticmethod
        def set_token(token: str) -> str:
            return token

        @staticmethod
        def realtime_quote(ts_code: str):
            raise RuntimeError("tushare unavailable")

    class FakeQuotation:
        def stocks(self, stock_codes, prefix=False):
            assert prefix is False
            assert "sh510300" in stock_codes
            return {
                "510300": {
                    "now": 4.57,
                    "volume": 3509938019.0,
                }
            }

    class FakeEasyQuotationModule:
        @staticmethod
        def use(name: str):
            assert name == "sina"
            return FakeQuotation()

    monkeypatch.setitem(sys.modules, "tushare", FailingTushare())
    monkeypatch.setitem(sys.modules, "easyquotation", FakeEasyQuotationModule())

    feed = MarketDataFeed(
        {
            "type": "tushare_realtime",
            "symbols": ["510300.SH"],
            "token": "demo-token",
            "poll_interval_seconds": 0,
            "fallback_provider": "easyquotation",
            "feature_window": 5,
        }
    )

    tick = next(feed.stream())

    assert tick.symbol == "510300.SH"
    assert tick.price == 4.57
    assert tick.volume == 3509938019.0


def test_easyquotation_realtime_market_feed_builds_ticks(monkeypatch) -> None:
    class FakeQuotation:
        def stocks(self, stock_codes, prefix=False):
            assert prefix is False
            assert "sh510300" in stock_codes
            return {
                "510300": {
                    "now": 4.58,
                    "volume": 123456789.0,
                },
                "600519": {
                    "now": 1499.88,
                    "volume": 4567.0,
                },
            }

    class FakeEasyQuotationModule:
        @staticmethod
        def use(name: str):
            assert name == "sina"
            return FakeQuotation()

    monkeypatch.setitem(sys.modules, "easyquotation", FakeEasyQuotationModule())

    feed = MarketDataFeed(
        {
            "type": "easyquotation_realtime",
            "provider": "sina",
            "symbols": ["510300.SH", "600519.SH"],
            "poll_interval_seconds": 0,
            "feature_window": 5,
        }
    )

    stream = feed.stream()
    first = next(stream)
    second = next(stream)

    assert first.symbol == "510300.SH"
    assert first.price == 4.58
    assert second.symbol == "600519.SH"
    assert second.price == 1499.88
