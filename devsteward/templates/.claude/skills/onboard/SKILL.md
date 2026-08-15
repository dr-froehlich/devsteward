---
name: onboard
description: Bring an existing project under the steward engine. Use once per project being migrated, pointing at that project — orchestrates the conversion, ledger seed, scaffold stamp, and CLAUDE.md reconciliation in order, gating each step on steward lint/status and merging (never overwriting) the target's existing artifacts. The retrofit analog of /bootstrap (which is for fresh projects).
---

# /onboard — migrate an existing project under the engine

`/bootstrap` brings a *fresh* `steward new` project to life; **`/onboard` retrofits an
*existing* one** — a project with its own REQ corpus, CLAUDE.md, and `.claude/` that predate
DevSteward. It is an **operator tool**: run by the person performing the migration, pointed at
the project being migrated, *not* shipped to consumers (a stamped project is already onboarded
and never runs this). The skill **orchestrates already-tested tools and owns no migration logic**
— it is the procedure and the per-project judgement over `convert_reqs.py`, `steward
seed-ledger`, `steward new`, and a CLAUDE.md merge. Drive the steps **in order**, and
**stop on any red verification gate** — onboarding must never declare success on an unlinted
corpus or an empty ledger.

The order is load-bearing, not stylistic — §2 exists because §3's gate cannot mean anything
before it (REQ-086 Finding 1):

| # | step | gate |
|---|------|------|
| 1 | Convert the REQ corpus | `steward lint` clean |
| 2 | **Commit the converted corpus** | working tree clean |
| 3 | Seed the ledger | `steward status` empty queue, `steward lint` still clean |
| 4 | Stamp the scaffold | — |
| 5 | Reconcile CLAUDE.md | — |

memzy is the first project retrofitted with this skill; the live memzy run is its own tracked
proof REQ (REQ-062), not part of running this skill the first time.

## 0. Orient

- Confirm the target: the project's repo root, its current REQ-corpus location, and its real
  branch names (you need them for config).
- **Decide where the engine's documents go, before touching anything (REQ-084).** Four paths
  are configurable — `requirements_dir`, `index_file`, `plans_dir`, `concepts_dir` (defaults
  `docs/requirements/`, `docs/plans/`, `docs/concepts/`). A retrofit target often cannot use
  them: if its `docs/` is owned by a docs generator (mkdocs, Sphinx, Docusaurus — everything
  under it is built and deployed), putting REQs, plans or concepts there publishes the
  engine's internals. **Ask the operator** where they should live (e.g. a top-level
  `requirements/` with `requirements/plans/`), and treat the answer as binding for every
  later step. This is where recipes was bitten: its corpus was placed correctly and its
  plans landed in the published `docs/` tree because nothing had been decided for them.
- Read the target's existing `CLAUDE.md`, `.claude/`, and `REQUIREMENTS_INDEX.md` before
  touching anything — onboarding **merges into** accumulated knowledge, it does not stamp over it.

## 1. Convert the REQ corpus (gate: `steward lint`)

Run the converter in place — it is non-destructive and idempotent:

```sh
python3 <devsteward>/scripts/convert_reqs.py <corpus-dir> <corpus-dir>   # e.g. docs/requirements
```

This injects `kind`, lifts `## Acceptance criteria` checkboxes into `yaml acceptance` blocks,
normalizes `supersedes`, and **splices** the generated REQ table into `REQUIREMENTS_INDEX.md`
(the REQ-023 splice — it replaces only the REQ rows and **preserves** the target's surrounding
prose, e.g. a "Planned" table or "Scenarios" section).

**Gate:** run `steward lint` from the target root. It must be **clean**. If it is red — a kind it
could not infer, an id the schema rejects, a missing row — **stop**: fix the cause (or park, see
§6) before seeding. Never seed an unlinted corpus.

## 2. Commit the converted corpus — **before** seeding the ledger

Commit the conversion in the target's git (on its integration branch, with the attribution
trailer) so the working tree is clean before `seed-ledger` runs.

**This ordering is required, not tidiness.** REQ-077's symmetric lint rule compares each
ledger step seeded `done` against the **committed** marker — the frontmatter and index row at
**HEAD**, not in the working tree. Seed before committing and HEAD still holds the
*pre-conversion* corpus, whose historic index cells carry annotations the row regex rejects
(`superseded *(by REQ-020)*`, `done *(2026-07-26)*`) — exactly the rows the converter has just
normalized *in the working tree*. Lint then reports them as `ABSENT`:

```
✗ REQ-018: ledger develop step is 'done' but the committed marker lags —
           HEAD frontmatter 'superseded', index row 'ABSENT'
```

The rule is firing correctly; it is being asked a question that has no meaningful answer yet.
The rule can only fire *after* seeding (before that the ledger has no `done` steps to compare),
so the only cure is to make HEAD current first. That is what this step does — and it is why a
correct onboarding must never present its operator with a red lint gate to wave through. If
the gate is red **after** the commit, it is a real problem: **stop** (§6).

