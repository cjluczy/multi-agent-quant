#!/usr/bin/env python
"""Check whether realtime or imported market-data configs are ready to run."""
from __future__ import annotations

import argparse
import csv
import importlib.util
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from multi_agent_quant.config import load_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check realtime market-data environment")
    parser.add_argument(
        "--config",
        default="configs/system.realtime.example.yaml",
        help="Path to config file",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = pathlib.Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")

    cfg = load_config(config_path)
    market = cfg.feeds.market.payload()
    feed_type = str(market.get("type", "synthetic_cn")).strip().lower()

    print(f"[OK] config loaded: {config_path}")
    print(f"[INFO] system.mode = {cfg.system.mode}")
    print(f"[INFO] market feed type = {feed_type}")

    if feed_type == "tushare_realtime":
        _check_tushare(market)
    elif feed_type == "easyquotation_realtime":
        _check_easyquotation(market)
    elif feed_type == "csv_replay":
        _check_csv_replay(config_path, market)
    else:
        print("[WARN] current feed is not a real-data feed; this script mainly checks tushare_realtime / easyquotation_realtime / csv_replay.")


def _check_tushare(market: dict[str, object]) -> None:
    module_installed = importlib.util.find_spec("tushare") is not None
    fallback_installed = importlib.util.find_spec("easyquotation") is not None
    token_env = str(market.get("token_env", "TUSHARE_TOKEN"))
    token = str(market.get("token") or os.getenv(token_env) or "").strip()
    symbols = list(market.get("symbols", []))
    fallback_provider = str(market.get("fallback_provider", "easyquotation"))
    supported_symbols = [
        symbol for symbol in symbols
        if "." not in str(symbol) or str(symbol).split(".", 1)[1].upper() in {"SH", "SSE", "SZ", "SZSE"}
    ]
    unsupported_symbols = [symbol for symbol in symbols if symbol not in supported_symbols]

    print(f"[INFO] symbols = {symbols}")
    print(f"[INFO] supported symbols = {supported_symbols}")
    if unsupported_symbols:
        print(f"[WARN] unsupported symbols for tushare_realtime = {unsupported_symbols}")
    print(f"[{'OK' if module_installed else 'FAIL'}] tushare installed = {module_installed}")
    print(f"[{'OK' if bool(token) else 'FAIL'}] token available from config/env = {bool(token)}")
    print(f"[INFO] fallback provider = {fallback_provider}")
    if fallback_provider == "easyquotation":
        print(f"[{'OK' if fallback_installed else 'FAIL'}] easyquotation installed = {fallback_installed}")

    if not symbols:
        print("[FAIL] tushare_realtime requires at least one symbol")
    else:
        print(f"[OK] symbol count = {len(symbols)}")
    if module_installed and token and supported_symbols:
        print("[OK] realtime mode can call Tushare directly")
    elif fallback_provider == "easyquotation" and fallback_installed and supported_symbols:
        print("[WARN] Tushare direct path is incomplete; runtime can fall back to EasyQuotation")
    else:
        print("[FAIL] neither direct Tushare nor fallback path is ready")


def _check_csv_replay(config_path: pathlib.Path, market: dict[str, object]) -> None:
    csv_path = pathlib.Path(str(market.get("path", "")))
    if not csv_path.is_absolute():
        csv_path = (config_path.parent.parent / csv_path).resolve()
    symbol_field = str(market.get("symbol_field", "symbol"))
    price_field = str(market.get("price_field", "price"))
    volume_field = str(market.get("volume_field", "volume"))

    exists = csv_path.exists()
    print(f"[{'OK' if exists else 'FAIL'}] csv path exists = {csv_path}")
    if not exists:
        return

    with csv_path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = [str(name).strip().lower() for name in (reader.fieldnames or [])]
    required = [symbol_field.lower(), price_field.lower(), volume_field.lower()]
    missing = [field for field in required if field not in fieldnames]
    print(f"[INFO] csv columns = {fieldnames}")
    if missing:
        print(f"[FAIL] missing required columns = {missing}")
    else:
        print("[OK] csv schema looks valid")


def _check_easyquotation(market: dict[str, object]) -> None:
    module_installed = importlib.util.find_spec("easyquotation") is not None
    symbols = list(market.get("symbols", []))
    provider = str(market.get("provider", "sina"))

    print(f"[INFO] symbols = {symbols}")
    print(f"[INFO] provider = {provider}")
    print(f"[{'OK' if module_installed else 'FAIL'}] easyquotation installed = {module_installed}")
    if not symbols:
        print("[FAIL] easyquotation_realtime requires at least one symbol")
    else:
        print(f"[OK] symbol count = {len(symbols)}")


if __name__ == "__main__":
    main()
