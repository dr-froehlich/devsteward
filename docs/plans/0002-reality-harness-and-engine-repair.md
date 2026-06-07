# 0002 — Reality harness and engine repair

**Date:** 2026-06-07
**Status:** assessment accepted; REQ-013 (reality harness) in progress
**Author:** Peter Fröhlich + Claude (assessment session)

This plan records a review prompted by a simple observation: DevSteward's 9-REQ baseline
was built by Claude "in one go," which felt suspiciously fast, and the first attempts to
use the engine on itself surfaced serious defects. The question was whether those were a
few isolated validation issues over a sound base, or the visible tip of a deeper problem —
and whether to restart (a) or fix incrementally (b).

**Verdict: do not restart. Fix incrementally — but lead with the missing reality test,
not with a fix list.** The skeleton is sound and well-factored; the failures are
concentrated at three places where clean code meets an external reality it guessed at, and
none of those three was ever exercised by a real run. A rewrite would reproduce the same
skeleton and, without a process change, the same blind spot.

## What was verified (not asserted)

- **`cswap` interface is fictional.** `core/accounts.py` builds `cswap exec --use N claude`
  and calls `cswap status`. Real `cswap` (v0.11.2, confirmed via `cswap --help`) has no
  `exec` subcommand, no `status` positional, no `--use` — it is a *switcher*
  (`--switch-to N`, `--status`, `--list`) that mutates the active account, after which you
  run plain `claude`. The event log shows the failure: `step_started`/`step_failed`
  stamped at the same second — a launch that never happened. → **REQ-012** (already
  drafted with an accurate diagnosis).
- **Headless `claude -p` passes no permission mode.** `core/claude.py:93` omits
  `--dangerously-skip-permissions` (the reference `Theresa/run_batch.py:363` has it).
  Without it a headless session cannot Edit/Write/Bash — nobody can approve the prompt — so
  the engine's core loop has, mechanically, never been able to do build work
  autonomously. → **REQ-014** (new; see below).
- **The verify guarantee has no teeth where it matters.** `profiles/req/source.py:48`
  attaches acceptance tests only to the `:land` step; `design`/`build` get `verify=()` and
  `core/verify.py:28` then returns `True, "marker trust"`. REQ-011 declared no tests at
  all, so every phase auto-passed. This is how an empty no-op reached `DONE` and was
  committed (then retracted in the event log). The architecture's headline promise — "so
  unattended automation can't be talked into a false done" (`handbook/02-engine.md:29`) —
  is real only at `land`-with-tests. → folded into the verify-teeth fix below.
- **The tests measure self-consistency, not fitness.** Every test mocks Claude
  (`conftest.FakeRunner`, `test_claude_stream` fake). `test_accounts.py:22-23` *asserts the
  hallucinated cswap argv* (`assert "--use" in argv`). Code and test were generated from
  the same wrong model, so they agree with each other and with nothing else. → the root
  cause this plan addresses first.
- **Empirical track record:** `.devsteward/events.jsonl` shows the engine has never once
  successfully driven a real Claude to produce REQ work — only `error`, retracted no-ops
  ("skill unresolvable, claude did nothing"), and `usage_limit` stops. The real REQ work
  and recent fixes were done by interactive sessions, not the engine.

## Assessment by layer

**Concept (sound, one unresolved fork).** REQs as the unit of work, a dependency DAG, the
ledger as cursor separate from the spec, and "the model thinks, the engine guarantees" are
the right ideas, faithfully derived from the reference systems. The unresolved fork: *is
`advance` a headless batch worker or an interactive pair?* The engine path (`claude -p`)
cannot ask questions and must park forks (correct, matches `run_batch.py`). The skill
(`templates/.claude/skills/advance/SKILL.md:39`) says "ask via AskUserQuestion, then
continue" — which only works in a live session where there is no executor in the loop, so
the skill is told to self-attest success: the exact false-done the architecture claims to
prevent. The guarantee holds only in the headless mode (currently non-functional); the
functional mode (interactive) has no engine guarantees.

**Architecture (clean skeleton, three boundary holes).** The four seams, the ledger split
(`state.yaml` + `events.jsonl`), dependency-gated eligibility, and park-and-surface are
clean and worth keeping verbatim. The defects are all at the reality boundary (the three
verified above), plus the conceptual incoherence.

**Implementation (never run for real).** See the verified track record. Green suite,
zero successful real checkpoints.

## Why not restart

The expensive, valuable part (seam design, ledger contract, DAG, park-and-surface, lint
rules) would be rebuilt nearly identically. The broken part is three boundary adapters and
one conceptual decision — cheap to fix, one already half-diagnosed. The real failure was
process (mock-only testing), not architecture; a rewrite without changing the process
walks straight back into it.

## The plan

Ordered so the missing reality check comes first; each fix lands with a *real*, not
mocked, check.

1. **REQ-013 — Reality harness (this change).** An opt-in end-to-end test that drives a
   real `claude -p` through the production executor and asserts a real edit + commit, plus
   hermetic meta-tests that keep the gate honest. Expected RED against today's engine —
   that red is the deliverable. Establishes the process rule: *no checkpoint of the
   engine's own loop is trusted until the real gate has been run green at least once.*
2. **REQ-014 — Permission mode for headless `claude -p`** (new). Pass a permission mode so
   a real headless session can edit files. Acceptance: the reality gate's build/land steps
   actually produce and commit the file. Turns the first half of REQ-013's gate green.
3. **REQ-012 — Real cswap CLI** (drafted). Rewrite the provider to the 0.11 switcher
   contract; harden `claude._classify` so a launch failure (non-zero exit, zero
   stream-json events) is distinct from a mid-task error. Replace the obsolete
   `test_use_pins_account`.
4. **Verify teeth** (new REQ or folded into REQ-006 follow-up). Forbid marker-trust on
   `design`/`build`, or require every active REQ to declare at least one runnable
   acceptance criterion the engine re-runs — enforced by `lint`. Closes the false-done
   path.
5. **Resolve the conceptual fork** (docs + skill). Declare `advance`/`run` a batch worker
   that never asks (forks always park); make interactive `/advance` an explicitly separate,
   human-driven mode that does **not** claim engine guarantees. Align `handbook/` and
   `SKILL.md`.

The sequencing matters: step 1 changes the *process* (no green without one real run),
which is the actual root cause; steps 2–5 are then routine and each verifiable for real.
