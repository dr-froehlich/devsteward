# Process-resilience audit — every red step has an available forward path

**REQ:** REQ-053 · **Date:** 2026-06-19 · **Depends on:** REQ-047 · **Scope:** audit + recommend
(no code change here; implementation spins out as named follow-on REQs).

This report is the validation surface for REQ-053's `manual` AC1. The human verdict — that
every red / failed / parked state maps to an *available* forward verb or a *flagged* gap, that
the repeat-vs-rework model and the `recover → repeat` naming question are resolved with a
recommendation, that the out-of-tool root-cause case names a stable continue-path, and that
each recommended change has a named follow-on REQ — is recorded at `steward validate REQ-053`.

## Method

Walked the **code**, not the prose, for every place a step can come to rest red:
`core/model.py` (the `StepStatus` state space), `core/executor.py` (the develop gate, the
repair loop, the land gate, attended/park handling), `profiles/req/validate.py` (the
validation parks and verdicts), `lifecycle.py` (`recover` / `rework` exact transitions and
refusals), `core/ledger.py` (`answer_decision`, `park_decision`), and the `cli.py` verb
surface. Two mechanical facts were confirmed by reading, because the findings hang on them:

- **usage-limit re-queues to `PENDING`** (or keeps `RECOVER` if already recovering) —
  `executor.py:276` — so it is auto-eligible on the next run with **no operator verb**; and
  the `--recover` resume signal is appended **only** when status is `RECOVER`
  (`executor.py:267-268`).
- **`decision answer` flips only the decision's own step** BLOCKED → PENDING
  (`ledger.py:153-164`). On a *red-validation* decision that re-arms **validate** while leaving
  **develop `DONE`** — a re-validate-without-redo path that already exists mechanically.

## The state space

`StepStatus` (`core/model.py`) is the whole vocabulary: `PENDING`, `RUNNING`, `DONE`,
`BLOCKED` (blocked-on-decision), `FAILED`, `RECOVER`. Only `PENDING` and `RECOVER` are
*runnable* (`executor._RUNNABLE`). So **every** forward path, whatever verb drives it, must
land the step in `PENDING` or `RECOVER` — that is the single mechanical definition of "an
available path forward." A state that can reach neither is a dead-end.

The operator verbs that move a stuck step toward runnable:

| Verb | Transition | Carries `--recover`? | Refuses when |
|---|---|---|---|
| `steward recover REQ` | `FAILED → RECOVER` (all failed steps of the REQ) | **yes** (RECOVER) | no `FAILED` step exists |
| `steward rework REQ` | develop `DONE → RECOVER`, validate `BLOCKED → PENDING`; answers the parked validate decision | yes for develop | no *red* validation (latest validation not `ok:false`, or validate not BLOCKED); `done` REQ → supersede |
| `steward decision answer DEC` | the decision's step `BLOCKED → PENDING` | **no** (PENDING) | no open decision by that id |
| *(auto)* quota re-queue | `→ PENDING` (or stays `RECOVER`) | only if RECOVER | — (engine-internal; next run retries) |
| *(engine-internal)* repair loop | spawns `--repair` sessions on a red develop gate | n/a | budget `≤ 0` → straight to FAILED |

## Forward-path map — every terminal red/failed/parked state

| # | Terminal state (where a REQ comes to rest) | Lands in | Cause | Available forward path | Resume status | Verdict |
|---|---|---|---|---|---|---|
| A | **Develop gate red**, no repair budget (`executor.py:340-343`) | `FAILED` | internal (work insufficient) | `steward recover` → re-run | `RECOVER` (+`--recover`) | available |
| B | **Develop session crash** — `step_failed`/`launch_failed` (ERROR/TIMEOUT/launch) (`executor.py:306-327`) | `FAILED` | **external** (claude crashed, API timeout, cswap/PATH) | `steward recover` → re-run | `RECOVER` (+`--recover`) | available |
| C | **Usage limit / quota block** during develop or repair (`executor.py:280, 301; validate.py:520`) | `PENDING` (auto) | **external** (limit resets, account swap) | next `steward run` (no verb) | `PENDING` | available, **automatic** |
| D | **Repair budget exhausted, still red** (`executor.py:585-601`) | `BLOCKED` + parked decision | internal | `steward decision answer` → re-run | `PENDING` (**no** `--recover`) | available, **seam** (loses resume signal over a dirty tree) |
| E | **Validate red** — artifact AC failed / manual *declined* (`validate.py:709-737`) | `BLOCKED` + parked decision | internal (hollow develop) **or** external (broken lab) | `steward rework` (→develop) **or** `decision answer` (→ re-validate only) | develop `RECOVER` / validate `PENDING` | available, **gap** (only `rework` is named; external cause forces a needless develop redo) |
| F | **Validate pending** — manual AC awaiting its human oracle, async QA (`validate.py:683-707`) | `BLOCKED` + parked decision, **no** validation event | external (waiting on a human) | `steward validate REQ` attended | runs validate directly | available, **seam** (`decision answer` here just re-parks in batch) |
| G | **Validate session crash** (System Tester) in-flight (`validate.py:526-533`) | `FAILED` | external (claude crashed) | `steward recover` → re-run validate | `RECOVER` | available |
| H | **Land refused** — no plan names the REQ (`executor.py:434-448`) | `BLOCKED` + parked decision | internal (missing artifact) | add the plan, `decision answer` → re-run | `PENDING` (**no** `--recover`) | available, **seam** (re-runs cognition over a dirty tree) |
| I | **Attended-parked** — batch hit an attended step (`executor.py:486-502`) | `BLOCKED` + parked decision | by-design (needs a human) | run it interactively / `decision answer` | `PENDING` | available |
| J | **Parked fork** — a skill raised a decision (`executor._detect_park`) | `BLOCKED` + parked decision | by-design (a question) | `steward decision answer` | `PENDING` | available |

