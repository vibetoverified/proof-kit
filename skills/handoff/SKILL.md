---
name: handoff
description: Write an end-of-session handoff (what changed, the evidence, known risks, next steps) so the user or the next session can pick up without re-reading everything. Use when finishing a session or a larger task, before a break, or when the user asks for a summary or handoff note.
---

# Hand off with evidence

The user should be able to read the handoff in a minute and know what changed, whether it is proven,
and what is left. Write it from facts you can show, not from memory of what you meant to do.

## 1. Gather the facts

- `git status` and `git diff --stat` for what changed (and `git log --oneline` for commits made this session).
- The latest check results: run the project's checks now (see `proof.toml`), or read `.proof/last-run.md`
  if the Stop hook just ran them and nothing changed since.
- Anything you couldn't finish, couldn't run, or decided not to do.

## 2. Write the handoff

Use this shape. Keep each line short and concrete.

```
Handoff: <task in a few words>

What changed
- src/limiter.ts: new sliding-window rate limiter (100 requests per minute per key)
- src/limiter.test.ts: 6 tests, including the burst case that was broken
- README.md: documented RATE_LIMIT_PER_MIN

Proof
- test: `npm test --silent` passed (30 tests)
- lint: passed · types: passed
- Evidence: .proof/last-run.md

Known risks
- In-memory store: limits reset on restart and aren't shared across instances

Next steps
1. Decide whether to move the store to Redis before deploying more than one instance
2. Add the limiter to the /auth routes (not done: outside this task)

Not done / not verified
- Didn't load-test; numbers above come from unit tests only
```

## 3. Save it if asked

If the user wants it kept, write it to `HANDOFF.md` (or the file they name) in the project root, and
mention that it may need adding to `.gitignore` if it shouldn't be committed.

Never write "all done" while any check is failing or unrun. Put it under "Not done / not verified".
