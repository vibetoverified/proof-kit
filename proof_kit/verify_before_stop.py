"""Claude Code Stop hook: block "done" while the project's checks fail.

Claude Code runs this when the agent is about to stop. It reads the hook's JSON on stdin.

Exit codes (Claude Code hook contract):
    0  allow the agent to stop
    2  block stopping; stderr is shown to the agent so it keeps working and fixes the failures

Safety:
    - Only blocks when files changed in the working tree (configurable).
    - Gives up after max_attempts blocked rounds in a session and hands back to the human,
      so it can never trap the agent in a loop.
    - Never crashes the session: any internal error allows the stop and says why.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proof_kit.common import (  # noqa: E402
    STATE_DIR, find_root, git_has_changes, load_config, load_state, read_hook_input, run_checks,
    save_state,
)


def _evidence(results: List[Dict[str, Any]], status: str) -> str:
    lines = [
        "# Proof Kit evidence",
        "",
        f"- Time: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Result: **{status}**",
        "",
        "| Check | Command | Result | Time |",
        "| --- | --- | --- | --- |",
    ]
    for r in results:
        verdict = "pass" if r["ok"] else f"FAIL (exit {r['exit_code']})"
        lines.append(f"| {r['name']} | `{r['command']}` | {verdict} | {r['seconds']} s |")
    for r in results:
        if not r["ok"]:
            lines += ["", f"## {r['name']} output (last lines)", "", "```", r["tail"], "```"]
    return "\n".join(lines) + "\n"


def _write_evidence(root: Path, results: List[Dict[str, Any]], status: str) -> None:
    folder = root / STATE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "last-run.md").write_text(_evidence(results, status), encoding="utf-8")


def _history(root: Path, session: str, status: str, results: List[Dict[str, Any]]) -> None:
    """Append one line per decision to .proof/history.log (an audit trail of every stop attempt)."""
    folder = root / STATE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    failed = ",".join(r["name"] for r in results if not r["ok"]) or "-"
    with (folder / "history.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}\tsession={session}\t{status}\tfailed={failed}\n")


def _failure_message(failed: List[Dict[str, Any]], attempt: int, max_attempts: int) -> str:
    parts = [f"Proof Kit: {len(failed)} check(s) failing, so this task is not done yet "
             f"(round {attempt} of {max_attempts})."]
    for r in failed:
        parts += ["", f"[{r['name']}] `{r['command']}` exited {r['exit_code']}:", r["tail"]]
    parts += ["", "Fix the cause (do not skip, delete or weaken tests), re-run the checks, then finish."]
    return "\n".join(parts)


def decide(hook_input: Dict[str, Any]) -> int:
    start = Path(hook_input.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    root = find_root(start)
    if root is None:
        return 0  # project not set up for Proof Kit

    config = load_config(root)
    hook = config["stop_hook"]
    if not hook.get("enabled", True) or not config.get("checks"):
        return 0

    if hook.get("only_if_changed", True) and git_has_changes(root) is False:
        return 0

    session = str(hook_input.get("session_id") or "default")
    state = load_state(root)
    attempts = int(state.get(session, 0))
    max_attempts = int(hook.get("max_attempts", 3))

    results = run_checks(config, root)
    failed = [r for r in results if not r["ok"]]

    if not failed:
        state.pop(session, None)
        save_state(root, state)
        _write_evidence(root, results, "all checks passed")
        _history(root, session, "passed", results)
        return 0

    if attempts >= max_attempts:
        state.pop(session, None)
        save_state(root, state)
        _write_evidence(root, results, f"still failing after {max_attempts} rounds; handed back to the human")
        _history(root, session, "handed_back", results)
        print(f"Proof Kit: checks still failing after {max_attempts} rounds. "
              f"See {STATE_DIR}/last-run.md.", file=sys.stderr)
        return 0

    state[session] = attempts + 1
    save_state(root, state)
    _write_evidence(root, results, "failing; agent asked to keep working")
    _history(root, session, "blocked", results)
    print(_failure_message(failed, attempts + 1, max_attempts), file=sys.stderr)
    return 2


def main() -> int:
    try:
        hook_input = read_hook_input()
    except ValueError:  # includes UnicodeDecodeError
        hook_input = {}
    try:
        return decide(hook_input)
    except Exception as exc:  # never break the user's session
        print(f"Proof Kit: internal error, allowing stop ({exc})", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