Guards that are **refusals, not terminal states** (they emit guidance and write nothing, so
they cannot strand anything): `checkpoint` on an already-`done` step (idempotency, REQ-040);
`validate` when develop isn't closed / a lab is pending / inside a Claude session / on the
wrong HEAD; `check_invariants` on production or mid-merge. None is a dead-end — each names
its own clearing action.

**Headline: there are no dead-ends.** Every one of the ten terminal states reaches a runnable
status through a currently-shipping verb (REQ-047's un-divergeable, single-ledger state model
is what makes the parked-on-the-wrong-branch stranding of REQ-043/044 *unreachable* — see
`[[trunk-based-pivot-req047]]`). What remains is not a stranding risk but a **clarity and
fit** problem: three states (D, E, H) reach `PENDING` via `decision answer` and so re-run a
fresh session **without** the `--recover` assess-the-tree signal even though partial work sits
in the tree; and the verb a human reaches for does not always match the root cause (E).

## The repeat-vs-rework model

Peter's framing: at a red step there are two intents, and which is right depends on the root
cause.

- **Repeat** — the cause is *external* to the work (rate limit, API timeout, a lab/setup
  issue since fixed). The prior work was sound; **run the step again**.
- **Rework** — the prior development was genuinely *insufficient*; **redo it**.

Map that onto the layer × cause grid, with the verb each cell uses today:

| | **Internal cause (insufficient → rework)** | **External cause (sound → repeat)** |
|---|---|---|
| **develop** | gate red → `recover` (re-arm, `--repair`/`--recover`) — state A | crash/timeout → `recover` (state B); usage-limit → **auto-requeue** (state C) |
| **validate** | hollow develop → `rework` (→develop) — state E | broken lab fixed → **no named verb** (`decision answer` + `steward validate` works, undocumented) — state E/F |

What this shows:

