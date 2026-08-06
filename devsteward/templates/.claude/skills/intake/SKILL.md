---
name: intake
description: Interview a raw idea into a schema-valid draft REQ. Use when the user has a new feature/change idea ("I want to add…", "we should support…", "intake this") that is not yet a requirement. Interrogates risks, scope, dependencies, and the English-code/localized-UI split, drives acceptance to system level and classifies each criterion's check:, then writes a draft REQ + its index row.
---

# /intake — interview an idea into a draft REQ

You turn a raw idea into a **schema-valid draft requirement**. The interrogation is the
point: a sharp `/intake` is worth more than fast output. Institutionalize the questions.
This is the one moment a human shapes the REQ before headless work — the house style you
seed here is what every later step inherits.

## 1. Orient

- **Where the documents live:** `.devsteward/config.yaml` names the requirements dir, the
  index, the plans dir and the concepts dir (`requirements_dir`, `index_file`, `plans_dir`,
  `concepts_dir`; defaults `docs/requirements/`, `docs/plans/`, `docs/concepts/`). Read it
  first and use *those* paths throughout — a project whose `docs/` belongs to a docs
  generator keeps them elsewhere.
- Read `CLAUDE.md`, `REQ-001.md` (the north star) and `REQUIREMENTS_INDEX.md` in the
  requirements dir. The new REQ must advance REQ-001 or be explicitly scoped against it.
- Find the next free id: highest `REQ-NNN` in the index + 1, zero-padded. Ids may carry a
  trailing letter (`REQ-028p`, an umbrella split into sub-parts) — **strip any trailing
  letter before taking the max**, so `REQ-028p` counts as `028`, never `028` + 1 skipped.

## 2. Interrogate (the sacred part)

Ask, in `AskUserQuestion` form when interactive, until you genuinely understand:

- **Problem:** who hits it, how often, what's the cost of the status quo?
- **Scope boundaries:** what is explicitly *not* in this REQ?
- **Alternatives:** what simpler thing did we reject, and why?
- **Risks / weaknesses:** what could make this the wrong call?
- **Dependencies:** which existing REQs must be done first? (→ `depends_on`)
- **Acceptance:** system-level, measurable, classified — §2a–§2b below.
- **Process:** the three declarations only a present human can make — §2c below.
- **Localization split:** any user-facing strings? They stay isolated/translatable; all
  code and technical text is English.

**Mid-turn explanations are swallowed — put context inside the question (2026-07-17
marker test).** In this harness, text emitted *after a tool result and followed by
another tool call* is **never rendered** — and the interview loop (answer → explanation →
next `AskUserQuestion`) puts every between-question explanation in exactly that position.
Only turn-initial text and the turn's final message (no trailing tool call) render.
Therefore: anything the operator must read to answer — commands to run, findings so far,
the option trade-offs — goes **inside the `question` field / option descriptions /
previews**, never in prose between the previous answer and the next question. When the
needed context is longer than a question can carry, **end the turn** with the explanation
as final text and ask in plain prose, waiting for the reply.

**A question timeout is not an answer.** If an interactive `AskUserQuestion` gets no
response (the harness gives up after ~60s and invites "best judgment"), the operator is
merely away — **re-ask and wait; never proceed on defaults**. Steering these answers is
the entire purpose of intake; a defaulted interview produces a REQ nobody chose. The only
sanctioned way to run intake without a human is the explicit `DEVSTEWARD_UNATTENDED=1`
park-and-surface path below — an unanswered prompt in an attended session is not it.

**Park-and-surface:** if `DEVSTEWARD_UNATTENDED=1` is set, do **not** block on questions.
Instead write a decision request to the ledger and stop (see §4).

### 2a. Drive acceptance to system level

Push every criterion toward an **end-to-end chain with a measurable, captured
deliverable** — output that can be hashed, golden-compared, or signed off once. "Fetch
*this* captured mail and compare the parsed fields" beats "connects to a server";
"produces `report.csv` matching the golden copy" beats "export works". Abstract,
artifact-less criteria are how REQs go green while hollow.

