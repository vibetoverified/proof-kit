"""Claude Code UserPromptSubmit hook: remember the project's state when each prompt arrives.

The Stop hook compares against this, so it only runs the checks when something changed during the
turn. Answering a question, reviewing code or explaining an error doesn't trigger the checks, even in a
project that already has uncommitted work. Always exits 0 and prints nothing (on UserPromptSubmit,
anything printed would be added to the agent's context).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from proof_kit.common import find_root, read_hook_input, save_baseline, tree_fingerprint  # noqa: E402


def record(hook_input: dict) -> None:
    start = Path(hook_input.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    root = find_root(start)
    if root is None:
        return
    fingerprint = tree_fingerprint(root)
    if fingerprint is not None:
        save_baseline(root, str(hook_input.get("session_id") or "default"), fingerprint)


def main() -> int:
    try:
        record(read_hook_input())
    except Exception as exc:  # never get in the way of the user's prompt
        print(f"Proof Kit: couldn't record the turn's starting state ({exc})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