1. **`recover` is misnamed, and Peter's instinct is right.** At the develop layer one verb
   (`recover`) serves *both* intents — the external crash/timeout (states B, the common
   "the work was sound, run it again") **and** the internal gate-red (state A). For its dominant
   use it is a **repeat**, not a "recover from a broken state." The forward *action* is
   mechanically identical in both (re-arm the FAILED step → `RECOVER`, hand the fresh session
   the tree + a `--recover`/`--repair` brief, let *the session* judge sound-vs-insufficient).
   So the right move is a **rename, not a split**: the engine cannot reliably pre-classify the
   cause, and it does not need to — `repeat` names the action ("attempt the failed step
   again") honestly for both. The `step_failed`/`launch_failed` vs `verify`-red events already
   record *which* cause it was, for whoever wants to know.

2. **`rework` is correctly named** — it is a structurally distinct edge (re-open a `DONE`
   develop, reset a `BLOCKED` validate, the V-model return). Keep the name.

3. **The validate-layer external cell has no named verb.** A red validation caused by a
   *broken lab the human then fixes* (external; the develop work was sound) wants to **re-run
   validate only**, leaving develop `DONE`. Today the only **named** verb is `rework`, which
   re-arms develop too — a needless redo of sound work — and `validate.py:_park_red` actively
   steers the human there ("Return it to develop for a fix with `steward rework`"). The
   re-validate-only path *exists* (`decision answer DEC` flips just the validate step to
   `PENDING`, develop stays `DONE`; then `steward validate REQ`) but it is undocumented and
   un-named. This is the sharpest fit gap in the surface.

So the clean model is symmetric:

| | internal → **rework** | external → **repeat** |
|---|---|---|
| **develop** | `repeat` (renamed `recover`; session fixes from the tree) | `repeat` / auto-requeue |
| **validate** | `rework` (→develop) | **`revalidate`** (new: re-arm validate, develop stays done) |

`repeat` carries both develop cells because the action is one action; `rework` and
`revalidate` are genuinely different edges and each earns its own name.

## Out-of-tool root cause — the stable continue-path

The tool cannot fix an external cause; it must offer a stable verb that **adopts whatever is
now true in the environment** and continues, *without* forcing a redo of sound work.

| External cause | Tool can't fix it, but… | Stable continue-path today | Verdict |
|---|---|---|---|
| **Usage limit resets / quota** | limit clears on its own; `--use N` pins an account, `--threshold` gates | step auto-requeued to `PENDING`; next `steward run` retries and re-checks the account precheck | **best-in-class** — automatic, no verb |
| **API timeout / claude ERROR** | transient; retry | `steward recover` (→ `repeat`) | available |
| **Account swap / cswap / `claude` not on PATH** (`launch_failed`) | human fixes PATH / account provider | `steward recover` (→ `repeat`) re-runs with the now-fixed environment | available |
| **Lab / host setup for a validation** (fixture, IMAP host, credentials) | human repairs the lab, commits the fixture (REQ-051) | **gap**: `decision answer` + `steward validate` (undocumented); the brief misdirects to `rework` | **gap → `revalidate`** |

The principle the audit affirms: **usage-limit is the reference design** for an out-of-tool
cause — the engine parks to a runnable status, re-checks the precondition on the next run, and
the human's external fix (or simply the passage of time) is adopted with no special verb. The
develop external causes (B) match this via `recover`/`repeat`. The **one cause that does not**
is the validation lab/host fix, because its only named verb over-corrects into a develop redo.
Closing that is the point of `revalidate`.

## Recommendations (each with a named follow-on REQ)

The design principles warn that a string of fixes that each *add* recovery machinery is a
smell. These deliberately **rename and document** before they add — one genuinely new verb,
and it fills a named hole rather than papering over a premise.

1. **Rename `recover` → `repeat`.** (Proposed **REQ-054**, `refactor`.) The develop FAILED
   re-arm is, in its dominant use, "the work was sound, run it again"; `repeat` names the
   action honestly and covers the gate-red case too (the session judges from the tree). Keep
   `steward recover` as a deprecated alias for one release so consumers' muscle memory and
   docs do not break; update `cli.py`, the skill prose, and the handbook. Do **not** split the
   verb by cause — the engine cannot reliably pre-classify, and the action is one action.

2. **Add `steward revalidate REQ`.** (Proposed **REQ-055**, `feature`.) Re-arm a red/parked
   `validate` step `BLOCKED → PENDING` while leaving `develop` `DONE`, for an external-cause
   red (a lab/host issue the human fixed) where the develop work was sound. It is the
   `repeat` of the validate layer, the missing external cell. Today only the internal-cause
   `rework` is named; this stops the brief from pushing a needless develop redo.

3. **Fix the red-validation brief to name both edges.** (Folds into **REQ-055**.)
   `validate.py:_park_red` should offer the human the *choice* — `steward rework` when the
   develop was hollow (internal), `steward revalidate` when an external lab/setup issue was
   fixed (the develop stands) — instead of unconditionally steering to `rework`.

4. **Carry the `--recover` resume signal through decision-answered re-runs of dirty steps.**
   (Proposed **REQ-056**, `fix`.) States D (repair-exhausted), E (after rework — already
   RECOVER, fine), and H (land-refused) leave partial work in the tree but resume via
   `decision answer` → `PENDING`, so the fresh session does **not** get the `--recover`
   assess-the-tree brief and may redo work or trip over the dirty tree. Re-arm these parks to
   `RECOVER` (not `PENDING`) on answer when partial work exists, so the resume is a true
   *repeat* with the tree-assessment signal — consistent with states A/B.

5. **Document the async-QA continue-path explicitly.** (Folds into **REQ-055** docs, or a
   small standalone **REQ-057**, `docs`.) For state F (manual AC awaiting its oracle), the
   forward path is `steward validate REQ` attended — *not* `decision answer`, which in batch
   only re-parks. Say so in the parked-decision message and the handbook so the human is not
   sent in a circle.

### Priority

REQ-055 (the `revalidate` gap) is the only **correctness-of-fit** item — it is the one place
the named path makes a human redo sound work; do it first. REQ-054 (`recover → repeat`) is the
naming change Peter asked about — low-risk, do it alongside. REQ-056 (resume-signal) and the
doc items are polish that remove the residual seams.

## Verdict offered for sign-off

- **No dead-ends.** All ten terminal red/failed/parked states reach a runnable status via a
  shipping verb; REQ-047's single-ledger model makes the historical stranding unreachable.
- **The repeat/rework model is resolved:** `recover` should become **`repeat`** (rename, not
  split); `rework` keeps its name; the missing symmetric verb is **`revalidate`** for the
  external-cause red validation.
- **The out-of-tool case is named:** usage-limit is the reference (auto-requeue + precheck);
  develop externals match via `repeat`; the one gap is the validation lab/host fix, closed by
  `revalidate`.
- **Follow-ons named:** REQ-054 (rename), REQ-055 (`revalidate` + brief), REQ-056 (resume
  signal through dirty-step parks), REQ-057/docs (async-QA path).

Reviewer sign-off (recorded at `steward validate REQ-053`): _is this enumeration complete, and
are the recommendations concrete and actionable enough that REQ-054…057 can be intaken without
re-litigating the model?_
