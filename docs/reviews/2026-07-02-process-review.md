# Process review — is the DevSteward rigor paying back?

- **Date:** 2026-07-02
- **Author:** Claude (Fable 5), at Peter's request
- **Question:** Every phase (concept, validation) has proven its value at some point — but is the
  effort and overhead the process imposes paying back overall? Did we bake in wasteful,
  low-merit patterns? Is REQ-072's implementation too narrow?
- **Evidence base:** both ledgers (`devsteward` 299 events, `flowsteward` 800 events), both
  requirement indexes (66 + 77 REQs), the engine source (full sweep, concentrated on the
  gate/verify/land path), the five skills, `STEWARD.md`, the handbook, FlowSteward's
  postmortems, and the 2026-06-10 strategic assessment as the baseline this review updates.
- **Scope note:** FlowSteward is used as *evidence about the engine*, per instruction; no
  FlowSteward-side recommendations except where a finding physically lives in its repo.

---

## Verdict

**The process is paying back, and the June-10 repositioning is the reason.** The evidence is
not subtle: FlowSteward landed **~75 substantial product REQs in 23 calendar days** (22 active
days) — folder lifecycle, a rule engine, a search console, production cutover, deployment — at
a measured cost of **~68 hours of tracked step time**, median attempt **9 minutes**, roughly
**1.3 sessions per REQ** plus a validate session where declared. The June-10 baseline was 29
sessions for 8 small REQs in one day, two-thirds of them verifying nothing. The fused-develop +
mechanical-land + conditional-validate shape fixed exactly what that assessment said it would.

The overhead that remains is mostly *load-bearing* (the gates catch real defects at a
significant rate — see §2), with three exceptions worth acting on, all in the **capture gate**
and the **documentation surface** — ranked proposals in §6. On REQ-072 specifically: the
implementation is narrow **by design** and the narrowness has no current bite, but the review
found the deeper issue is not the carry's width — it is that the capture gate reproduces the
wrong *set* of tests. Scoping it by the REQ-068 lane taxonomy would have made REQ-072
unnecessary and removes the whole false-red class at the root (§3).

---

## 1. The efficiency question, measured

### 1.1 Throughput (FlowSteward, 2026-06-09 → 2026-07-02)

| Metric | Value |
|---|---|
| REQs in index / done | 77 / ~73 (50 feature, 17 fix, 5 refactor, 3 chore, 2 spec) |
| Calendar / active days | 23 / 22 |
| Engine lands (`checkpoint` events) | 91 |
| Develop commits deferred to validate | 73 |
| Tracked step time (started → terminal event) | ~68 h |
| Median / mean / p90 attempt duration | 9 / 24 / 62 min |
| Sessions per step (steps needing >1 start) | 35 of 116 (30 %) |

Three-plus REQs per day, sustained for three weeks, on a codebase that now includes a Django
console, an IMAP worker fleet, a predicate language with three compilation targets, and a
production deployment. Whatever the process costs per REQ, the denominator is large and the
absolute pace is high. For comparison, DevSteward's own dogfood ledger over the same period:
~23 h of tracked step time to take the engine through the trunk-based pivot and the gate
hardening — a reasonable tool-to-product ratio, and one that has been *falling* (see §5.4).

### 1.2 Where the overhead actually goes

The retry/red rates decompose the 30 % re-start figure into meaning:

- **Verify red rate: 24 %** (37 of 155 gate runs). This is the gate doing its job — each red
  is a session that *claimed* green and wasn't, or an environment mismatch. The repair loop
  absorbed some (only 3 `repair_started` events — cheap); the rest surfaced honestly.
- **Red validations: 25 of 79** (32 %). Of those, **16 routed to `rework`** — the decoupled
  System Tester found a defect the builder's own tests could not see, and the work went back.
  **5 routed to `revalidate`** (lab/setup issue, develop stood). This is the single strongest
  number in the review: **roughly one in five validated REQs had a real defect that only the
  independent oracle caught.** The validate phase is not overhead; it is the part of the
  process with the highest defect yield per session.
