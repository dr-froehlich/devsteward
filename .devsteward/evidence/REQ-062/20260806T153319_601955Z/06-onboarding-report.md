# REQ-062 — memzy onboarding report (the first live retrofit)

**Date:** 2026-08-01
**Target:** `/home/peter/projects/memzy` @ `66e073a`, branch `dev` (clean tree at start)
**Driver:** attended `/advance REQ-062 develop`, running the shipped `/onboard` skill (REQ-024)
**Engine:** the pipx editable `steward` → this repo on `dev`

This is the proof record REQ-062 asks for: what ran, each gate's result, and what surfaced.
memzy's actual repo changes live in memzy's own git (Decision 3); DevSteward records only
that it happened.

## Preamble — the target was wrong on arrival

The session was invoked as `/advance REQ-017 develop, apply to ../memzy`, and the working
tree already carried an uncommitted `draft → open` promotion of **REQ-017**. REQ-017 is the
legacy-**prose** converter for **ExamEngineer**; memzy has **zero** prose-header REQs (all 31
of its REQ files already carried YAML frontmatter — REQ-010's territory). Applying REQ-017 to
memzy is a null operation.

The operator confirmed the intended work was the **memzy onboarding**, which is already
specced as **REQ-062**. The REQ-017 promotion was reverted; REQ-062 was the target driven.

A second, unrelated promotion (`REQ-062: draft → open`) was already present in the working
tree but **invisible to `git status`** — a racy-timestamp stat-cache miss; it only surfaced
once `git checkout` refreshed the index. Worth knowing: `git status` alone is not proof of a
clean tree immediately after a write.

## Pipeline

### §0 Orient — doc layout (REQ-084)

memzy's `docs/` is a **plain in-repo tree** — no mkdocs / Sphinx / Docusaurus config — and
memzy already keeps its corpus in `docs/requirements/` and its plans in `docs/plans/`. The
conventional layout *is* memzy's own layout, so all four seams took their defaults. This was
settled from evidence, not preference, so no operator fork was raised (contrast: recipes,
whose plans landed in a published `docs/` tree because nothing had been decided).

Branches confirmed from the repo, not assumed: `main` (production) + `dev` (integration).

### §1 Convert the corpus — **gate: `steward lint` → GREEN**

```
python3 scripts/convert_reqs.py <memzy>/docs/requirements <memzy>/docs/requirements
→ converted 31 REQ(s)
```

- `kind` injected on all 31 (29 `feature`, 1 `fix`, 1 `spec` — the north star REQ-001).
- `## Acceptance criteria` checkboxes transcoded into `yaml acceptance` blocks, verdicts
  preserved (`[x]` → `passed`).
- `supersedes: []` → `null`; the non-schema `superseded_by` key dropped (1 file, intended).
- Index rows rewritten to match the linter's row regex; **the surrounding prose survived** —
  the "Planned" table and the whole `## Scenarios` (SCN-001…005) section are intact (REQ-023
  splice).

**Idempotency verified on the live corpus:** a second conversion run over the converted tree
was a byte-for-byte no-op (`diff -r` clean). REQ-010 Decision 7 holds against real input, not
just fixtures.

### §2 Seed the ledger — **gate: `steward status` → GREEN**

```
steward init          → Initialized .devsteward/ (req profile)
steward seed-ledger   → Seeded 30 terminal REQ(s)
steward status        → all active requirements done  (empty work queue)
```

30 terminal REQs seeded (29 `done` + 1 `superseded`). The one non-terminal REQ is **REQ-001**,
memzy's permanently-`draft` north star — correctly producing no step. `advance` is a no-op
until memzy's next `/intake`, which is exactly the caught-up state REQ-062 asks for.

### §3 Stamp the scaffold — merge, never overwrite

Config written **first** (REQ-084) with memzy's real branch names and the four doc paths, plus
a `verify:` block matched to memzy being a Django project: `python: .venv/bin/python`,
`env_file: .env` (REQ-072), `full_suite: python -m pytest`. Verified live: **326 tests collect**
under that interpreter.

```
steward sync → advance, bootstrap, intake, system-test, STEWARD.md  (5 refreshed)
```

- **`onboard` is correctly absent** from the stamped set — `skillsync.OPERATOR_ONLY`, REQ-084's
  rule, observed live for the first time on a real target.
- `.devsteward/stamped.lock` written — the provenance lock a fresh `steward new` gets, and the
  thing FlowSteward's pre-REQ-057 onboarding never had.
- **Nothing clobbered:** memzy's `.claude/settings.local.json` (13 KB) is byte-identical, mtime
  still Jul 26. memzy owned no skills, so there were no name collisions.

Two §3 items `steward sync` does **not** cover, completed by hand:

- **`_templates/`** — copied into `docs/requirements/_templates/` (no-clobber). This is not
  cosmetic: the stamped `/intake` skill reads `_templates/req.md`, so without it memzy's very
  next intake would have broken. See Finding 2.
- **`.gitignore`** — appended `.claude/settings.local.json` + `.claude/scheduled_tasks.lock`
  (mirroring this repo's convention), with an explicit note that `.claude/skills/` **and** the
  `.devsteward/` ledger *are* tracked.

### §4 Reconcile CLAUDE.md — fold in, don't flatten

memzy's domain voice is untouched: the Latin/FSRS overview, the py-fsrs service boundary and
`owner`-FK invariants, the GDPR/no-PII hard constraint, the Quarto teacher-manual section, and
the "decisions belong in REQs" rule all stand as written.

Three passages had been made **factually false** by the migration and were rewritten:

1. **The frontmatter example** still showed the pre-conversion dialect (no `kind`, no
   `supersedes`, prose-checkbox acceptance). Replaced with the hybrid schema plus a
   `yaml acceptance` block showing the `check:` axis.
2. **"Completing a REQ: set `status: done`"** — the false-done hole. Rewritten: the engine is
   the verifying bookkeeper; `steward checkpoint` flips frontmatter *and* index only on green;
   an `artifact`/`manual` criterion defers the land to `steward validate`.
3. **"branch before committing on `main`"** — replaced with the trunk-based model (all work on
   `dev`, never commit to `main`, the only branch op is the human-gated `dev → main` PR).

Added: a black-box pointer to `STEWARD.md`, the ledger contract, the `/intake` → `/advance`
workflow, and the `python -m pytest` rule (REQ-040's lesson — bare `pytest` can resolve to
another checkout's stale editable install). Also **subtracted** the hand-maintained "next REQ
is REQ-010" status narrative, which had drifted ~29 REQs behind reality — status now points at
the index ↔ frontmatter pair and `steward status` (`[[roadmap-never-tracks-status]]` doctrine:
a status copy with no writer always drifts; subtract it, don't add a synchronizer).

## Findings

### Finding 1 — `steward lint` necessarily goes RED between `seed-ledger` and the first commit

**Observed:** lint was green after §1 and red after §2, on two REQs:

```
✗ REQ-018: ledger develop step is 'done' but the committed marker lags —
           HEAD frontmatter 'superseded', index row 'ABSENT'
✗ REQ-039: ... HEAD frontmatter 'done', index row 'ABSENT'
```

**Cause — not a corpus defect.** REQ-077's symmetric HEAD-reading lint compares the seeded
`done` steps against the **committed** markers. HEAD still held the *pre-conversion* index,
whose rows carry annotations the linter's row regex rejects — `superseded *(by REQ-020)*` and
`done *(2026-07-26)*`. Those are precisely the rows the converter normalized in the working
tree. The rule fires only after seeding because before that the ledger had no `done` steps to
compare. It resolves deterministically on the onboarding commit.

**Why it matters:** `/onboard` says "**stop on any red verification gate** — onboarding must
never declare success on an unlinted corpus". Followed literally, a *correct* onboarding halts
here. The skill's §2 gate and REQ-077's HEAD-marker rule have an unstated ordering dependency:
the corpus must be **committed** before the HEAD-comparison can be meaningful. Routes to
REQ-024 (skill text) and/or REQ-022 (`seed-ledger`) — not patched inside this proof
(REQ-062 out-of-scope, Decision: a surfaced defect returns to the machinery REQ).

**Confirmed:** the onboarding commit (memzy `a00444e`) turned lint green with no other change —
`lint: OK`, exit 0, clean tree. The red was entirely the uncommitted-HEAD artifact diagnosed
above, and nothing was hand-forced past it.

Two candidate cures, for whoever picks it up:
- **Skill-level (cheap):** `/onboard` sequences the conversion commit *before* `seed-ledger`,
  and says so; the gate then means what it claims at every point.
- **Engine-level:** `seed-ledger` (or lint) suppresses the HEAD-marker rule for steps seeded
  from historic record, which by construction have no committed flip of their own.

### Finding 2 — `steward sync` does not seed `_templates/`, but the stamped `/intake` requires it

`/onboard` §3 lists `_templates/` among what the stamp must bring in, and
`templates/.claude/skills/intake/SKILL.md:214` writes new REQs *from* `_templates/req.md` — but
`steward sync` seeds only the skills and `STEWARD.md`. A project onboarded by the skill as
written therefore gets an `/intake` that references a file it does not have. Copied by hand
here; the durable fix is for `sync` to seed `_templates/` (same customized-refusal semantics as
the rest). Routes to REQ-066 / REQ-024.

### Finding 3 — the converter drops unknown frontmatter keys silently

memzy's REQ-039 carried `amends: [REQ-013]`, a relation memzy authored deliberately ("Recording
it as an amendment (not silently) is the point"). The converter dropped it with no report, the
same path as the known `superseded_by`. Across 31 files exactly two keys were dropped
(`superseded_by` ×1, `amends` ×1), so the blast radius is small, and here the *fact* survives
in REQ-039's prose (its M6 row) and in `depends_on: [… REQ-013 …]` — no information was
actually lost this time.

Still, "non-destructive" (REQ-010 Decision 7) is asserted for *prose*, not for frontmatter, and
a migration that silently discards a maintainer's typed relation is a quiet failure mode. The
cure is a **report**, not preservation: the converter should list dropped non-schema keys per
file so the operator can judge. Low priority; routes to REQ-010's converter.

## Post-onboarding state

memzy's onboarding commit: **`a00444e`** on branch `dev` — 46 files, +2594/−1129, clean tree
after. Its parent `66e073a` is the pre-onboarding state, so the whole retrofit reverts with a
single `git revert`.

| Gate | Result |
|------|--------|
| `steward lint` (memzy root) | **GREEN** — green after §1, red pre-commit by Finding 1, green again after `a00444e` |
| `steward status` (memzy root) | GREEN — all active requirements done, empty work queue |
| `.claude/settings.local.json` preserved | YES — byte-identical, mtime unchanged |
| `ROADMAP` / Scenarios / Planned table preserved | YES — REQ-023 splice, prose intact |
| CLAUDE.md domain guidance preserved | YES — GDPR, FSRS boundary, teacher manual all stand |
| `.devsteward/stamped.lock` seeded | YES |
| `onboard` skill excluded from the stamp | YES — REQ-084 operator-only, confirmed live |

memzy is now a caught-up steward project: `steward status` reports an empty work queue, and the
next act on it is a `/intake`, which will produce the first REQ the engine drives end-to-end.

## Sign-off

REQ-062's AC1 is a `manual` criterion — a human inspects memzy's post-onboard state and signs
off. This report is the develop deliverable; the sign-off runs separately via
`steward validate REQ-062` in a plain shell, following the validation procedure in the REQ.