The screening question is the **oracle** — *what decides pass/fail, and is it coupled to
the code under test?* A criterion whose only oracle is a mock authored alongside the code
cannot disconfirm anything: name it `regression` honestly, or sharpen the criterion until
a decoupled observable exists. (Oracle = the part of a test that decides correct vs
incorrect, distinct from the fixture and the system under test.)

**Wire through the live entrypoint (REQ-071).** A *system-scoped* criterion must exercise
the feature through its **real running entrypoint** (the cadence / scheduler, the served
surface) — so a feature that is present and unit-tested but **unwired** *fails* the
criterion. **Tests passing ≠ wired**: "the unit is correct" and "the system invokes the
unit" are different claims, and a criterion that only proves the first goes green while
the user-visible feature stays dead.

**A known defect is never scoped out silently (REQ-071).** When the interview surfaces a
defect this REQ will not fix, it is either fixed here or homed in a **named follow-on REQ**
(record the home in Notes). Genuine non-goals may simply be listed out-of-scope; known
*defects* may not be silently deferred — silent deferral is how "built but unwired"
stayed invisible.

### 2b. Classify every criterion: `check:`

Every acceptance criterion carries a required `check:` field — the routing key that maps
it onto the V-model: `regression` → Build phase (verification); `artifact` and `manual` →
System-Test phase (validation), which exists only if such a check exists. Decide by
**oracle coupling, not test name**:

- `regression` — module/unit scope; coupled or mock oracle; runs headless in Build.
- `live` (REQ-068) — system scope and a **decoupled** oracle, but a **standing** gate
  member: the cheapest end-to-end integration proof, run *as* regression in **every** develop
  gate forever (not once-on-demand like `artifact`/`manual`). Use it for "a few e2e tests
  kept running continuously" — the matrix cell (system scope × standing) that otherwise forces
  you to mislabel an e2e as `regression` or hide it behind a pytest marker. A `live` test that
  **skips** in the develop gate (its declared resource absent) is a **hard red**, never a
  silent skip — so a `live` AC must name a resource the gate environment actually has.
- `artifact` — system scope; a **decoupled, durable** oracle (a captured/golden/hashable
  observable produced by the lab); the engine consumes only its pass/fail signal. Runs
  **once** in the System-Test phase (a one-time validation, not a standing gate member).
- `manual` — system scope; **human** oracle; a decision stop inside the System-Test
  phase (one-time).

**One flavor (REQ-068).** Author every pytest acceptance command as `python -m pytest …`;
the engine runs it under one resolved interpreter and normalizes a leading bare `pytest …`
to `<interpreter> -m pytest …` (repo root importable). Never rely on a bare `pytest` or a
`-m "not live"` marker to decide a lane — the lane is the `check:` value, the engine reads it.

**Degrade — `live → artifact` (REQ-068).** When a newer live proof subsumes an older one,
flip the older AC's `check:` from `live` to `artifact`: it drops out of the standing develop
gate and stays re-runnable via `steward revalidate`. Record the superseding test/REQ in the AC
text or Notes. Degrade is *reclassification*, not a `steward degrade` verb.

**Writing a `manual` AC for a human oracle (2026-06-12 postmortem):** the human is the
least-context reader in the system and cannot infer — so a `manual` AC must name its
**observation surface** (where to look — the exact folder/page/file), its **operator
entrypoint** (the command + account that brings that surface up), and an explicit
**pass/fail** condition. Prefer "observe X in location Y" over "X works", and never assume a
coding-agent-grade reader who can reconstruct a missing runbook or entrypoint. (REQ-034's
guided validation session assists at runtime, but the criterion itself must still name these.)

**Honest deferral:** when an `artifact`/`manual` check needs a lab that does not exist
yet, record the follow-on REQ that owns the asset in `process.lab` — **never downgrade**
the check to `regression` to make it runnable today, and never fake the lab with an
inline double.

