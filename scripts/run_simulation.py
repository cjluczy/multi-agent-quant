#!/usr/bin/env python
"""Convenience runner for end-to-end simulations."""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from multi_agent_quant.main import bootstrap_system


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the multi-agent quant simulation")
    parser.add_argument(
        "--config",
        default="configs/system.example.yaml",
        help="Path to system configuration file",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = pathlib.Path(args.config)
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")

    bootstrap_system(config_path, run_ablation=True)


if __name__ == "__main__":
    sys.exit(main())
