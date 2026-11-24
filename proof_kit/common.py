"""Shared helpers: config loading, running checks, git state. Standard library only, Python 3.9+."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional

CONFIG_NAME = "proof.toml"
STATE_DIR = ".proof"
CHECK_ORDER = ("test", "lint", "types")
TAIL_LINES = 40

DEFAULTS: Dict[str, Any] = {
    "checks": {},
    "stop_hook": {"enabled": True, "max_attempts": 3, "only_if_changed": True, "timeout_seconds": 300},
    # full edition only: the PostToolUse test-tampering guard and the PreToolUse secrets guard
    "guards": {"tamper": True, "secrets": True, "allow_test_changes": False, "secrets_allow": ""},
}


# ---------- hook input ----------

def read_hook_input(stream: Optional[BinaryIO] = None) -> Dict[str, Any]:
    """Parse the hook's JSON from stdin.

    Reads bytes and decodes them as UTF-8, dropping a leading byte-order mark. Windows PowerShell
    adds one when text is piped to a program, and text-mode stdin on Windows would otherwise use
    the locale code page instead of UTF-8. Empty input gives {}; invalid JSON raises ValueError.
    """
    if stream is None:
        stream = sys.stdin.buffer
    text = stream.read().decode("utf-8-sig").strip()
    if not text:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("hook input is not a JSON object")
    return data


# ---------- config ----------

def _parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
        return bytes(raw[1:-1], "utf-8").decode("unicode_escape")
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        return raw[1:-1]
    if raw in ("true", "false"):
        return raw == "true"
    if re.fullmatch(r"[+-]?\d+", raw):
        return int(raw)
    raise ValueError(f"Unsupported value in {CONFIG_NAME}: {raw!r}")


def _strip_comment(line: str) -> str:
    """Remove a trailing # comment that is not inside quotes."""
    quote: Optional[str] = None
    for i, ch in enumerate(line):
        if quote:
            if ch == "\\" and quote == '"':
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def parse_toml(text: str) -> Dict[str, Any]:
    """Tiny TOML subset: [sections], key = "string" | 'string' | int | bool. Enough for proof.toml."""
    try:
        import tomllib  # Python 3.11+

        return tomllib.loads(text)
    except ImportError:
        pass
    data: Dict[str, Any] = {}
    section = data
    for number, line in enumerate(text.splitlines(), start=1):
        line = _strip_comment(line).strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = data.setdefault(line[1:-1].strip(), {})
            continue
        if "=" not in line:
            raise ValueError(f"{CONFIG_NAME} line {number}: expected key = value")
        key, value = line.split("=", 1)
        section[key.strip()] = _parse_value(value)
    return data


def find_root(start: Path) -> Optional[Path]:
    """Walk up from start to the folder containing proof.toml."""
    start = start.resolve()
    for folder in (start, *start.parents):
        if (folder / CONFIG_NAME).is_file():
            return folder
    return None


def load_config(root: Path) -> Dict[str, Any]:
    raw = parse_toml((root / CONFIG_NAME).read_text(encoding="utf-8"))
    config = {key: dict(value) for key, value in DEFAULTS.items()}
    for key, value in raw.items():
        if isinstance(value, dict):
            config.setdefault(key, {}).update(value)
    return config


# ---------- running checks ----------

KEY_LINE = re.compile(
    r"(✖|✗|×|✘|\bFAIL(ED|URES?)?\b|\bfailed\b|\berror\b|Error:|\bassert|"
    r"^\s*(ℹ )?(tests?|pass|fail)\s+\d+|\d+ (passed|failed))", re.I)
KEY_LIMIT = 25
LAST_LINES = 12


def _tail(text: str, lines: int = TAIL_LINES) -> str:
    """Short output: all of it. Long output: the lines that name failures and totals, then the last lines.

    Test runners bury the useful lines between stack traces; this keeps the agent's message (and the
    evidence file) readable without losing which tests failed.
    """
    all_lines = text.strip().splitlines()
    if len(all_lines) <= lines:
        return "\n".join(all_lines)
    key: List[str] = []
    for ln in all_lines[:-LAST_LINES]:
        if KEY_LINE.search(ln) and ln.strip() not in (k.strip() for k in key):
            key.append(ln)
        if len(key) >= KEY_LIMIT:
            break
    last = all_lines[-LAST_LINES:]
    skipped = len(all_lines) - len(last)
    head = key + [f"... ({skipped} lines condensed; showing the last {len(last)}) ..."] if key else \
        [f"... ({skipped} earlier lines not shown) ..."]
    return "\n".join(head + last)


def run_check(name: str, command: str, cwd: Path, timeout: int) -> Dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(
            command, shell=True, cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
        ok, code = proc.returncode == 0, proc.returncode
        output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    except subprocess.TimeoutExpired:
        ok, code, output = False, None, f"Timed out after {timeout} s"
    return {
        "name": name, "command": command, "ok": ok, "exit_code": code,
        "seconds": round(time.monotonic() - started, 1), "tail": _tail(output),
    }


def run_checks(config: Dict[str, Any], root: Path) -> list:
    checks = config.get("checks", {})
    timeout = int(config["stop_hook"].get("timeout_seconds", 300))
    names = [n for n in CHECK_ORDER if checks.get(n)] + [n for n in checks if n not in CHECK_ORDER and checks[n]]
    from .edition import EDITION, FREE_CHECKS
    if EDITION == "free":
        names = [n for n in names if n in FREE_CHECKS]
    return [run_check(n, checks[n], root, timeout) for n in names]


# ---------- git and state ----------

def git_has_changes(root: Path) -> Optional[bool]:
    """True/False if root is in a git repo; None if git isn't available or it's not a repo."""
    try:
        # Scoped to the project folder, so a proof.toml in a subfolder of a bigger repo only sees its own files.
        proc = subprocess.run(["git", "status", "--porcelain", "--", ".", f":(exclude){STATE_DIR}"],
                              cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    lines = [l for l in proc.stdout.splitlines() if l[3:].split("/")[0] != STATE_DIR]
    return bool(lines)


def state_path(root: Path) -> Path:
    return root / STATE_DIR / "state.json"


def load_state(root: Path) -> Dict[str, Any]:
    try:
        return json.loads(state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(root: Path, state: Dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")
