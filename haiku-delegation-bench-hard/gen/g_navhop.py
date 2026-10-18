"""nav-multihop: follow a chain of two or three lookups across files of a real
repository (a caller to its helper to a config default, a constant to the
places that use it), with Read, Grep and Glob.

The scout runs inside a clean checkout of a public repository pinned to one
commit. Every gold value is asserted against that checkout when the items are
built: a line must hold the expected text, set-valued gold is recomputed from
the source with `ast`, and each unanswerable question's subject is asserted
absent with `git grep`. Each question has traps one hop away (another
backend's breaker, a docstring's rounder number, a bound for a different
field), but the gold never depends on reading intent into a comment.

Gold is {"fields": {name: {"kind": ..., "value": ...}}}; the first field is the
one an unanswerable item expects NOT_FOUND in."""
from __future__ import annotations

import ast
import subprocess

from common import NAV_REPO_DIR, NAV_REPO_SHA, item, json_contract

CAT = "nav-multihop"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(NAV_REPO_DIR), *args], capture_output=True,
                          text=True, encoding="utf-8")


def _lines(path: str) -> list[str]:
    return (NAV_REPO_DIR / path).read_text(encoding="utf-8").split("\n")


def _line(qid: str, path: str, line: int, needle: str) -> None:
    text = _lines(path)
    assert needle in text[line - 1], f"{qid}: {path}:{line} is {text[line - 1]!r}"


def _absent(qid: str, pattern: str, path: str | None = None, icase: bool = False) -> None:
    # Tests stdout, not the exit code: git grep exits 1 both for "no match" and
    # for some errors, and an empty match list is the claim being checked.
    args = ["grep", "-n"] + (["-i"] if icase else []) + ["-e", pattern]
    if path:
        args += ["--", path]
    res = _git(*args)
    assert res.returncode in (0, 1), f"{qid}: git grep failed: {res.stderr}"
    assert not res.stdout.strip(), f"{qid}: {pattern!r} is not absent:\n{res.stdout}"