**Environment-bound `regression` — the silent-skip trap (REQ-064):** screen **every**
`check: regression` criterion with one question — *does its oracle need a service, secret,
or network that is **not** present in a clean repo checkout?* (a database, a `.env`, a
running service). If yes, its "green" silently rides hidden environment: the same test that
passes with that environment present **skips** without it, so the green is *environment-bound*,
not self-contained — the exact shape that discarded a whole session in the FlowSteward
REQ-043 postmortem (an all-`pg_required` AC, filed `regression`, whose green rode a gitignored
`.env`). Do **not** leave it a silent `regression`; route by **oracle coupling** (§2a):

- the oracle is **decoupled** (a live service / golden output the test compares against) → it
  is really an `artifact`: reclassify it `check: artifact` and name the REQ that owns the lab
  asset in `process.lab`.
- the oracle is **coupled** to the code and only needs a **runtime** present → keep it
  `regression`, but **record the required environment** in the REQ prose (Context/Notes —
  "required environment: …") so the batch lane / operator wires it up.

This does not *forbid* an environment-bound `regression` — the engine tolerates such a skip at
land (REQ-063) — it makes the author's choice **deliberate**, never a silent default that only
surfaces when a paid-for session is lost.

**The live-proof-in-develop screen — don't defer the teeth to a toothless validator.** There
is **no rule that development must stay off the live/production system** — the standing ruling
is the opposite: *don't defer the critical proof to the validator.* The System Tester runs in a
**fresh session that never sees the diff and cannot fix anything**, so a proof routed to the
System-Test phase (`artifact`/`manual`) has **no repair loop** — on a red it bounces back as
rework a whole session later. Yet the failures that matter most often live only in the **real
production corpus**, where every edge case a synthetic fixture could never invent actually
exists. So screen every criterion whose real risk is corpus-shaped with one question — *is this
only trustworthy after running against the live/real system and iterating on what it turns up?*
If yes, do **not** mechanically file it `artifact`/`manual` and ship it to validation: make the
live proof a **develop-session obligation** — performed and iterated attended, **fixable in
place**, stated in the Requirement + a Decision (`develop: split` is its natural shape), *not*
an acceptance criterion routed to the fixless System-Test phase. Keep a synthetic-fixture
`regression` alongside to prove the *mechanism* disconfirmably in the gate. Reserve
`artifact`/`manual` System-Test deferral for proofs a synthetic fixture genuinely can't stand in
for **and** whose oracle needs no fixing loop. Beware the two over-generalizations that breed
the false "develop must not touch prod" rule: the no-prod-content-in-`regression` rule bars
*committing prod-content assertions to the gate*, **not** *testing against* the live system in
develop; and the mid-phase deploy permission is a grant, not a restriction that **only**
concept phases may reach the live system — `/advance` §4 states it as an **attended** grant
covering any work that needs a round-trip through external infrastructure (REQ-089), so the
two documents now say the same thing.

**The deploy-shaped case, explicitly (REQ-089).** When the code only exists somewhere runnable
*after* a push — CI builds the image, a pipeline deploys it to a remote host — the proof
belongs in the **develop session**, which may push and deploy as often as the iteration needs
and fix what the deploy turns up **in place**. Routing that proof to `artifact`/`manual` is the
worst available destination: the System Tester never sees the diff and cannot fix anything, so
the proof gets **no repair loop** and every red costs a whole extra session. File the live
proof as a develop obligation in the Requirement + a Decision, and keep a synthetic-fixture
`regression` AC for the mechanism.

### 2c. The three process declarations (while the human is present)

Decide these now — they must not be made headless later — and record them in the
optional `process:` frontmatter block (omit the block when every value is the default
and no lab is needed):

