# REQ-085 — THermo prose retrofit

Two parts, in order: extend `scripts/convert_reqs_prose.py` to the grammar THermo's live
corpus actually uses (verified in this repo's suite), then drive the live onboarding
(an attended develop-session obligation, Decision 2).

Trial conversion re-run at the start of this session against THermo `e45f4ac` — the same five
blockers the intake recorded, no drift.

## Part 1 — the converter extension

### Where the aborts actually come from

The intake named four constructs; the trial run shows two of them share one cause:

| file | reported abort | actual cause |
|------|----------------|--------------|
| REQ-011, REQ-012 | content before the first field bullet | the `> **SUPERSEDED by …**` banner |
| REQ-017 | duplicate `notes` field bullet | a second `- **Notes:**` prepended by REQ-025 |
| REQ-026, REQ-027 | `depends_on` carries prose beyond its bullet line | the **unknown** `- **Implementation plan:**` bullet, which is appended to whatever segment is open — `depends_on` |

So construct 4 (the ninth field) is what unblocks REQ-026/027, not the `Depends on:` prose.
The prose-`Depends on:` problem is real but *silent*, which is worse: the qualifier text is
dropped and every `REQ-NNN` token inside it becomes a dependency — today REQ-028's
`… ; found by REQ-027's suite on bench device GIMYB` yields a spurious `REQ-027` dep and
REQ-012's `REQ-026 (was REQ-011, superseded 2026-07-04)` yields both ids, with the explanation
gone. Decision 4 is what makes that legible: extract every id (unchanged), **preserve the raw
line** so no qualifier is lost, and **report** the carry so the operator can check it.

### Structure

`convert_prose_text` is per-file, but `supersedes:` is a *corpus* relation (REQ-011's banner
determines REQ-026's frontmatter). So the parse is split:

- `parse_prose_req(text, *, name) -> ParsedProse` — rid, title, segments, `banner`,
  `merges`, `dep_carry`, `supersedes_of` (from either encoding). Pure, no rendering.
- `render_prose_req(parsed, *, supersedes=None) -> str` — frontmatter + body.
- `convert_prose_text(text, *, name, supersedes=None)` — the two composed; unchanged
  signature plus one optional keyword, so REQ-017's suite keeps working.
- `convert_corpus_prose` becomes two-pass: parse all → resolve the supersedes map → render.

`split_fields` stays as a 3-tuple wrapper over the new parse (REQ-017's tests call it).

### The four constructs (enumerated rule, never tolerance — Decision 3)

1. **Header banner.** Leading content before the first field bullet is accepted **only** when
   every non-blank line of it is a blockquote (`>`); anything else still aborts exactly as
   today. It rides into the body verbatim, directly under the preserved `### REQ-NNN:` header.
2. **Prose `Depends on:`.** Ids: every `REQ-NNN` token in source order (existing behaviour).
   When the line carries anything beyond the ids and their separators, the **raw line** is
   emitted into the body as `**Depends on:** <raw>` and the carry is reported.
3. **Repeated field bullets.** Merged in source order into one segment (blank line between),
   reported. No abort — two `- **Notes:**` bullets are two notes.
4. **`Implementation plan:`** — a ninth known field name, inline-only, rendered as a
   `**Implementation plan:** <raw>` prose line in the body. No `plan_refs:` schema field
   (Decision 6); DevSteward's plans gate already finds `<plans_dir>/REQ-NNN*.md` by convention.

### `supersedes:` (Decision 7)

Two stated encodings, both on the *superseded* side pointing at the superseding REQ:

- banner `> **SUPERSEDED by [REQ-026](…)**` on REQ-011 → `supersedes: REQ-011` on **REQ-026**;
- `- **Depends on:** REQ-011 (supersedes it)` on REQ-026 → the same edge.

Per superseding id the two extractions must agree: both non-empty and different → abort.
More than one distinct superseded id for one REQ → abort (the schema holds one string; a
silent drop is exactly what this rescues). Every extraction is reported.

Direction matters and is asserted: REQ-026 supersedes REQ-011, REQ-027 supersedes REQ-012.

### Fixtures (Decision 8)

`tests/fixtures/thermo_reqs/` and `thermo_reqs_golden/` are re-captured wholesale from
THermo's HEAD at conversion time — all 28 plus the index and the `REQ-xxx` stub — replacing
the 12. The commit message records the THermo SHA.

Consequences for REQ-017's existing suite, which asserts against the 12: the corpus is now
entirely terminal, so `report.demotions` is empty (Decision 10 is dormant, not dead) and the
title-conflict set grows from 2 to 11. Those assertions are retargeted, and the two
corpus-wide nodes are **renamed** to REQ-085's declared ids (`test_thermo28_…`) with REQ-017's
`test:` strings updated to follow — one oracle per property, no dangling node id.

## Part 2 — the live retrofit

Drive `/onboard`'s five steps against `/home/peter/projects/THermo` (clean, `dev`, `e45f4ac`),
with REQ-086's commit-before-seed ordering in force:

| # | step | THermo specifics |
|---|------|------------------|
| 0 | orient | paths are **singular** `doc/` (Decision 10): `doc/requirements`, `doc/requirements/REQUIREMENTS_INDEX.md`, `doc/plans`, `doc/concepts`; branches `main`/`dev` |
| 1 | convert | `convert_reqs_prose.py` in place; gate `steward lint` |
| 2 | **commit** | in THermo's git, on `dev` |
| 3 | seed ledger | 28 terminal REQs → empty work queue |
| 4 | stamp | merge into THermo's `.claude/`, config first, then `steward sync` (which now seeds `doc/requirements/_templates/req.md` — REQ-086) |
| 5 | CLAUDE.md | fold house conventions in, keep ESP-IDF build/flash + hardware guidance, replace the drifted Phase-5 status table with a pointer |

Ends as a caught-up steward project. THermo's changes commit in **THermo's** git (not pushed);
what lands here is the converter extension, the re-captured fixtures/goldens, and an
onboarding report under `docs/reports/` logging every judgement call — the 11 title rewrites,
the `supersedes:` extractions, the CLAUDE.md merge, and the captured SHA.

AC9 (manual) defers the land: the checkpoint commits `develop_committed` and the flip waits on
`steward validate REQ-085`.

## Out of scope

Per the REQ: no re-adjudicated verdicts, no authored north star, no `kind` correction on
THermo's REQ-001, no acceptance-test ids for imported REQs, no scenario/design-doc conversion,
no `plan_refs:` field. A *machinery* defect surfaced during the run routes back to REQ-086;
a *converter* defect is fixed here, in session.
