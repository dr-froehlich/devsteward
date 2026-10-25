# AC3 validation procedure (guided) — REQ-064

`check: manual`. The **reviewer is the oracle**; the System Tester only prepares the
surface and captures artifacts. The verdict is recorded by the engine, never by this
session.

## Surfaces brought up

- The authoring surface: `.claude/skills/intake/SKILL.md` §2b (the screen under test) —
  captured in `intake-screen-under-test.md`.
- The seed input: a deliberately environment-bound idea — captured in `seed-idea.md`.

## Procedure for the reviewer

1. In a **plain terminal** (not inside a Claude/CLAUDECODE session — the decoupling, and
   the only place a fresh, uncoupled `/intake` run is honest), start `claude` and run
   `/intake`, pasting the idea from `seed-idea.md`.
2. Drive the interview to the acceptance + `check:` classification step.
3. Observe whether the **§2b environment-binding screen fires**: does `/intake` surface
   that this `regression`'s oracle needs an absent service/secret (Postgres + `.env`)?
4. Observe the **route** it lands on in the produced REQ's acceptance + `process` blocks:
   - reclassified `check: artifact` with the owning lab REQ named in `process.lab`, **or**
   - kept `check: regression` **with** the required environment recorded in the REQ prose.

## Pass / fail (the reviewer's sign-off)

- **PASS** — the screen fired AND the AC landed on one of the two honest routes above.
- **FAIL** — the screen did not fire, OR the AC was left a silent `check: regression`
  with no recorded environment (the REQ-043 disease unchanged).

## Note on this session

This guided session runs inside CLAUDE (`CLAUDECODE=1`). The genuine human-driven
`/intake` of step 1 is best run from a **plain shell** so the reviewer's oracle is not
coupled to anything this session produced — consistent with the validate-phase decoupling.
This session prepared the surfaces + seed and captured them as evidence; it did **not**
run `/intake` to a committed REQ (a validation session never mutates the repo) and did
**not** assert the verdict.