- **Parked decisions: 34** — but only **2** were genuine design forks (split-develop reviews).
  **7** were expected manual-sign-off stops (process working as designed), and **25** were red
  validations, i.e. defect reports wearing a decision costume. The REQ-056 doctrine
  ("decisions are real forks only") is right and has already drained the develop-side parks;
  the validate side still routes every red through a human by design (Decision 8 of REQ-030),
  which the data supports — *except* for one loop shape, see finding §4.6.
- **Quota blocks: 16** — batch marching colliding with subscription windows. Annoying, now
  clauder's problem (REQ-058/061), out of scope here.

### 1.3 Did each phase earn its keep?

- **Intake.** Not directly measurable in the ledger, but the failure archaeology is
  consistent: every expensive failure class of the period (env-bound ACs → capture gaps;
  prose-poisoned deselects; fixture deadlocks) was cheaest to fix at intake, and the fixes
  that stuck (REQ-064 screening, REQ-068 `check:` taxonomy) are intake-side. The interview is
  where a present human is cheapest; the data says keep it sacred.
- **Concept.** Four FlowSteward REQs were concept-gated (REQ-025, 034, 045, 055) — exactly the
  big UI/architecture ones. After REQ-039 subtracted the heavy phase down to a doc-gate, the
  marginal cost of `concept: true` is one attended session plus one grep-shaped land check.
  Cheap, targeted, opt-in. No waste found.
- **Develop (fused) + mechanical land.** The land spends zero Claude tokens; the bookkeeping
  is sub-second; the cost is the test runs. This is the June-10 design working as intended.
