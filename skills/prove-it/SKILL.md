---
name: prove-it
description: Prove a coding task works before calling it done. Use whenever you are about to say a task, fix or feature is complete, or when the user asks you to verify, test or prove your changes.
---

# Prove it before you say "done"

"Done" means proven, not "looks right". Before you tell the user a task is complete:

1. **Read `proof.toml`** in the project root. Its `[checks]` section lists the commands that prove the work (tests, lint, type checks). If there is no `proof.toml`, find the project's test command (package.json scripts, pyproject, Makefile) and use that.
2. **Run every check** yourself, from the project root. Don't summarize what you expect them to do; run them and read the output.
3. **If anything fails, keep working.** Find the cause and fix the code. Never skip, delete, comment out or weaken a test, and never loosen an assertion to make it pass, unless the user explicitly asked for that change.
4. **Add a test for what you changed** when the project has tests and none covers your change. A fix without a test that would have caught the bug is not proven.
5. **Re-run all checks** after your last edit, not just the one that failed.
6. **Report with evidence.** End with a short block like:

   ```
   Proof
   - test: `npm test --silent` passed (24 tests)
   - lint: `npm run lint --silent` passed
   - types: `npx tsc --noEmit` passed
   - Added: tests/rate-limit.test.ts (covers the new limiter)
   ```

   Say plainly if a check could not run (missing tool, no network) instead of implying it passed.

A Stop hook may also enforce this: if checks fail when you try to finish, it blocks the stop and shows you the failures. Treat that message as a bug report and fix the cause.
