"""Run one locked-down `claude -p` call and return what it said and what it cost.

Shared by experiments that measure Claude models through the Claude Code CLI
rather than the raw API. The CLI path is what a coding agent's delegation
actually goes through (system prompt, tool definitions, harness overhead), and
it bills against a Claude subscription instead of an API key.

Three modes, copied from the flags C3's `c3_delegate` uses so the benchmark
measures the same call an agent makes in practice:

* ``single``  -- tool-free. ``--safe-mode`` drops CLAUDE.md, skills, plugins,
  hooks, output styles and MCP servers; ``--tools ""`` removes every built-in
  tool. The model sees only the system prompt and the request.
* ``scout``   -- read-only agent. ``--restricted`` ignores user/project/local
  settings (so no hooks, plugins or CLAUDE.md) and confines the file tools to
  the working directory; ``--tools Read,Grep,Glob``.
* ``worker``  -- like scout plus Edit and Write, allowed only on the write set
  (``Edit(./<path>)`` per path; Claude Code's Edit rules cover Write too).
  Under ``dontAsk`` an edit outside the set is refused, as in C3.

Isolation was checked on Claude Code 2.1.302: a control call without these
flags quoted the user's global ~/.claude/CLAUDE.md back; all three modes did
not. See METHODS.md.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field, asdict

# Environment variables that make a child `claude` think it is nested inside a
# parent session, or that would leak the parent's thinking budget into it.
_STRIP_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "MAX_THINKING_TOKENS")

SCOUT_TOOLS = "Read,Grep,Glob"
WORKER_TOOLS = "Read,Grep,Glob,Edit,Write"


@dataclass
class Call:
    ok: bool
    text: str
    model_requested: str
    model_answered: str = ""
    cost_usd: float = 0.0
    input_tokens: int = 0          # uncached + cache-write + cache-read
    output_tokens: int = 0
    thinking_tokens: int = 0
    num_turns: int = 0
    duration_ms: int = 0           # CLI-reported, excludes process start-up
    wall_s: float = 0.0            # includes process start-up
    error: str = ""
    model_usage: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _claude_exe() -> str:
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("`claude` CLI not found on PATH")
    return exe


def build_cmd(mode: str, model: str, system_prompt: str,
              max_budget_usd: float = 0.0, effort: str = "",
              write_paths: list[str] | None = None) -> list[str]:
    cmd = [_claude_exe(), "-p", "--output-format", "json", "--no-session-persistence"]
    if mode == "single":
        cmd += ["--safe-mode", "--strict-mcp-config", "--tools", ""]
    elif mode in ("scout", "worker"):
        tools = SCOUT_TOOLS if mode == "scout" else WORKER_TOOLS
        settings: dict = {}
        if mode == "worker":
            if not write_paths:
                raise ValueError("worker mode needs write_paths")
            settings = {"permissions": {"allow": [f"Edit(./{p})" for p in write_paths]}}
        cmd += ["--restricted", "--strict-mcp-config", "--tools", tools,
                "--permission-mode", "dontAsk", "--settings", json.dumps(settings)]
    else:
        raise ValueError(f"unknown mode {mode!r}")
    cmd += ["--system-prompt", system_prompt, "--model", model]
    if effort:
        cmd += ["--effort", effort]
    if max_budget_usd > 0:
        cmd += ["--max-budget-usd", f"{max_budget_usd:g}"]
    return cmd


def _primary_model(model_usage: dict, requested: str) -> str:
    """The modelUsage entry that answered. Claude Code also spends a little
    Haiku on housekeeping, so the requested alias wins when it matches."""
    if not model_usage:
        return ""
    hits = [n for n in model_usage if requested.lower() in n.lower()]
    if hits:
        return hits[0]
    return max(model_usage, key=lambda n: float(model_usage[n].get("costUSD") or 0))


def run(prompt: str, *, model: str, mode: str = "single", system_prompt: str,
        cwd: str | None = None, timeout_s: int = 600,
        max_budget_usd: float = 0.0, effort: str = "",
        write_paths: list[str] | None = None,
        thinking_cap: int | None = None) -> Call:
    """Send ``prompt`` on stdin and parse the JSON result. Never raises for a
    model-side failure; the Call carries ok=False and the error instead.

    ``thinking_cap`` sets MAX_THINKING_TOKENS for the child, the way C3 caps a
    tier's thinking budget; None leaves the CLI default."""
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
    env.setdefault("PYTHONIOENCODING", "utf-8")
    if thinking_cap is not None:
        env["MAX_THINKING_TOKENS"] = str(thinking_cap)
    cmd = build_cmd(mode, model, system_prompt, max_budget_usd, effort, write_paths)
    t0 = time.monotonic()
    try:
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", cwd=cwd, env=env,
                              timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return Call(ok=False, text="", model_requested=model,
                    wall_s=time.monotonic() - t0, error=f"timeout after {timeout_s}s")
    wall = time.monotonic() - t0
    raw = (proc.stdout or "").strip()
    try:
        data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
    except ValueError:
        return Call(ok=False, text="", model_requested=model, wall_s=wall,
                    error=f"unparseable output (exit {proc.returncode}): "
                          f"{(proc.stderr or raw)[:400]}")
    usage = data.get("usage") or {}
    mu = data.get("modelUsage") or {}
    thinking = sum(int((v or {}).get("thinkingTokens") or 0) for v in mu.values())
    return Call(
        ok=not data.get("is_error") and data.get("subtype") == "success",
        text=str(data.get("result") or ""),
        model_requested=model,
        model_answered=_primary_model(mu, model),
        cost_usd=float(data.get("total_cost_usd") or 0.0),
        input_tokens=sum(int(usage.get(k) or 0) for k in
                         ("input_tokens", "cache_creation_input_tokens",
                          "cache_read_input_tokens")),
        output_tokens=int(usage.get("output_tokens") or 0),
        thinking_tokens=thinking,
        num_turns=int(data.get("num_turns") or 0),
        duration_ms=int(data.get("duration_ms") or 0),
        wall_s=wall,
        error="" if data.get("subtype") == "success" else str(data.get("subtype")),
        model_usage=mu,
    )
