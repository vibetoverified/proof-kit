# done-gate: a 31-line Stop hook for Claude Code

The smallest useful version of what Proof Kit does: Claude Code can't stop while your check command fails.
It's one file with no dependencies (Node built-ins only), and it works with any command that exits non-zero
when it fails: `npm test`, `pytest -q`, `go test ./...`, `cargo test`, or `npm run lint && npm test`.

It's built step by step, line by line, in the Vibe to Verified video "Build a done-gate for Claude Code in 31 lines".

## What it does

Every time the agent tries to finish its reply, Claude Code runs this script (a Stop hook):

1. **Nothing changed?** If `git status` shows no changes in the project, the agent may stop. A question or a plan
   doesn't run your whole test suite.
2. **Run your check.** If it passes (exit code 0), the agent may stop.
3. **It failed:** the script exits with code 2. Claude Code doesn't let the agent stop, and gives it the message
   and the test output as the reason.
4. **Never a trap:** after 3 blocks in one turn, it lets the agent stop and shows you a message saying why. It uses
   the `stop_hook_active` field Claude Code sends, so the count starts again with each new prompt.

## Install (2 minutes)

You need Node installed (any current version), even for a Python, Go or Rust project.

1. In your project, create a `.claude` folder if there isn't one.
2. Copy `done-gate.mjs` into `.claude/`.
3. Copy `settings.json` to `.claude/settings.json`. If you already have one, add the `"Stop"` entry under your
   existing `"hooks"` instead of replacing the file.
4. Change the last argument to your check command:
   ```json
   "args": ["${CLAUDE_PROJECT_DIR}/.claude/done-gate.mjs", "pytest -q"]
   ```
5. Start a new Claude Code session in the project. Type `/hooks` to check the Stop hook is listed.

To try it by hand without Claude Code, from your project folder:

```
# macOS / Linux
echo '{"session_id":"try","stop_hook_active":false}' | node .claude/done-gate.mjs npm test

# Windows (Command Prompt)
echo {"session_id":"try","stop_hook_active":false} | node .claude\done-gate.mjs npm test
```

With uncommitted changes and failing tests it prints the failures and exits with code 2. With nothing changed it
exits with code 0 straight away.

## Limits

- **It only knows what your tests know.** If the agent skips or deletes a failing test, the suite passes and the
  gate lets it stop. The message tells the agent not to, but nothing enforces it.
- **"Changed" means "uncommitted".** Files that were already uncommitted before this turn still count, so it may run
  your check on a turn where the agent only answered a question. Committing often keeps that rare.
- **One command.** Chain several with `&&`; they're reported as one result.

The [full edition of Proof Kit](https://vibetoverified.gumroad.com/l/proof-kit) closes those gaps: a guard that
blocks weakened or skipped tests, change detection per turn, lint and type checks reported one by one, a secrets
guard, and the same checks in GitHub Actions. The free edition in this repo has the per-turn change detection.

## Licence

MIT, like the rest of this repo.
