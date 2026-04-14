#!/usr/bin/env python
"""Probe configured market feed and print a few normalized ticks."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from multi_agent_quant.config import load_config
from multi_agent_quant.data_layer.pipelines import DataPipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe a configured market feed")
    parser.add_argument(
        "--config",
        default="configs/system.easyquotation.example.yaml",
        help="Path to config file",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=3,
        help="Number of normalized ticks to print",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = pathlib.Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")

    cfg = load_config(config_path)
    pipeline = DataPipeline(cfg.feeds, poll_interval_seconds=cfg.system.poll_interval_seconds)
    stream = pipeline.stream(max_iterations=max(args.count, 1))

    print(
        json.dumps(
            {
                "config": str(config_path),
                "mode": cfg.system.mode,
                "market_feed_type": cfg.feeds.market.type,
                "symbols": list(cfg.feeds.market.payload().get("symbols", [])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    for index, bundle in enumerate(stream, start=1):
        tick = bundle["market"][0]
        print(
            json.dumps(
                {
                    "index": index,
                    "symbol": tick.symbol,
                    "price": tick.price,
                    "volume": tick.volume,
                    "features": tick.features,
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
