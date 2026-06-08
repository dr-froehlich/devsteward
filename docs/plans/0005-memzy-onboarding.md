# 0005 — Onboard memzy onto the steward engine

**Date:** 2026-06-08
**Status:** Plan only — no code/files changed yet. Scope decided with the operator:
*plan everything, build nothing*; the lettered-id divergence is resolved by **relaxing the
schema** (not renumbering memzy).
**Builds on:** [0004 — memzy converter (REQ-010)](0004-memzy-converter.md). REQ-010 shipped
the dialect normalizer + fixtures; this plan covers the *rest* of bringing memzy fully under
`steward`, plus the one divergence REQ-010's gap table did not anticipate.

## What was actually verified (not assumed)

The REQ-010 converter was run against memzy's **live** `docs/requirements/` into a throwaway
dir and the result was linted with the real engine:

- **23 REQ files convert cleanly** — `kind` injected, `## Acceptance criteria` checkboxes →
  `yaml acceptance` blocks (verdicts preserved), `supersedes` normalized, index rewritten,
  prose byte-preserved.
- **Lint returns exactly 3 problems, all one root cause** — memzy's lettered umbrella ids:

  ```
  REQ-027.md: schema: depends_on.5: 'REQ-028p' does not match '^REQ-[0-9]{3}$'
  REQ-028p.md: schema: id: 'REQ-028p' does not match '^REQ-[0-9]{3}$'
  REQ-028p: missing a row in REQUIREMENTS_INDEX.md   (downstream of the same regex)
  ```

memzy authored `REQ-028p` (and has planned `REQ-028s`, `REQ-014a–d`) to mean "umbrella REQ
split into sub-parts." Only `REQ-028p` is a *live file* today; the rest are roadmap entries.
DevSteward's id regex is `^REQ-[0-9]{3}$`, so the suffix is rejected. **Decision: widen the
format to accept an optional lowercase letter suffix** — memzy's history and `[[REQ-028p]]`
backlinks travel verbatim; the format gains a legitimate "split umbrella" affordance.

## The five pieces of a *full* onboarding

Normalizing the REQ files is step 1 of 5. "memzy uses steward" means `steward status` /
`steward advance` resolve real steps from a real ledger. The pieces:

1. **Schema relaxation** (a DevSteward REQ — changes shipped behavior). *Below.*
2. **REQ corpus conversion** — run `scripts/convert_reqs.py` over memzy in place. Gated on (1).
3. **Ledger seed** — `.devsteward/` config + state + events for an *already-built* project.
4. **Scaffold stamp** — skills, schema copy, `_templates/`, `.gitignore`, install `steward`.
5. **CLAUDE.md reconciliation** — fold DevSteward house conventions into memzy's own.

Scenarios (`SCN-*`), `ROADMAP.md`, and the "Planned" table are **out of scope** (as in
REQ-010) — they convert later, REQ-017-style, or stay as living docs.

---

## Piece 1 — Relax the id format (new DevSteward REQ, on `dev`)

New id pattern: `^REQ-[0-9]{3}[a-z]?$`. The `[a-z]?` is a *suffix on an existing 3-digit
number*, never a replacement for it — `REQ-028p` is part of the `REQ-028` family.

Touch points (all must move in one commit per same-commit discipline):

| File | Line(s) | Change |
|------|---------|--------|
| `devsteward/schema/req.schema.json` | 12 (`id`), 42 (`depends_on.items`), 57 (`supersedes`) | `[0-9]{3}` → `[0-9]{3}[a-z]?` (the **package** copy lint actually loads via `files("devsteward")`) |
| `devsteward/templates/docs/requirements/schema/req.schema.json` | same 3 | keep in sync so future `steward new` consumers get the wider format |
| `devsteward/lint.py` | 29 (`_INDEX_ROW_RE`, currently `(REQ-\d{3})`) | `(REQ-\d{3}[a-z]?)` so index rows for lettered ids parse |

**Must also check (not yet confirmed):**

- `devsteward/profiles/req/source.py` — step derivation builds `REQ-NNN:design/build/land`
  ids and depends-on edges by string. memzy's lettered REQs are all `done`, so they yield
  **no active steps today** — but if `REQ-028p` is ever reopened, the step source and the
  `REQ-...:phase` parsing must tolerate the suffix. Verify `step` id parsing doesn't assume
  exactly 3 digits before reopening any lettered REQ.
- `scripts/convert_reqs.py` `build_index` already emits `| REQ-028p | … |` verbatim, so once
  `_INDEX_ROW_RE` widens, the "missing row" problem clears with no converter change.
