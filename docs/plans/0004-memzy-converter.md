# 0004 — memzy converter (REQ-010)

**Date:** 2026-06-08
**Status:** Design (REQ-010:design). Build + Land pending.
**REQ:** [REQ-010](../requirements/REQ-010.md) — normalize memzy's frontmatter REQ
dialect into the hybrid schema. `depends_on: REQ-002 (format/schema/linter)`.

memzy already crossed the frontmatter threshold on its own, so this is **not** a prose
parser — it is a **dialect normalizer** plus a one-line linter relaxation. REQ-010's
seven Decisions settle every governance question (faithful archivist, not judge; `[x]`→
`passed`; best-effort test ids; relax lint for terminal REQs; standalone script + fixtures;
idempotent/non-destructive). This design is purely *how*, against the real engine code.

## Approach in one paragraph

Add `devsteward/profiles/req/convert.py` — importable, pure-ish functions that take a parsed
source REQ (text in, text out) and a corpus driver — and a thin `scripts/convert_reqs.py`
CLI that reads a source `docs/requirements/` and writes a normalized copy. Relax `lint.py`
rule 5 so the test-id / empty-block checks fire only on **active** statuses (reusing
`ReqFile.is_active`), exempting terminal REQs like `draft` already is. Drive everything from
hermetic fixtures under `tests/fixtures/memzy/` that reproduce each gap in the REQ's dialect
table, and assert the converted corpus lints clean.

## Where the code lives (resolved from repo conventions)

- **Core, importable:** `devsteward/profiles/req/convert.py`. The converter is REQ-format
  aware and reuses `profiles/req/reqfile` (the parser) and `lint` — so it belongs beside the
  parser it depends on, not in the content-agnostic `core/`. Tests import
  `from devsteward.profiles.req.convert import …`, exactly like every other test imports the
  installed package (the repo has no importable `scripts/` package; pytest only puts `tests/`
  on the path). This also gives [[REQ-017]] a clean reuse seam for its prose front-end.
- **Entry point, thin:** `scripts/convert_reqs.py` — argparse `--src DIR --out DIR`, calls
  `convert_corpus(...)`, prints a summary. This satisfies Decision 6's "standalone script
  with importable functions": the script is the standalone CLI, the functions are importable.
  Running it on memzy's **live** repo stays a separate operator act (Decision 6), not part of
  landing this REQ.

## Public functions (the importable core)

