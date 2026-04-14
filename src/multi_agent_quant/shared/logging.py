from __future__ import annotations

import logging
from logging import Logger


def get_logger(name: str) -> Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    return logging.getLogger(name)