- `concept:` — is a **concept phase** (architecture / risk buy-down / spike) warranted
  before develop? Default `false`. Setting it makes the develop step *attended* (batch
  parks it) and the develop land **refuses** unless a concept deliverable — a flat
  `<concepts_dir>/REQ-NNN.md` **or** a non-empty `<concepts_dir>/REQ-NNN/` **bundle directory**
  (REQ-067) — exists and the REQ's `concept_refs:` names it (the flat file or a path inside the
  directory; REQ-039 — the doc-gate, mirroring the plans dir). The spike is throwaway by default,
  but when the bought-down risk is *empirical* (e.g. operator consent to a concrete UI,
  unanswerable by a REQ or wireframe) the concept phase MAY keep a **committed, frozen prototype**
  as its deliverable — the build wires it (the bundle directory is its natural home). The author
  decides per REQ; the engine enforces no criterion. There is no separate `steward concept` step;
  the attended develop session *is* the concept phase.
  **Decision rule (REQ-071): set `concept: true` when the acceptance criteria cannot be
  honestly written at intake** — the concept phase is where you earn the ACs you can't yet
  write (a cause/path analysis for an outcome REQ; a committed prototype or frozen live data
  for an empirical one). An empirical concept phase may *iterate* — commit, push, deploy —
  until its deliverable is frozen; `steward checkpoint` is the terminal act (the `/advance`
  skill carries that workflow).
  **Phase-model placement — ask this explicitly (REQ-071):** when `concept: true` is set
  *because the target ACs depend on the concept deliverable*, also decide where the
  post-freeze work lives: **`develop: split`**, so a post-freeze develop phase iterates the
  analysis and authors the target ACs against the frozen deliverable, **or** a **named
  downstream REQ** that owns the modeling — and then the upstream REQ must **never carry the
  downstream REQ's acceptance bar** (no "sufficient basis for phase-N+1"-style manual AC on
  an upstream inventory step whose own Notes scope that work out — the FlowSteward REQ-081
  AC6 trap). `concept: true` + `develop: fused` stays the legitimate default for spike-shaped
  concepts whose ACs *are* writable at intake; either shape alone is fine — the *unexamined
  combination* is the defect.
- `lab:` — which REQs own the **lab assets** the System-Test phase will require?
  Default `[]`.
- `develop:` — `fused`, one design+build session (the **default**), or `split`, an
  attended design review before build — reserved for genuinely risky REQs. If split,
  extract *why* and record the reason in the REQ's Decisions table.

## 3. Emit

- Write `REQ-NNN.md` into the requirements dir from `_templates/req.md` with `status: draft`,
  filled frontmatter (including the `process:` block when it deviates from defaults or
  declares a lab), a real Context/Decisions/Requirement, and a `yaml acceptance` block
  where **every** criterion has an `id`, a `test:`, and a `check:`.
- Add its row to `REQUIREMENTS_INDEX.md` (status `DRAFT`). The index ↔ frontmatter pair is the
  **single source of truth** for status (`steward lint` keeps them in lockstep).
- If scenarios help, add `SCN-NNN` files and reference them in `scenario_refs`.
- Run `steward lint` and fix anything it reports. Leave it green.

Do all of this in **one commit** (frontmatter + index together), co-author trailer, on
`dev`. A requirement is a *registry declaration*, not implementation; committing it
serializes id allocation and keeps the index consistent.

**Close by naming the next command precisely (REQ-078).** When you suggest starting
development, phrase it as **`/advance REQ-NNN develop`** naming *this* just-intook REQ —
never a bare "run advance". A bare suggestion lets `/advance` self-orient onto whatever
step the cursor happens to make eligible (often an unrelated pending validation); an
explicit target can only ever start the REQ you just wrote.

## 4. Unattended fork handling

When `DEVSTEWARD_UNATTENDED=1` and you hit a question you cannot answer from REQ-001 +
the repo, append to `.devsteward/state.yaml` under `decisions:` a record
`{id, step, question, status: open}` and stop without writing a half-baked REQ. The
engine surfaces it; resume when answered.