```python
def infer_kind(fm: dict) -> str
    # default "feature"; REQ-001 / north-star title → "spec"; light tag/title heuristic
    # (e.g. tags containing "fix"/"bug" → "fix", "docs" → "docs", "refactor" → "refactor").

def transcode_acceptance(body: str) -> str
    # find the "## Acceptance criteria" section's "- [x]/[ ]" checkbox list; emit a single
    # ```yaml acceptance block: sequential AC1..ACn, text = checkbox text verbatim (minus the
    # marker), status = "passed" for [x] / "pending" for [ ], test = an embedded `test_*`
    # token (backtick-wrapped, matched by TEST_RE) if present else "". Returns the body with
    # the checkbox section replaced by the yaml block; prose around it byte-preserved.

def normalize_supersedes(fm: dict) -> dict
    # [] -> None; ["REQ-NNN"] (or "REQ-NNN") -> "REQ-NNN"; drop an unknown "superseded_by" key.

def convert_req(text: str) -> str
    # parse one source REQ; inject kind if absent; normalize supersedes; transcode acceptance;
    # carry every other frontmatter field unchanged; re-emit. Idempotent: converting output
    # is a no-op (kind already present, acceptance already a yaml block, supersedes already
    # normalized) and the prose is preserved byte-for-byte.

def rewrite_index(reqs: list[ReqFile], src_index: str) -> str
    # emit REQUIREMENTS_INDEX.md rows that lint._INDEX_ROW_RE matches, status (uppercased) in
    # sync with each converted REQ's frontmatter; drop memzy's lowercase + "*(by REQ-NNN)*"
    # annotations.

def convert_corpus(src: Path, out: Path) -> ConvertReport
    # the driver scripts/convert_reqs.py calls: convert every REQ-*.md, rewrite the index,
    # write into `out`. Non-destructive (writes a copy; never mutates `src`).
```

`AcceptanceCheck.status` is a free string in the model and the linter does **not** validate
acceptance status values, so emitting `passed`/`pending` per Decision 2 is tolerated even
though the *engine* writes `pass`/`fail` when it runs a live verification. `passed` is the
faithful imported-verdict marker; on reopen the engine re-runs and overwrites it. Noted, not
a divergence to fix.

## Linter relaxation (rule 5)

Today `lint.py:118-127` skips only `status == "draft"`. Change the guard to skip every
**non-active** REQ:

```python
for r in reqs:
    if not r.is_active:          # was: if r.status == "draft"
        continue
    if not r.acceptance:
        problems.append(f"{r.id}: no acceptance criteria block")
    for ac in r.acceptance:
        ...
```

`ReqFile.is_active` already exists (`ACTIVE_STATUSES = {open, in-progress, blocked}`).
Terminal REQs (`done`/`dropped`/`superseded`) become exempt like drafts — a record imported
as already-complete has nothing to land, so the "name a test before the gate runs" rule is
meaningless for it. Active REQs are unchanged: empty-block + test-id still enforced, so the
engine never lands one blind. DevSteward's own `done` REQs already carry test ids, so the
dogfood lint stays green; the existing `test_acceptance_without_test_flagged` uses `open`
(active) and is unaffected.

## Fixtures (hermetic, faithful to the observed dialect)

memzy's live repo is **not** in this sanitized public workspace, and mutating it is out of
scope (Decision 6). So `tests/fixtures/memzy/` holds a small **representative** corpus that
reproduces every row of the REQ's gap table, internally consistent (deps + supersedes
resolve, index in sync) so the converted output lints clean:

| fixture | exercises |
|---|---|
| a `done` REQ, no `kind`, `## Acceptance criteria` with an embedded `` `test_*` `` | kind injection, `[x]`→`passed`, test-id copy |
| a `done` REQ, checkboxes with **no** test names (manual/guided verification) | best-effort test id stays empty, verdict not downgraded |
| a REQ with `supersedes: []` | `[]`→`null` |
| a REQ with `supersedes: [REQ-NNN]` | list→string |
| a `superseded` REQ carrying an unknown `superseded_by:` key | key dropped, terminal lints clean with no test ids |
| an `open`/`in-progress` REQ | the active branch of the lint relaxation |
| `REQUIREMENTS_INDEX.md` lowercase rows + `*(by REQ-NNN)*` annotations | index rewrite |

If the operator later has memzy's real export, the fixtures are plain data files — drop the
real captures in and re-run. AC8 ("the full captured fixture corpus lints clean") asserts
against this corpus.

## Tests to write (the REQ's acceptance block, verbatim test ids)

`tests/test_convert_reqs.py`:
- `test_injects_kind_preserves_fields` (AC1)
- `test_transcodes_acceptance_verdicts` (AC2) — parse the result with the real
  `profiles.req.reqfile._parse_acceptance` to prove it is parseable.
- `test_test_id_is_best_effort` (AC3)
- `test_normalizes_supersedes` (AC4)
- `test_index_rows_parseable_and_synced` (AC5) — assert against `lint._INDEX_ROW_RE` /
  `_index_rows`.
- `test_idempotent_and_preserves_prose` (AC6) — convert twice, second run byte-identical;
  diff prose sections against source.
- `test_memzy_fixture_corpus_lints_clean` (AC8) — `convert_corpus` then `lint()` == [].

`tests/test_lint.py`:
- `test_test_id_required_only_for_active` (AC7) — a terminal REQ with test-less criteria
  lints clean; an active REQ with a test-less criterion still fails.

## Out of scope (unchanged from REQ-010)

Legacy **prose** format → [[REQ-017]]; memzy scenarios / ROADMAP; mutating memzy's live
repo; a per-criterion `verified:` method field (Decision 5).
