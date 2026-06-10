# 03 · The REQ workflow

The shipped profile turns every active requirement into a single develop checkpoint and
sequences requirements by their dependencies.

## One develop step per requirement (REQ-029)

For each active REQ (`open` / `in-progress` / `blocked`) the REQ profile derives **one**
step:

| Step | What happens | Verified? |
|------|--------------|-----------|
| `REQ-NNN:develop` | Plan-first → implement → write & green the acceptance tests | **yes** |

`develop` is the single Claude session — the fused successor to the old `design → build →
land` triple (which paid three cold sessions where two verified nothing). It carries the
REQ's acceptance `test:` commands as its verification, so the engine re-runs them before
marking the requirement done.

On a **green** develop gate the engine performs the **mechanical land** itself — status
flip, index sync, the single commit, the `--no-ff` merge, ledger advance — with **no
Claude** (and it refuses unless a file in `docs/plans/` names the REQ). On a **red** gate it
spawns up to **two** fresh repair sessions (failure brief, default Sonnet), then parks. A
REQ that declared `develop: split` or `concept: true` is parked in batch, naming the
attended need, rather than driven headless. (See 02 · engine for the gate's teeth.)

## The V-model mapping: `check:` steers the phases

Each acceptance criterion's `check:` classification (see 01 · format) is a **routing
key** that maps it onto the V-model:

| `check:` | V-model side | Phase | Oracle |
|----------|--------------|-------|--------|
| `regression` | verification (left) | **Build** (inside `develop`) | coupled / mock, headless |
| `artifact` | validation (right) | **System-Test** | decoupled, durable (lab-produced; engine reads only the pass/fail signal) |
| `manual` | validation (right) | **System-Test** | human — a decision stop |

The phase names here are V-model *stages*, not step ids: the `develop` step does the
Build-side **verification** of every `regression` criterion (that is its gate). The
classification steers **phase existence**: a REQ with only `regression` criteria
runs no System-Test phase; any `artifact` *or* `manual` criterion makes the System-Test
(validation) phase apply. A human review *is* validation — system-level by definition —
which is why `manual` lives inside the System-Test phase rather than as a stray
module-level stop.

*Status:* the System-Test phase itself — its conditional flow-routing, the independent
System Tester session, and the first lab — is REQ-030/031 territory. Until it lands, the
taxonomy is seeded at intake and enforced by lint; an engine-driven land of a REQ with
`artifact`/`manual` criteria fails loudly rather than faking validation.

## Sequencing whole requirements

`REQ-B:develop` depends on `REQ-A:develop` for each `REQ-A` in `REQ-B.depends_on`. So a
requirement only starts once its prerequisites have fully landed, while **independent
requirements interleave freely**. A dependency that is already `done` is satisfied and
dropped; a dependency that is draft, dropped, or missing leaves the dependent correctly
blocked (and `steward lint` flags it).

## Branching model

DevSteward uses a two-line model. `main` is **production** — release tags are cut here and
consumers pin them. `dev` is the **integration** branch: the default working and merge
target. **Declaration lives on `dev`; only implementation branches** — intake (REQ
frontmatter, index row, roadmap), plans, and the ledger are committed directly on `dev` (a
requirement is a registry entry, not behavior; forking the shared registry races id
allocation and conflicts the index/roadmap), while **implementation** (code + acceptance
tests + the status-flip to `done`) goes on a feature branch and merges into `dev` by a plain
local merge (no PR). `dev` is promoted to `main` via a PR.

This is **engine-enforced**, not just convention: before any step runs, the executor checks
the current branch, and if it is the production branch it **refuses** — it invokes no
`claude`, commits nothing, leaves the step pending, and prints a guard message naming the
branch and the fix. Off the production branch it proceeds normally. The branch names are
configurable in `.devsteward/config.yaml`:

```yaml
git:
  production_branch: main          # repos using `master`/`release` set it here
  integration_branch: dev
  feature_branch: req-{num}-{slug} # name for an auto-managed implementation branch
```

The production guard has no opt-out — strictness is the point — and it never opens PRs
(`dev → main` stays a human PR).

**The executor manages the implementation feature branch** (it no longer merely refuses to
implement on the integration branch). When a `develop` step is eligible on the integration
branch it lazily **creates and switches** to `feature_branch` (`{num}` is the REQ id without
the `REQ-` prefix; `{slug}` a short slug of the title) and runs the step there; a partial
prior run's branch is **reused** (a *diverged* one is surfaced, not merged over). After a
**green develop** the mechanical land commits the trailing ledger write, switches back, and
merges `--no-ff` with the co-author trailer — leaving the integration branch clean at rest.
A failed or parked develop does **not** merge: the feature branch stays checked out for
inspection. Declaration (intake, plans, the ledger) is no longer a step — it is committed
directly on the integration branch — so the automation only ever branches the one
implementation phase.

## Two modes: batch worker vs. interactive pair

`/advance` is one skill run two ways, with **different contracts**. The fork that was once
ambiguous is settled: *the engine commands are a batch worker; the bare skill is an
interactive pair.* The switch is the `DEVSTEWARD_UNATTENDED` environment variable, which the
engine sets when it shells out.

- **Batch worker — `steward advance` / `steward run`.** Both drive `claude -p` headless
  (`DEVSTEWARD_UNATTENDED=1`); there is no human channel. The **engine owns the guarantees**:
  it re-runs the acceptance tests itself (teeth at the develop gate), lands the REQ
  mechanically on green (repairing up to twice on red, then parking), and advances the
  ledger. A fork is never asked — it is **parked** and surfaced. `steward advance` does one
  checkpoint; `steward run` marches every eligible step, parking on forks and stopping on a
  usage limit or hard failure so a human can look.
- **Interactive pair — `/advance` in a live session.** A person runs the skill directly in
  Claude Code. There is no executor in the loop and therefore **no engine guarantees**: the
  skill verifies, the skill commits (same-commit discipline), **the human advances the ledger
  by hand** (mark the step done + record the checkpoint, or the next `/advance` redoes it),
  and at a fork it asks via `AskUserQuestion`. The human reviewing the work is the guarantee —
  trust comes from the person, not the engine. *(That hand-advance of the ledger is the gap
  REQ-018's `steward checkpoint` closes — until it lands, it is a hand-edit of
  `.devsteward/`.)*

**One commit, one owner.** Commit ownership is exclusive by mode: the engine commits in
batch, the skill commits interactively — *never both*. (Earlier the skill committed even
under the engine, which then committed again — a double commit; resolved by keying the
skill's close step off `DEVSTEWARD_UNATTENDED`.)

## The fixed report

Every checkpoint ends the same way, so orientation is instant:

```
Did:       what this checkpoint produced
Cursor:    new ledger position
Review:    one line — what to look at
Decisions: parked forks, or "none"
Next:      the next eligible step
```

## A day in the life

```sh
steward status                       # where are we?
/intake "let users export to CSV"    # interview → draft REQ-014
steward lint                         # green?
steward advance                      # develop REQ-014 (plan + code + tests; engine lands on green)
# or, hands-off:
steward run                          # march everything eligible; park on forks
steward decision list                # anything parked?
steward decision answer DEC-001 "use RFC 4180 quoting"
steward run                          # resume
```