- **Validate.** See above — 16 caught defects across ~54 validated REQs. The System-Test
  session at medium effort (FlowSteward's config) is also the *cheapest* session type. Clear
  payback.

---

## 2. REQ-072 — is the implementation too narrow?

**Short answer: it is exactly as narrow as it should be, and the residual narrowness has no
current bite — but the review found the gate it patches has a scoping problem that is the
better long-term fix.**

### 2.1 What it does, verified against the code

`Executor._carry_env_file` copies the single declared env-file (`verify.env_file`, default
`.env`) into the ephemeral `git archive` extract before `_green_gap_at` re-runs the named
acceptance tests there; `os.environ` was always inherited. Honor-when-present, secrets never
surfaced, `_capture_gap_message` rewritten to be environment-honest. Implementation matches
the REQ's six decisions faithfully; the tests in `test_commit_integrity.py` cover all five ACs.

### 2.2 The narrowness cases, checked against FlowSteward's actual repo

1. **Only one file is carried.** FlowSteward has *two* gitignored operator-local config
   surfaces: `.env` (carried) and `config/rules.yaml` (untracked by FlowSteward REQ-075, not
   carried). I verified by grep that **no test currently reads `rules.yaml`**, so there is no
   live bite — but the pattern "operator-local file the bootstrap reads from CWD" is a family,
   not a single file. **Recommendation: do not generalize preemptively** (the subtraction
   principle) — but note the tripwire: the day a capture gap names a config file rather than
   an env var, the fix is widening `verify.env_file` into a `verify.carry:` *list of paths*,
   not new machinery.
2. **Files referenced *by* the env-file** (e.g. `SOME_CREDENTIALS=./secrets/key.json`) are not
   carried. Same tripwire, same answer.
3. **External services** (the Postgres container, the mail lab) are reachable from the extract
   because `os.environ` + the carried `.env` name them — no narrowness there.

### 2.3 The finding that matters more: the gate's scope, not the carry's width

Two structural observations from the static review:

**(a) The capture check reproduces the wrong set.** `_capture_gap` re-runs *all* of
`step.verify` — which after REQ-068 includes `check: live` ACs. But the taxonomy already
declares what each lane's green means: `regression` = hermetic, self-contained,
reproduce-from-a-tree-extract is exactly its contract; `live` = *by definition* coupled to an
external system and a declared environment — the same category for which the **validate phase
is already exempted** from the capture check ("its green legitimately does not live in
`git archive` content"). Reproducing a `live` test from a bare extract was always a category
error; REQ-072 papers over it by carrying the env in, which works, but the root fix is:
**scope the capture reproduction to `check: regression` ACs only.** That would have made
REQ-072's carry unnecessary for the FlowSteward shape (their capture-gap tests were
env-coupled), removes the false-red class wholesale rather than per-file, and is a
*subtraction*. Keep the carry anyway — it is 25 lines, and it also protects the case REQ-064
explicitly tolerates (an env-bound test deliberately left `regression`).

**(b) The capture check has a false-*green* blind spot under editable installs.** The
interpreter is resolved against the real repo (correct — the venv is not part of a commit),
but FlowSteward's `.venv` has the package installed **editable**
(`__editable__.flowsteward-0.0.1.pth`), so when the capture check runs `python -m pytest` in
the extract dir, `import flowsteward` resolves through the editable finder **to the real
working tree, not the extract**. The check therefore proves the *test files, conftest chain,
and CWD-read data* are captured — but an uncaptured **package source file** would import fine
from the real repo and pass silently. The gate's docstring claims more than it delivers for
src-installed consumers. The observed failure history is 100 % on the false-red side and 0 on
the false-green side, so this is not urgent — but the honest move is to document the actual
guarantee in STEWARD.md/handbook ("the capture check proves test-side capture; package-source
capture rides the editable install"), and *optionally* detect-and-note editable resolution in
the gap message. Do not build an isolation sandbox for it; that is CI's job if you ever add CI.

**(c) Minor side effect.** `_stage_and_write_tree` runs `git add -A` (minus `.devsteward/`)
as a side effect of *checking*. On the failure path the operator's index is left fully staged.
Harmless under engine flow (the engine commits next), but surprising in interactive debugging.
A `git stash`-free alternative (`git write-tree` against a temporary index via
`GIT_INDEX_FILE`) would make the check read-only; cheap, low priority.

---

## 3. Static review — engine, skills, manual

Overall: the engine is small (~5.4 k lines core+profile+CLI), seam-structured, and unusually
well-documented — the docstrings are a decision record, each naming its REQ. Tests exist per
REQ and the suite is the develop gate's own floor. The review found no correctness defect in
the happy paths. Findings, roughly by weight:

1. **Capture-gate lane scoping + editable-install blind spot** — §2.3 above. The one place
   the engine's guarantee and its prose disagree.
2. **Stale stamped config in the consumer.** FlowSteward's `.devsteward/config.yaml` still
   carries the pre-pivot text: a `git.feature_branch` key (verified: **no reader anywhere in
   the engine** — dead key) and ~10 comment lines describing branch management the engine no
   longer does ("the engine now manages the feature branch end-to-end… merges it back
   `--no-ff`"). The current template (`templates/.devsteward/config.yaml.tmpl`) is correct;
   only FlowSteward's stamped copy is stale. Config is consumer-owned by design, so
   `sync-skills` rightly doesn't touch it — but config *comments* are process doctrine, and a
   cold session orienting from that file inherits dead, pre-pivot behaviour: exactly the
   resurrection risk STEWARD.md warns about. Cheapest closure engine-side: `steward lint`
   warns on unknown/dead config keys (`git.feature_branch`), which nudges the consumer to
   refresh the file.
3. **`_park_red` parks unconditionally** (`validate.py`), unlike `_park_manual` and
   `_park_attended` which dedupe against an existing open decision for the step. Combined
   with the retry loop this produced FlowSteward's REQ-022 pattern: **five identical parked
   decisions for the same skipped lab test.** Not a correctness bug (each prior decision was
   answered), but see §4.6 — the human was routed through the same fork five times with no
   signal that it was the same failure.
4. **`PlanArtifactGate` matches by substring across all plan files.** Any plan that merely
   *mentions* `REQ-NNN` (e.g. as a dependency of another REQ's plan) satisfies plan-first for
   it. Deliberately grep-shaped, and with 76 plans in FlowSteward the false-pass probability
   is real. A cheap sharpening — require the id in the filename or a heading — would keep the
   existence-check spirit. Low priority; no observed false pass.
5. **Redundant environment probes.** `resolve_test_interpreter`/`_has_pytest` spawn an
   `import pytest` subprocess per candidate, and the resolution is repeated for the named
   gate, the full suite, and the capture check within one land. Milliseconds against
   minute-scale test runs; note only.
6. **Skills and STEWARD.md are accurate.** I verified STEWARD.md's claims against the code —
   the lane table, the recovery-verb table, the env-carry description, the reland
   preconditions all match the implementation. Two small tensions:
   - `/advance` §3 tells a batch session to *append a decision record to
     `.devsteward/state.yaml`* while STEWARD.md's hard rule says *never hand-edit
     `state.yaml`*. The engine supports the cleaner `[[DEVSTEWARD_PARK]]` sentinel path in
     `_detect_park`; steering skills to the sentinel only would remove the one sanctioned
     hand-write of the ledger and the contradiction with the manual.
   - The `intake` skill (164 lines) is accreting postmortem doctrine inline (REQ-064, 068,
     070 case law). It is still coherent, but every intake session pays the full token tax of
     every past postmortem. Watch the trend; when it next grows, move case law to the
     handbook and keep the skill to the rules.

---

## 4. Did we bake in wasteful, low-merit patterns?

Checked candidate by candidate. Most suspects turn out to be load-bearing:

| Pattern | Cost | Merit | Verdict |
|---|---|---|---|
| Trailing ledger-close commits (≈2 commits per step outcome) | Noisy `git log` | Clean tree at rest; ledger recoverable (REQ-032) | Keep |
| Repair loop (budget 2, fresh sessions) | 3 uses in 800 events | Absorbs transient reds without a human | Keep — cheap because rarely triggered |
| Evidence dirs + sha256 per artifact | Bytes | Auditability, rot detection | Keep |
| Recovery-verb taxonomy (`repeat`/`rework`/`revalidate`/`reland` + decisions) | Conceptual surface | Each verb traced to a real stalemate; STEWARD.md table routes them | Keep, but **stop here** — `reland` (1 use) is the canary that the verb set is at its complexity budget |
| Capture gate re-running live-lane tests | Minutes per land, false-red class, REQ-063+072 spent fixing it | Reproduction proof for tests whose oracle is external anyway | **Subtract** — scope to `regression` lane (§2.3) |
| Four documentation registers (handbook, STEWARD.md, skills, CLAUDE.md.tmpl) | Every process change touches 2–4 places; REQ-066 built sync machinery to cope | Different audiences are real (human narrative vs. agent contract) | **Consolidate direction**: STEWARD.md is the normative agent contract; treat handbook as narrative that *links* rather than restates mechanics |
| The dogfood REQ stream itself (66 engine REQs, 17 `kind: fix`) | Half of June | The firefighting era (branch topology, REQ-037→044, all SUPERSEDED) is closed; post-REQ-047 fixes are small, consumer-postmortem-driven — the intended model | Healthy trend; the June-10 warning ("the tool is outgrowing its consumer") no longer holds: FlowSteward 77 vs DevSteward 66, and the gap is widening the right way |

And one pattern that is *missing* rather than baked in:

**§4.6 The identical-red retry loop has no memory.** REQ-022's validate step parked five times
on the same `test_lab_paperless_consume … skipped` red across several days. Each park read as
a fresh fork; nothing told the human "this is the fourth identical failure." A one-line
fingerprint in the park question ("same failure as DEC-NNN, n-th occurrence") — or simply the
`_park_red` dedupe that `_park_manual` already has, updating the existing decision — would
have compressed five human round-trips into one honest standing item. This is the cheapest
efficiency win the ledger data points at.

---

## 5. Best practices and alternatives

For calibration against the field (spec-driven agent workflows: GitHub spec-kit, OpenSpec,
Kiro-style spec pipelines, and the general CI orthodoxy):

- **The core bet — engine-owned verification — is the differentiator, and the data supports
  it.** Most agent-workflow frameworks are prompt/template stacks that ultimately *trust the
  agent's self-report*. DevSteward's "the gate cannot be talked into green" is rarer and is
  precisely what a 24 % verify-red rate proves necessary: one in four closes would have been a
  false done under self-report.
- **The decoupled validator matches the strongest known practice** (independent V&V / the
  test-vs-build separation), implemented at the cheapest possible layer — information flow
  (the session never sees the diff), not infrastructure. The 16-rework yield validates it.
- **The capture gate is a local approximation of "clean-room CI replay."** The industry answer
  to "does the commit reproduce its green" is a hermetic CI runner. You reasonably rejected CI
  for a local-first single-operator setup; the honest local equivalent is exactly the
  restriction proposed in §2.3 — replay the *hermetic lane* from the extract, and let
  env-coupled proof live where the environment does (the develop gate and the validate
  phase). That alignment, not a wider carry, is the best-practice answer to "too narrow?".
- **Lane declaration in the spec (`check:`) over pytest markers** — you already made this
  move (REQ-060/068), and it matches where the field is going (test intent declared in
  requirements, execution routing owned by tooling). No change advised.
- **What the field would add that you deliberately lack:** PR review gates, multi-writer
  concurrency, remote artifact stores. For a single operator, all three would be ceremony.
  The one to revisit *if* a second contributor ever appears is the single-writer ledger
  assumption (`_reconcile_stranded_running` proves ownership by process-shape, which is
  single-operator-only reasoning).

---

## 6. Ranked proposals (REQ candidates — not intaken)

1. **Scope the capture-gate reproduction to `check: regression` ACs** (subtract; engine,
   `_capture_gap`). Root-fixes the REQ-072 class instead of widening carries per file-shape;
   aligns the gate with the REQ-068 taxonomy and the validate exemption's own rationale. Keep
   the env-file carry as belt-and-braces for deliberate env-bound regressions (REQ-064).
2. **Park dedupe / failure fingerprint for red validations** (engine, `_park_red`): an
   identical repeated red updates the existing decision and says how often it recurred,
   instead of minting a fresh fork each time. Directly addresses the worst observed
   human-loop waste (REQ-022 × 5).
3. **Document the capture gate's real guarantee under editable installs** (docs:
   STEWARD.md + handbook; optionally a detection note in the gap message). Closes the gap
   between claim and behaviour without new machinery.
4. **`steward lint` warns on dead/unknown config keys** (engine, small): flags
   `git.feature_branch` and future removals, prompting consumers to refresh stale stamped
   config whose *comments* carry dead doctrine (FlowSteward's current file).
5. **Skill park path: sentinel only** (skills + docs): retire the "append to
   `state.yaml` under `decisions:`" instruction from `/advance`/`/intake` in favour of the
   `[[DEVSTEWARD_PARK]]` sentinel, removing the one sanctioned hand-edit of the ledger and
   the contradiction with STEWARD.md's hard rule.
6. **Documentation altitude rule** (method, no code): STEWARD.md is the single normative
   statement of engine mechanics; handbook chapters link to it rather than restating; skills
   carry rules, the handbook carries case law. Halts the four-register drift tax at its
   current, still-manageable size.
7. **Make the staged-tree check index-neutral** (engine, `GIT_INDEX_FILE`): the capture check
   stops mutating the operator's index on the failure path. Cosmetic; last.

---

## 7. The one-sentence answer

The rigor is paying back — three-plus verified REQs a day for three weeks, a gate that caught
a false green in one of four closes, and an independent validator that caught real defects in
one of five REQs — and the only genuinely wasteful baked-in pattern found is the capture gate
re-proving env-coupled tests from a hermetic extract, which is fixed by narrowing the gate's
scope to the lane taxonomy you already built, not by widening REQ-072's carry.
