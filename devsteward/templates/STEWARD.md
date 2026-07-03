# STEWARD.md — the `steward` manual for agents

You are an agent driving this project's work through **DevSteward**. This file is your
**complete operating manual** for the `steward` command. Treat DevSteward as a black box: the
`steward` CLI and this document are the whole interface. **Do not read the DevSteward package
source** to figure out how to use it or how to recover from a state — everything you need is
here. Reading `cli.py` or the engine internals couples you to private structure and resurrects
dead, pre-pivot behaviour; if something seems missing from this manual, say so rather than
reverse-engineering the engine.

## The model in one breath

A **REQ** (`docs/requirements/REQ-NNN.md`) is a spec with a machine-readable acceptance block.
The **ledger** (`.devsteward/`) is the cursor: where work is and what happened. You do the
thinking; **the engine verifies and commits** — it runs the acceptance tests itself and only
marks a step `done` when they pass. You never write `status: done` and you never hand-edit the
ledger. All work lands on **`dev`** (trunk-based, linear history): no feature branches, no
worktrees, no branch switching. `main` is production (release tags only); the one branch
operation is the human-gated `dev → main` PR.

Each active REQ derives **one fused `develop` step** (plan → code → acceptance tests in one
session). A REQ whose acceptance has an `artifact` or `manual` criterion also gets a
**`validate` step** (the System-Test phase) between `develop` and the land.

## Orienting — always start here

```sh
steward status      # the cursor, eligible/blocked steps, parked decisions — the ONE read of the ledger
steward lint        # schema-valid REQs, deps resolve, index↔REQ in sync, every AC has a test id
```

`steward status` is the sanctioned way to see the ledger. Do not hand-read `.devsteward/state.yaml`.

## The normal forward path

```sh
/intake "<idea>"          # interview a raw idea into a schema-valid draft REQ (a skill)
steward activate REQ-NNN  # flip a draft (or dropped) REQ to open so it becomes eligible
/advance                  # do ONE develop checkpoint: plan + code + acceptance tests
steward checkpoint        # close it: the engine re-runs the tests and lands on green (one transaction)
```

- **`/advance`** (a skill) does exactly one fused develop checkpoint and stops. In a live
  session it asks you at forks. It leaves the working tree dirty for the engine — it does **not**
  commit.
- **`steward checkpoint [REQ-NNN develop]`** is the interactive close. It re-runs the named
  acceptance tests through the land-grade gate, checks a `docs/plans/` file names the REQ, and on
  green makes the one authoritative commit (frontmatter + index + code) and advances the ledger —
  all on `dev`. **On red nothing lands**: fix the cause and re-run `checkpoint`. The gate cannot
  be talked into green; certification is the engine's, never yours to assert.

Plan-first is enforced: the land **refuses** unless a file in `docs/plans/` names the REQ id.
Concept-first is enforced the same way for a REQ that declared `process.concept: true`: the land
also **refuses** unless a concept deliverable — `docs/concepts/REQ-NNN.md` **or** a non-empty
`docs/concepts/REQ-NNN/` bundle directory — exists and the REQ's `concept_refs:` names it (the flat
file or a path inside the directory). The bundle form is for a concept phase that keeps a committed
prototype as its deliverable, not only a throwaway spike.

## The batch lane (headless queues)

```sh
steward advance     # one develop checkpoint, headless
steward run         # march every eligible step headless; park on forks, stop on a hard failure / usage limit
```

In batch the engine drives `claude -p`, re-runs the tests itself, lands on green (repairing up to
twice on red, then parking), and advances. There is no human channel, so a fork is **parked**, not
asked. A REQ that needs a human (e.g. `develop: split`) is parked naming the attended need.

## The System-Test phase (`validate`)

If a REQ declares an `artifact` or `manual` acceptance criterion, the green develop gate only
**commits** the work on `dev` (it does not land yet) and a `REQ-NNN:validate` step follows.

```sh
steward validate REQ-NNN    # the single entry point for the validate step
```

- A fresh System Tester session (it never sees your diff) brings the lab up and captures
  artifacts; the **engine** runs each `artifact` test itself and consumes only pass/fail.
- A `manual` criterion takes a **human sign-off**. Run `steward validate REQ-NNN` from a plain
  terminal (not from inside a Claude session) — it walks the human through the procedure and
  records the verdict.
- On green, the same mechanical land fires (flip + index + ledger, on `dev`). A green validate on
  an already-`done` REQ just appends a fresh evidence event.

## Acceptance lanes — how the engine runs your tests (REQ-068)

The **engine** decides how each acceptance test runs — which lane, which flavor. You declare the
lane with the per-criterion `check:` field; you never decide it with a marker string or how you
typed the command. The four lanes:

| `check:` | scope / oracle | when it runs | in the develop gate? |
|----------|----------------|--------------|----------------------|
| `regression` | module, coupled | every gate (hermetic) | yes — named test + in the full suite |
| `live` | system, decoupled | every gate (**standing**) | yes — named test (a **standing** integration proof) |
| `artifact` | system, decoupled, durable | **once**, in `validate` | no — a one-time validation |
| `manual` | system, human | **once**, in `validate` | no — a one-time validation |

