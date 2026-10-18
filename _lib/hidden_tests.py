"""Run a worker item's hidden tests against a set of files in a fresh temp dir."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

HIDDEN_DIR = "_hidden_tests"


def run_hidden_tests(files: dict[str, str], hidden: str, timeout_s: int = 120) -> tuple[bool, str]:
    """Write `files` to a fresh temp dir and run the hidden tests against them."""
    with tempfile.TemporaryDirectory() as tmp:
        for path, src in files.items():
            dest = Path(tmp, path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(src, encoding="utf-8")
        Path(tmp, HIDDEN_DIR).mkdir()
        Path(tmp, HIDDEN_DIR, "test_hidden.py").write_text(hidden, encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": tmp, "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               "--rootdir", tmp, HIDDEN_DIR], cwd=tmp, env=env,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout_s)
        return proc.returncode == 0, (proc.stdout + proc.stderr)[-2000:]
