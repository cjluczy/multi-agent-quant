from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from ..shared.logging import get_logger

LOGGER = get_logger(__name__)


@dataclass
class LLMTask:
    prompt: str
    context: Dict[str, float]
    task_type: str = "analysis"


class LLMRouter:
    def __init__(self, cfg: dict):
        self.default = cfg.get("default", "qwen2.5:32b")
        self.fallbacks: List[str] = cfg.get("fallbacks", [])

    def run(self, tasks: Iterable[LLMTask]) -> List[str]:
        responses = []
        for task in tasks:
            LOGGER.info("Routing LLM task", extra={"type": task.task_type})
            content = (
                f"[{self.default}] summarizing {task.task_type}: {task.prompt[:80]}"
            )
            responses.append(content)
        return responses