- **The develop gate routes by `check:`, deterministically.** It runs this REQ's `regression` +
  `live` lane tests as named tests, runs the hermetic full suite, and **deselects every
  `artifact`/`manual` node-id project-wide** from that suite — so a **one-time** validation of an
  already-done REQ never gates a later REQ's develop. You never hand-edit a `-m "not live"`
  marker; the engine derives the exclusion from frontmatter.
- **Fail-hard on a missing declared resource.** A `live` (or any named-lane) test that reports
  **skipped** in the develop gate is a **hard red** — the engine knows it must run, so a skip is
  not tolerated. (An *unknown* test that skips in the full suite is still tolerated.) A red
  withholds the land without destroying the work commit.
- **Your declared environment travels.** On green the land self-checks that the recorded commit
  reproduces its own green from a clean tree extract — and that check runs in your **declared
  environment**: the env-file (`verify.env_file` in `.devsteward/config.yaml`, default `.env`)
  is copied into the ephemeral extract when present, and `os.environ` is inherited. A green that
  legitimately reads a gitignored `.env` certifies with no shell exports. No env-file declared
  or present means the bare, hermetic check, unchanged. If certification is withheld anyway, the
  message names the **preserved** work commit; the cause is a source/test file the commit can't
  hold **or** a runtime environment the check lacked — fix it (never commit a secret), then
  `steward repeat REQ-NNN`.
- **One flavor.** Every pytest acceptance command runs as `python -m pytest` under one
  engine-resolved interpreter; a leading bare `pytest …` is normalized to
  `<interpreter> -m pytest …` (repo root importable). A test never runs in a different flavor
  depending on how you typed it.
- **Degrade is reclassification, not a verb.** When a newer live proof subsumes an older one, flip
  the older AC's `check:` from `live → artifact`: it leaves the standing develop gate, stays
  re-runnable via `steward revalidate`, and you record the superseding test/REQ in the AC text or
  Notes. There is no `steward degrade`.

## Recovery — getting out of every red or parked state

Pick the verb by **what is actually stuck**. None of these touch a `done` REQ (supersede instead;
`done` is never weakened) and none switch branches.

| State you see in `steward status` | What it means | The verb |
|---|---|---|
| A step is **FAILED** (a develop step errored or the gate stayed red) | The attempt left partial edits in the tree | `steward repeat REQ-NNN` |
| **D/H** — a develop step ineligible (e.g. no plan artifact, or split/attended need) | **Not a decision.** A mechanical go-fix-and-retry stop | fix the cause, then `steward repeat REQ-NNN` |
| A parked **decision** on a `develop` step (a genuine fork) | The session hit a choice it couldn't resolve | `steward decision answer DEC-NNN "<answer>"` |
| A **`manual`-AC** validate hold (state F): "awaits its human oracle" | Async QA — a human must sign off | `steward validate REQ-NNN` (**not** `decision answer`) |
| A **red validation** (the lab found a defect, or the validation test is wrong) | A human question — no auto-repair loop | `steward rework` or `steward revalidate` (below) |
| A **`done` REQ still surfacing a parked `:validate` decision** | A diverged ledger — the land already happened; the cursor was rewound behind it | `steward validate REQ-NNN` (reconciles it from the event log; **never** hand-edit `state.yaml`) |

- **`steward repeat REQ-NNN`** — the re-run verb (REQ-054, renamed from `recover`). The common
  failure is transient (a flaky env, an account swap), so the honest action is to repeat the step:
  it flips the FAILED step back to eligible, then `steward run` / `steward checkpoint` re-attempts
  against the partial tree the failed attempt left. It succeeds regardless of which branch is
  checked out (single ledger). Use it for any FAILED step **and** for a D/H mechanical stop once
  you've fixed the cause (e.g. added the missing plan file).
- **`steward decision answer DEC-NNN "<answer>"`** — resolves a **genuine fork** parked from a
  develop step. It refuses on a validation hold and redirects you to the right verb — heed that;
  do not try to force it.
- **`steward rework REQ-NNN`** — the return edge when a **red validation is a real defect**: it
  sends the validate step back to develop (`develop → recover`, `validate → pending`) so you fix
  the cause and re-validate. Reads the red evidence dir as your repair context.
- **`steward revalidate REQ-NNN`** — the validate-layer mirror: when the develop work **stands**
  and an external lab/setup issue was fixed, re-run the validation only (`develop` stays `done`).

`steward decision list` shows parked forks with their ids and questions.

## Hard rules

- **Never** write `status: done` in a REQ, and **never** hand-edit `.devsteward/state.yaml` — the
  engine owns both. Faking green is the false-done hole the gate exists to close. If a `done` REQ
  still surfaces a parked `:validate` decision (a diverged ledger), the sanctioned exit is `steward
  validate REQ-NNN`, which reconciles it from the event log — not a hand-edit.
- **Never** create, switch, or merge a branch to do REQ work. Everything is on `dev`.
- **Never** read the DevSteward engine source to operate it. This manual is the contract; the
  `steward` CLI is the API.
- Move a REQ's frontmatter, its `REQUIREMENTS_INDEX.md` row, and the code that satisfies it in the
  **same commit** (the engine does this for you on a checkpoint).