def _literal(path: str, name: str) -> tuple[object, int]:
    """Value and line of a module-level `name = <literal>` (a set, tuple, or
    frozenset({...}) call), read with ast so the gold is never typed by hand."""
    tree = ast.parse((NAV_REPO_DIR / path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            v = node.value
            if (isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                    and v.func.id in ("frozenset", "set") and len(v.args) == 1):
                v = v.args[0]
            return ast.literal_eval(v), node.lineno
    raise AssertionError(f"{path}: no module-level literal {name}")


def _f(kind: str, value=None) -> dict:
    return {"kind": kind, "value": value}


def _nf(first: str) -> str:
    return (f" If the setting, symbol or value asked about does not exist in this "
            f'repository, put "NOT_FOUND" in `{first}` and null in the other fields.')


def _ext_list(exts) -> list[str]:
    return sorted({e.lower() for e in exts})


# ── Answerable chains ────────────────────────────────────────────────────────

def h01() -> tuple:
    q = ("c3_delegate wraps each backend in a runtime circuit breaker. For the claude "
         "backend, on a project whose .c3/config.json sets no delegate options, after how "
         "many consecutive failures does the breaker trip, and for how many seconds does "
         "it stay open? Name the function that creates the breaker, and give its file and "
         "the line of its def.")
    shape = ('{"failures": <integer>, "cooldown_seconds": <integer>, "function": "<name>", '
             '"file": "<repo-relative path>", "line": <integer>}')
    # The caller (enabled by default, config.py line 298) asks for the claude breaker
    # with the merged delegate config...
    _line("H01", "core/config.py", 298, '"claude_enabled": True,')
    _line("H01", "cli/tools/delegate.py", 804, 'breaker = _backend_breaker("claude", dcfg)')
    _line("H01", "core/config.py", 342, "return {**DELEGATE_DEFAULTS, **delegate}")
    # ...whose shipped defaults carry no breaker keys, so the helper's fallbacks apply.
    _absent("H01", "breaker_failure_threshold", "core/config.py")
    _absent("H01", "breaker_cooldown_seconds", "core/config.py")
    _line("H01", "cli/tools/delegate.py", 1739, "def _backend_breaker(")
    _line("H01", "cli/tools/delegate.py", 1747, 'cfg.get("breaker_failure_threshold", 3) or 3')
    _line("H01", "cli/tools/delegate.py", 1748, 'cfg.get("breaker_cooldown_seconds", 60) or 60')
    # Trap: the memory distiller's breaker (2 failures, 300 s).
    _line("H01", "services/memory_distiller.py", 101,
          "def __init__(self, threshold: int = 2, cooldown_sec: int = 300):")
    gold = {"failures": _f("int", 3), "cooldown_seconds": _f("int", 60),
            "function": _f("str", "_backend_breaker"),
            "file": _f("path", "cli/tools/delegate.py"), "line": _f("line", 1739)}
    return q + _nf("failures"), shape, gold, ("caller-helper-default", "trap-other-breaker")


def h02() -> tuple:
    q = ("On a project whose .c3/config.json sets no delegate options, c3_delegate is "
         "called with backend='claude' and no tier, model, scout or write_paths. Which "
         "model alias does it pass to the claude CLI's --model? Which alias does it pass "
         "for the same call with scout=true? Give the file and line of the config default "
         "whose value ends up deciding the tier of the first (plain) call.")
    shape = ('{"plain_alias": "<alias>", "scout_alias": "<alias>", '
             '"file": "<repo-relative path>", "line": <integer>}')
    _line("H02", "cli/tools/delegate.py", 544,
          'return "claude_scout_default_tier" if scout else "claude_default_tier"')
    _line("H02", "cli/tools/delegate.py", 305, "def normalize_tier(")
    _line("H02", "cli/tools/delegate.py", 308, "raw = (tier or (dcfg.get(default_key)")
    _line("H02", "cli/tools/delegate.py", 309, 'or dcfg.get("default_tier") or "small")')
    # claude_default_tier is empty, so the plain call falls through to default_tier.
    _line("H02", "core/config.py", 299, '"claude_default_tier": "",')
    _line("H02", "core/config.py", 290, '"default_tier": "small",')
    _line("H02", "core/config.py", 300, '"claude_scout_default_tier": "medium",')
    _line("H02", "core/config.py", 303,
          '"claude_tier_models": {"small": "haiku", "medium": "sonnet", "large": "opus"}')
    gold = {"plain_alias": _f("str", "haiku"), "scout_alias": _f("str", "sonnet"),
            "file": _f("path", "core/config.py"), "line": _f("line", 290)}
    return q + _nf("plain_alias"), shape, gold, ("fallthrough-default", "three-hop")


def h03() -> tuple:
    q = ("In C3's scheduled-task store, every run status is either open or terminal, and "
         "some statuses count as executed (the task's command actually ran). Which "
         "terminal run statuses do not count as executed? List them, and give the file "
         "and line where the set of terminal statuses is defined.")
    shape = ('{"statuses": [<status strings>], "file": "<repo-relative path>", '
             '"line": <integer>}')
    path = "services/schedule_store.py"
    run, _ = _literal(path, "RUN_STATUSES")
    open_, _ = _literal(path, "OPEN_RUN_STATUSES")
    executed, _ = _literal(path, "EXECUTED_STATUSES")
    _line("H03", path, 49,
          "TERMINAL_RUN_STATUSES = frozenset(RUN_STATUSES) - OPEN_RUN_STATUSES")
    want = sorted(set(run) - set(open_) - set(executed))
    assert want == sorted({"skipped_overlap", "missed", "check_skipped", "denied",
                           "expired"}), f"H03: computed {want}"
    gold = {"statuses": _f("set", want), "file": _f("path", path), "line": _f("line", 49)}
    return q + _nf("statuses"), shape, gold, ("set-arithmetic",)


def h04() -> tuple:
    q = ("C3 keeps two hand-written lists of code-file extensions: the one the file "
         "watcher reacts to, and the one file memory extracts structure from. Which "
         "extensions are in file memory's list but not the watcher's, and which are in "
         "the watcher's but not file memory's? Give the file and line where the "
         "watcher's list is defined.")
    shape = ('{"only_file_memory": [<extensions>], "only_watcher": [<extensions>], '
             '"file": "<repo-relative path>", "line": <integer>}')
    watcher, w_line = _literal("services/watcher.py", "CODE_EXTENSIONS")
    fmem, _ = _literal("services/file_memory.py", "CODE_EXTENSIONS")
    _line("H04", "services/watcher.py", 95, "if p.suffix.lower() not in CODE_EXTENSIONS:")
    only_f = _ext_list({e.lower() for e in fmem} - {e.lower() for e in watcher})
    only_w = _ext_list({e.lower() for e in watcher} - {e.lower() for e in fmem})
    assert w_line == 21, f"H04: watcher list at line {w_line}"
    assert only_f == [".cs", ".htm", ".rb"] and only_w == [".sh", ".sql"], (only_f, only_w)
    gold = {"only_file_memory": _f("set", only_f), "only_watcher": _f("set", only_w),
            "file": _f("path", "services/watcher.py"), "line": _f("line", 21)}
    return q + _nf("only_file_memory"), shape, gold, ("two-files", "set-arithmetic")


def h05() -> tuple:
    q = ("C3's prompt-recall hook adds possibly relevant project facts to each prompt. On "
         "a project whose .c3/config.json has no memory_llm section, what is the most "
         "facts it adds to one prompt, how many characters is the injected block capped "
         "at in total, and to how many characters is each fact's text cut? Give the file "
         "and line where the total cap is computed.")
    shape = ('{"max_facts": <integer>, "total_chars": <integer>, "per_fact_chars": '
             '<integer>, "file": "<repo-relative path>", "line": <integer>}')
    path = "cli/hook_prompt_recall.py"
    _line("H05", path, 52, 'mem_cfg = cfg.get("memory_llm", {})')
    _line("H05", path, 53, 'if not mem_cfg.get("prompt_inject_enabled", True):')
    _line("H05", path, 79, 'int(mem_cfg.get("inject_top_k", 4))')
    _line("H05", path, 80, 'max_chars = int(mem_cfg.get("inject_max_tokens", 400)) * 4')
    _line("H05", path, 19, "_LINE_CAP = 220")
    _line("H05", path, 87, '[:_LINE_CAP]')
    gold = {"max_facts": _f("int", 4), "total_chars": _f("int", 400 * 4),
            "per_fact_chars": _f("int", 220), "file": _f("path", path),
            "line": _f("line", 80)}
    return q + _nf("max_facts"), shape, gold, ("unit-conversion", "trap-tokens")


H06_CANDIDATES = [".ps1", ".lua", ".proto", ".vue", ".ipynb", ".tsv", ".kt", ".gradle",
                  ".svelte", ".txt"]


def h06() -> tuple:
    q = ("On a project with default configuration, c3_search's `files` and `exact` "
         "actions walk a fixed set of file extensions. Which of these extensions are in "
         "that set, and which are skipped: " + ", ".join(H06_CANDIDATES) + "? Give the "
         "file and line where the extension set is defined.")
    shape = ('{"included": [<extensions>], "skipped": [<extensions>], '
             '"file": "<repo-relative path>", "line": <integer>}')
    exts, line = _literal("services/indexer.py", "DEFAULT_CODE_EXTS")
    assert line == 63, f"H06: DEFAULT_CODE_EXTS at line {line}"
    _line("H06", "cli/tools/search.py", 17, "from services.indexer import DEFAULT_CODE_EXTS")
    _line("H06", "cli/tools/search.py", 224, 'exts = getattr(indexer, "code_exts", None)')
    _line("H06", "cli/tools/search.py", 226, "exts = DEFAULT_CODE_EXTS")
    _line("H06", "services/indexer.py", 176, "self.code_exts = set(DEFAULT_CODE_EXTS)")
    lower = {e.lower() for e in exts}
    inc = sorted(e for e in H06_CANDIDATES if e in lower)
    skip = sorted(e for e in H06_CANDIDATES if e not in lower)
    assert inc == sorted([".ps1", ".lua", ".proto", ".vue", ".kt", ".svelte"]), inc
    gold = {"included": _f("set", inc), "skipped": _f("set", skip),
            "file": _f("path", "services/indexer.py"), "line": _f("line", 63)}
    return q + _nf("included"), shape, gold, ("import-chain", "membership")


def h07() -> tuple:
    q = ("C3's memory distiller trips a breaker when an LLM tier keeps failing. With "
         "shipped defaults (no memory_llm overrides), after how many consecutive failures "
         "does the breaker open, for how many seconds does it stay open, and what "
         "queue_max_attempts value does the distiller read? Give the file and line where "
         "the distiller constructs its breaker.")
    shape = ('{"failure_threshold": <integer>, "cooldown_seconds": <integer>, '
             '"queue_max_attempts": <integer>, "file": "<repo-relative path>", '
             '"line": <integer>}')
    path = "services/memory_distiller.py"
    _line("H07", "services/runtime.py", 293, "memory_distiller = MemoryDistiller(")
    _line("H07", "core/config.py", 345, "def load_memory_llm_config(")
    _line("H07", "core/config.py", 179, '"queue_max_attempts": 3,')
    _line("H07", "core/config.py", 180, '"breaker_cooldown_sec": 300,')
    _line("H07", path, 134, "self.breaker = DistillerBreaker(")
    _line("H07", path, 135, 'threshold=2, cooldown_sec=self.config.get("breaker_cooldown_sec", 300))')
    _line("H07", path, 226, 'int(self.config.get("queue_max_attempts", 3))')
    gold = {"failure_threshold": _f("int", 2), "cooldown_seconds": _f("int", 300),
            "queue_max_attempts": _f("int", 3), "file": _f("path", path),
            "line": _f("line", 134)}
    return q + _nf("failure_threshold"), shape, gold, ("hardcoded-vs-config",
                                                        "trap-other-breaker")


def h08() -> tuple:
    q = ("A scheduled task is created through the c3_schedule MCP tool on a machine with "
         "the shipped Oracle config. What is the smallest timeout_s the store accepts, "
         "what timeout_s is stored when the call gives none, and what is the largest "
         "accepted? Give the file and line where the smallest accepted value is defined.")
    shape = ('{"min_timeout_s": <integer>, "default_timeout_s": <integer>, '
             '"max_timeout_s": <integer>, "file": "<repo-relative path>", '
             '"line": <integer>}')
    store = "services/schedule_store.py"
    _line("H08", "cli/tools/schedule.py", 26, "def _defaults() -> dict:")
    _line("H08", "cli/tools/schedule.py", 29, "return defaults_from_config(load_config())")
    _line("H08", "cli/tools/schedule.py", 135, "row = store.create(fields, defaults=_defaults()")
    _line("H08", "oracle/services/scheduler.py", 37,
          '"timeout_s": int(cfg.get("scheduler_default_timeout_s", 1800)),')
    _line("H08", "oracle/services/scheduler.py", 38,
          '"max_timeout_s": int(cfg.get("scheduler_max_timeout_s", 21600)),')
    _line("H08", "oracle/config.py", 74, '"scheduler_default_timeout_s": 1800,')
    _line("H08", "oracle/config.py", 75, '"scheduler_max_timeout_s": 21600,')
    _line("H08", store, 52, "MIN_TIMEOUT_S = 30")
    _line("H08", store, 207, 'timeout_s = _int_in(row.get("timeout_s", d.get("timeout_s", '
          'DEFAULT_TIMEOUT_S)),')
    _line("H08", store, 208, 'MIN_TIMEOUT_S, int(d.get("max_timeout_s", MAX_TIMEOUT_S))')
    _line("H08", store, 267, "if number < lo or number > hi:")
    gold = {"min_timeout_s": _f("int", 30), "default_timeout_s": _f("int", 1800),
            "max_timeout_s": _f("int", 21600), "file": _f("path", store),
            "line": _f("line", 52)}
    return q + _nf("min_timeout_s"), shape, gold, ("three-hop", "trap-other-bound")


# ── Unanswerable near misses ─────────────────────────────────────────────────

def n01() -> tuple:
    q = ("What is the shipped default of c3_delegate's claude_scout_max_turns config key "
         "(the --max-turns limit for claude scout runs)? Give the file and line where "
         "that default is set.")
    shape = ('{"max_turns": <integer>, "file": "<repo-relative path>", "line": <integer>}')
    for pat in ("claude_scout_max_turns", "claude_max_turns", "scout_max_turns"):
        _absent("N1", pat)
    # Near misses the scout will meet: Grok's turn cap and the claude scout timeout.
    _line("N1", "core/config.py", 284, '"grok_max_turns": 8,')
    _line("N1", "core/config.py", 305, '"claude_scout_timeout": 240,')
    gold = {"max_turns": _f("not_found"), "file": _f("path", None), "line": _f("line", None)}
    return q + _nf("max_turns"), shape, gold, ("unanswerable", "near-miss-key")


def n02() -> tuple:
    q = ("C3's AGENT_DEFAULTS configures each background agent. What interval does it "
         "give the MemoryCompactor agent, and is that agent enabled by default? Give the "
         "file and line of its entry.")
    shape = ('{"interval_seconds": <integer>, "enabled_by_default": <true or false>, '
             '"file": "<repo-relative path>", "line": <integer>}')
    _absent("N2", "MemoryCompactor")
    _absent("N2", "memory_compactor", icase=True)
    _absent("N2", "memorycompactor", icase=True)
    _line("N2", "core/config.py", 106, "AGENT_DEFAULTS = {")
    _line("N2", "core/config.py", 111, '"MemoryPruner": {')
    gold = {"interval_seconds": _f("not_found"), "enabled_by_default": _f("bool", None),
            "file": _f("path", None), "line": _f("line", None)}
    return q + _nf("interval_seconds"), shape, gold, ("unanswerable", "near-miss-name")


CHAINS = [("H01", h01), ("H02", h02), ("H03", h03), ("H04", h04), ("H05", h05),
          ("H06", h06), ("H07", h07), ("H08", h08), ("N1", n01), ("N2", n02)]


def items() -> list[dict]:
    head = _git("rev-parse", "HEAD").stdout.strip()
    assert head == NAV_REPO_SHA, f"fixture repo at {head}, expected {NAV_REPO_SHA}"
    out = []
    for qid, build in CHAINS:
        question, shape, fields, tags = build()
        answerable = next(iter(fields.values()))["kind"] != "not_found"
        out.append(item(qid, CAT, question + json_contract(shape), {"fields": fields},
                        "navhop", task_type="ask", mode="scout", tags=tags,
                        answerable=answerable))
    return out


if __name__ == "__main__":
    for it in items():
        print(it["id"], it["answerable"], list(it["gold"]["fields"]), it["tags"])