Do **not** weaken or suppress the lint rule to get past this. REQ-077's guard exists because it
caught real divergence; the ordering is the honest fix.

## 3. Seed the ledger (gate: `steward status`)

The corpus is built history; the engine must see every terminal REQ's phase-step(s) as `done` or
it will try to re-Design built work.

```sh
steward init          # creates the empty ledger (.devsteward/) if absent
steward seed-ledger   # marks every terminal REQ's develop (+ validate) step done
```

**Gate:** run `steward status`. It must show the finished corpus **all-done with an empty work
queue** (no eligible steps until a new REQ is intaken). If active steps remain, the seed is
incomplete — **stop** and reconcile before stamping. Re-run `steward lint` here too: with §2's
commit in place it is now comparing the seeded steps against a current HEAD, so a red here is
a real divergence and a hard stop.

## 4. Stamp the scaffold — **merge, never overwrite**

**Write the config first (REQ-084).** Before copying a single artifact, put
`.devsteward/config.yaml` in place carrying the project's **real**
`production_branch`/`integration_branch` **and** the four doc paths decided in §0 —
`requirements_dir`, `index_file`, `plans_dir`, `concepts_dir`. Everything below then goes to
*those* paths; nothing is written under `docs/` unless the config says so. The engine reads
the same keys, so the land gates look exactly where you put the artifacts.

Then bring in the scaffolding the engine needs: the **widened** REQ schema (REQ-021 lettered
ids), a plans dir, and `.gitignore` additions for the `.devsteward/` runtime.
(`<requirements_dir>/_templates/req.md` — the file the stamped `/intake` writes new REQs from
— is *not* a hand-copy: `steward sync` below seeds it, REQ-086 Finding 2.)

The target already has a `.claude/` and an 8 KB CLAUDE.md — so this is a **merge**:

- Check for **skill-name collisions** and an existing `settings.json` before copying any skill.
- Keep the target's **richer artifacts** (its living docs, its domain skills) — do not clobber them.
- Add only what is missing; leave what the project already owns.

A stamp that overwrites the target's accumulated knowledge is a regression, not a migration.

**Seed the engine-owned artifacts with `steward sync` (REQ-066).** `onboard` does not run
`steward new`, so it never seeded the provenance lock — that is *why* a project onboarded
before REQ-057 (e.g. FlowSteward) ended with neither a `STEWARD.md` manual nor a
`.devsteward/stamped.lock`. Run **`steward sync`** as part of this step: it stamps the missing
engine-owned artifacts (the bundled skills, the root `STEWARD.md`, and the REQ template at
`<requirements_dir>/_templates/req.md`) from the installed template and writes a populated
`.devsteward/stamped.lock`, giving the retrofitted project the
same baseline a fresh `steward new` project gets. **Run it *after* the config is written** —
the REQ template lands at the `requirements_dir` the config names, not under `docs/` by
assumption. `sync`'s customized-refusal **preserves any
same-named artifact the project already owns** (reported customized, refused without `--force`)
— so this honours "merge, never overwrite" while closing the manual gap. `sync` seeds the
**consumer** skills only; this skill is operator-only and is never stamped into a target
(REQ-024 Decision 2, enforced by `skillsync.OPERATOR_ONLY` since REQ-084) — a migrated project
is already onboarded.

## 5. Reconcile CLAUDE.md — fold in, don't flatten

Fold the **house conventions** into the target's existing CLAUDE.md *without discarding its domain
guidance*:

- **same-commit discipline** (REQ frontmatter + index row + code in one commit),
- the **ledger contract** (state lives in `.devsteward/`, never in REQ files),
- the **branching model** (trunk-based, work lands on `dev`),
- the **attribution trailer**.

This is an edit/merge against the project's own §-structure (e.g. memzy's Django/py-fsrs
guidance, its no-PII invariant) — preserve that voice; add the contracts it now inherits.

## Out of scope

- **Re-implementing** conversion/seeding logic in this skill — it only orchestrates the tested
  tools (the logic stays in `convert_reqs.py` / `steward seed-ledger`, independently verifiable).
- **Scenario (`SCN-*`) conversion** — left as living docs, same boundary as the
  converter (REQ-010).
- **Mutating the target's live repo as a deliverable** of this skill — the live retrofit (memzy
  end-to-end) is its own tracked proof REQ (REQ-062), gated by its own `steward lint`/`status`.

## 6. Park-and-surface

`/onboard` is normally run interactively, where a fork (an ambiguous `kind`, a `.claude/` or
CLAUDE.md merge conflict, a branch-name you cannot confirm) is a question you **ask**. If it is
ever invoked headless with `DEVSTEWARD_UNATTENDED=1` set, obey the same contract as the other
skills: do **not** guess — append a decision request to `.devsteward/state.yaml` under
`decisions:` (`{id, step, question, status: open}`) and **stop**. A red verification gate is
likewise a hard stop, attended or not: never onboard past an unlinted corpus or a non-empty queue.