- The REQ-010 acceptance suite + dogfood `steward lint` must stay green after widening (the
  regex only *adds* matches; existing 3-digit ids are unaffected).

Acceptance for this REQ: a fixture REQ with a lettered id (`REQ-099z`) lints clean, appears
in the index, and is referenced from another REQ's `depends_on` without error; all existing
tests pass.

## Piece 2 — Convert memzy's corpus in place

Once Piece 1 lands on `dev` and `steward` is reinstalled (`pipx install --editable .`):

```sh
cd /home/peter/projects/memzy
python3 /home/peter/projects/devsteward/scripts/convert_reqs.py \
    docs/requirements docs/requirements      # in place; converter is non-destructive + idempotent
```

Then verify against memzy (not the temp dir): `steward lint` from memzy's root must be clean.
The converter rewrites `REQUIREMENTS_INDEX.md`'s **table** but leaves memzy's surrounding prose
(the "Planned" table, "Scenarios" section) — confirm those are preserved (idempotency covers the
REQ section; the index rewrite replaces only the rows it generates — **re-check** it doesn't
clobber memzy's Planned/Scenarios sections, since `build_index` emits a *whole* file. This is a
real risk: `convert_corpus` writes `build_index(...)` over the entire `REQUIREMENTS_INDEX.md`,
discarding memzy's Planned + Scenarios sections. **Mitigation:** either splice rows into the
existing index instead of overwriting, or accept the loss and move Planned/Scenarios elsewhere.
Decide before running in place.)

## Piece 3 — Seed the ledger for an already-built project

There is **no `steward import-ledger`** today. `steward init` (`cli.py:322`, `Ledger.init`)
creates an *empty* ledger; it does not mark historic REQs done. All 23 memzy REQs are terminal,
so the engine must see every `REQ-NNN:{design,build,land}` as `done` or it will try to re-Design
built work.

Options:
- **(a) Small seeder** — a script that, for each non-active REQ, writes `done` statuses via
  `Ledger.set_status` and appends one synthetic `system`/import event. Reusable for the next
  onboarding; arguably belongs beside `convert_reqs.py`. *Recommended.*
- **(b) Hand-authored `state.yaml` + `events.jsonl`** — fast for one project, not repeatable.

Note: memzy's `done` REQs become *exempt* from the test-id lint (REQ-010's rule-5 relaxation),
and the step source yields steps only for **active** REQs — so a seeded done-corpus produces an
empty work queue, which is correct: `steward status` shows everything done, `advance` is a no-op
until a new REQ is intaken. Config: copy `config.yaml.tmpl`, set
`production_branch`/`integration_branch` to memzy's actual branches (verify what they are).

## Piece 4 — Stamp the scaffold

From `devsteward/templates/`: `.claude/skills/{advance,intake,bootstrap}/SKILL.md`,
`docs/requirements/schema/req.schema.json` (the widened one), `_templates/`, `scenarios/`,
ROADMAP placeholder (memzy already has a richer one — keep memzy's), `.gitignore` additions for
`.devsteward/` runtime. memzy already has a `.claude/` — **merge, don't overwrite**: check for
skill-name collisions and existing settings.json. Then `pipx install devsteward` (or pin a tag)
so `steward` is on PATH in memzy's environment.

## Piece 5 — Reconcile CLAUDE.md

memzy has its own 8 KB CLAUDE.md. DevSteward's consumer template
(`templates/CLAUDE.md.tmpl`) carries the house contracts memzy now inherits: same-commit
discipline (REQ frontmatter + index row + code in one commit), the ledger contract (state in
`.devsteward/`, never in REQ files), the branching model, the co-author trailer. Fold these in
**without** discarding memzy's domain-specific guidance (Django/py-fsrs, the §4/copyright
posture, the no-PII invariant). This is an edit/merge, not a stamp.

## Suggested order

1. (DevSteward, `dev`) Piece 1 as a REQ — design → build → land, dogfooded through `steward`.
2. (DevSteward, `dev`) decide the index-overwrite question (Piece 2 mitigation) + write the
   ledger seeder (Piece 3a) if reusable — likely its own REQ ("onboard an existing project").
3. (memzy) Pieces 2→5 in order, each verified by `steward lint` / `steward status` from memzy.

## Open questions for the operator

- **Index overwrite (Piece 2):** splice rows, or let conversion own the whole index file and
  relocate memzy's Planned/Scenarios? (Blocks running the converter in place.)
- **Ledger seeder (Piece 3):** build the reusable seeder, or hand-author memzy's ledger once?
- **Scenarios (`SCN-*`):** leave as living docs, or schedule a converter REQ for them too?
