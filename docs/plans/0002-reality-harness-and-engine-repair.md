# 0002 — Reality harness and engine repair

**Date:** 2026-06-07
**Status:** **COMPLETE.** Assessment accepted; REQ-013 + REQ-014 + REQ-012 + REQ-015
(verify-teeth, defect 3) done (reality gate first green 2026-06-08 — the engine drove a real
`claude -p` through design→build→land; re-run green under REQ-012's hardened `_classify`
and again under REQ-015's `ReqVerifier`). Step 5 (resolve the batch-vs-interactive `advance`
fork + double-commit) **done 2026-06-08** as a docs+skill change (no engine code change — the
executor already implemented the batch contract; the incoherence was in the prose and the
skill's commit instruction).
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

**Concept (sound; the one fork is now resolved — step 5).** REQs as the unit of work, a
dependency DAG, the ledger as cursor separate from the spec, and "the model thinks, the
engine guarantees" are the right ideas, faithfully derived from the reference systems. The
fork was: *is `advance` a headless batch worker or an interactive pair?* The engine path
(`claude -p`) cannot ask questions and must park forks (correct, matches `run_batch.py`).
The skill said "ask via AskUserQuestion, then continue" — which only works in a live session
where there is no executor in the loop, so the skill was, in effect, told to self-attest
success: the exact false-done the architecture claims to prevent. **Resolution:** the two
are now declared as two distinct modes (step 5). The headless engine commands are the *batch
worker* — engine-guaranteed, forks always park, engine owns the single commit. The bare
skill in a live session is the *interactive pair* — explicitly carrying no engine guarantees,
asking at forks, committing its own work, with the human as the guarantee. The skill keys its
ask/park and commit/leave-dirty behaviour off `DEVSTEWARD_UNATTENDED`, which also closes the
double-commit (only one owner commits per mode).

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

1. **REQ-013 — Reality harness — DONE (gate first green 2026-06-08).** An opt-in end-to-end test that drives a
   real `claude -p` through the production executor and asserts a real edit + commit, plus
   hermetic meta-tests that keep the gate honest. Expected RED against today's engine —
   that red is the deliverable. Establishes the process rule: *no checkpoint of the
   engine's own loop is trusted until the real gate has been run green at least once.*
2. **REQ-014 — Permission mode for headless `claude -p` — DONE.** Pass a permission mode so
   a real headless session can edit files. Acceptance: the reality gate's build/land steps
   actually produce and commit the file. Turns the first half of REQ-013's gate green.
3. **REQ-012 — Real cswap CLI — DONE (2026-06-08).** Provider rewritten to the 0.11
   switcher contract (`claude_argv()` is plain `["claude"]`; `precheck()` switches via
   `cswap --switch-to N` and gates on `cswap --status`, all non-fatal). `claude._classify`
   hardened: a non-zero exit with zero stream-json events is now `Outcome.LAUNCH_FAILURE`,
   distinct from a mid-task error, recorded as a `launch_failed` event. Obsolete
   `test_use_pins_account` replaced by `test_use_switches_account`; `config.yaml` restored
   to `provider: cswap`. Not exercised by the reality gate (it pins `single`), so verified
   by hermetic ACs; the gate stays green under the new classify path.
4. **Verify teeth — REQ-015 — DONE (2026-06-08).** New REQ (not folded into REQ-006).
   Concentrated the guarantee at land via `ReqVerifier` (REQ profile): a `land` step with
   no acceptance tests is *refused*, not marker-trusted; design/build keep marker-trust
   (they only advance the cursor — a no-op build is caught at land when its acceptance
   tests fail). A per-phase "working tree changed" gate was rejected because the advance
   skill's design phase legitimately produces no file change for a trivial REQ (it would
   fail honest designs and this very gate). `build_executor` wires `ReqVerifier` for the
   req profile; the handbook/verify docstring were corrected to stop overclaiming. Closes
   the false-done path. Reality gate re-ran green under `ReqVerifier` (4 passed ~212s).
5. **Resolve the conceptual fork — DONE (2026-06-08, docs + skill).** Settled the fork by
   declaring two modes with different contracts. *Batch worker* (`steward advance` /
   `steward run`, driving `claude -p` headless): the engine owns the guarantees — it re-runs
   the tests, owns the **single commit**, advances the ledger, and forks always **park**
   (never `AskUserQuestion`). *Interactive pair* (`/advance` in a live session): no executor
   in the loop and so **no engine guarantees** — the skill verifies, the skill commits, and
   it asks at forks; the human is the guarantee. The **double-commit** is closed by making
   commit ownership exclusive per mode (engine commits in batch, skill commits interactively,
   never both): the skill's close step now keys off `DEVSTEWARD_UNATTENDED` — under the engine
   it leaves the working tree dirty for the engine's one commit. No engine code change was
   needed (the executor already implemented the batch contract); the fix aligned
   `advance/SKILL.md`, `handbook/00`–`04`, `CLAUDE.md.tmpl`, and the executor docstring.

The sequencing matters: step 1 changes the *process* (no green without one real run),
which is the actual root cause; steps 2–5 are then routine and each verifiable for real.
