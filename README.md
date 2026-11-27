# Proof Kit (free edition)

**Your AI coding agent can't say "done" while a test is failing.**

Proof Kit adds a Stop hook to Claude Code. When the agent tries to finish, the hook runs your project's
test command. If it fails, the agent isn't allowed to stop: it sees the failing output and goes back to
fix it. When the tests pass, it writes the evidence to `.proof/last-run.md`.

A real block, from a session where the agent found a rate-limiter bug and tried to stop without fixing it:

```
Proof Kit: 1 check(s) failing, so this task is not done yet (round 1 of 3).

[test] `npm test --silent` exited 1:
✖ blocks the 6th request in the same minute (0.9171ms)
✖ counts each key separately (0.129ms)
✖ remaining() never goes below zero (0.1018ms)
✖ still blocks halfway through the window (0.0828ms)
ℹ tests 6
ℹ pass 2
ℹ fail 4

Fix the cause (do not skip, delete or weaken tests), re-run the checks, then finish.
```

It never traps the agent: after 3 blocked rounds (configurable) it hands back to you and says which
tests still fail. It only runs when files changed during the turn (so questions and reviews never trigger it), and any
internal error lets the agent stop
rather than break your session.

## What's included

- **Stop hook** that runs your test command before the agent may finish
- **prove-it skill**: run the checks, add a test for the change, report with evidence
- **handoff skill**: end-of-session summary of what changed, the proof, risks and next steps
- **Setup** that detects Node (npm, pnpm, yarn, bun) and Python (pytest) projects
- **[examples/done-gate](examples/done-gate)**: the same idea as a single 31-line Node script you can read in a minute and adapt to any stack

Plain Python 3.9+, standard library only. Tested on Windows 11, macOS and Linux. No network calls, no
telemetry.

## Install

You need Claude Code and Python 3.9 or newer (`python --version`; on Windows also try `py`).

1. Download this repository (**Code > Download ZIP**, then unzip) or clone it:

   ```
   git clone https://github.com/vibetoverified/proof-kit.git
   ```

2. Open a terminal in **your project's** root folder (the one with `package.json` or `pyproject.toml`)
   and preview:

   ```
   python path/to/proof-kit/install.py --dry-run
   ```

   It prints the test command it found, for example `test: npm test --silent`, and changes nothing.

3. Install:

   ```
   python path/to/proof-kit/install.py
   ```

4. Open `proof.toml` in your project and check the `test` command works when you run it yourself.

5. Start a **new** Claude Code session in the project. Type `/hooks` to see the Stop hook listed.

Commit `proof.toml` and `.claude/proof-kit/` and `.claude/skills/`. Don't commit
`.claude/settings.local.json`: it points at your machine's Python, so each teammate runs the installer
once.

## Try it

Break a test on purpose, then:

```
# macOS / Linux
echo '{"cwd": "."}' | python3 .claude/proof-kit/proof_kit/verify_before_stop.py; echo "exit $?"

# Windows PowerShell
'{"cwd": "."}' | python .claude\proof-kit\proof_kit\verify_before_stop.py; "exit $LASTEXITCODE"
```

You'll see the failing output and `exit 2`, which means "the agent may not stop". Fix the test and run
it again: `exit 0`.

## proof.toml

```toml
[checks]
test = "npm test --silent"

[stop_hook]
enabled = true
max_attempts = 3        # after this many blocked rounds, hand back to the human
only_if_changed = true  # skip when nothing changed during the turn
timeout_seconds = 300   # per check
```

## Full edition

The full edition adds the parts that stop the agent from getting around the tests:

| | Free | Full |
|---|---|---|
| Stop hook | test command | tests, lint, type checks and any other command |
| Test-tampering guard (blocks skipped, deleted or weakened tests) | | ✓ |
| Secrets guard (blocks reading `.env`, keys, credentials) | | ✓ |
| GitHub Actions workflow with a job summary and tamper scan | | ✓ |
| Skills | prove-it, handoff | + self-review, security-pass |
| Stacks | Node, Python | + Go, Rust, Java/Kotlin, .NET |
| Guide | this README | full setup and troubleshooting guide |

Get it here: https://vibetoverified.gumroad.com/l/proof-kit

## Licence

MIT. See [LICENSE](LICENSE).
