"""Paths and the pinned fixture repository for the generators. Prompt assembly
lives in _lib/c3_prompts.py, shared with haiku-delegation-bench-hard."""
from __future__ import annotations

import sys
from pathlib import Path

BENCH = Path(__file__).resolve().parents[1]
REPO = BENCH.parent
CACHE = REPO / ".cache"

# Public repository the scout items navigate, pinned so gold never drifts.
NAV_REPO_URL = "https://github.com/drknowhow/code-context-control"
NAV_REPO_SHA = "931cb4de72b140a39130e8c7c06a86f25bf6c310"
NAV_REPO_DIR = CACHE / "c3"

sys.path.insert(0, str(REPO / "_lib"))

from c3_prompts import (  # noqa: E402,F401
    C3_TASKS, DELEGATE_SYSTEM, SCOUT_SYSTEM, WORKER_SYSTEM, WORKER_TIMEOUT_S, dump, item,
    json_contract, numbered, worker_prompt)
