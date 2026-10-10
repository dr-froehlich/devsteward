# REQ-100 — A backlog item survives what the owner types

Plan for `REQ-100:develop`. Requirement: `docs/requirements/REQ-100.md` (9 decisions,
4 regression ACs, no concept phase, no System-Test phase).

## The shape of the change

All four defects live in one file, `devsteward/profiles/req/backlog.py`, at the boundary
between a typed value and the markdown file. Each one comes from writer and reader not being
an exact inverse pair:

| Defect | Writer today | Reader today | Fix |
|---|---|---|---|
| line boundaries | passed through | splits on every `str.splitlines` boundary | writer folds them (Decision 1) |
| `\|` | escaped to `\\|` | never unescaped | reader unescapes (Decision 2) |
| `<!--` in a row/bullet | passed through | opens a comment anywhere mid-line | reader opens a comment only at line start (Decision 3) |
| a write that cannot read back | written anyway (`add` never checks; `edit` checks *after* writing) | fails on next read | check before write (Decision 4) |

## Data shapes and functions

- `one_line(value) -> str` (new, public): replaces each run of whitespace containing a line
  boundary with one space, then strips. The boundary class is exactly what `str.splitlines()`
  splits on: `\n \r \x0b \x0c \x1c \x1d \x1e \x85    `. This is "the value as the
  file stores it". The CLI echo and the dashboard flash show it, so the owner sees the fold.
- `_cell(value)`: `one_line(value)` and then `|` → `\|`. This is the single cell encoder, used
  by `append_item` and by `edit`'s row rewrite.
- `parse()`: the need cell is unescaped (`\|` → `|`), which makes it exactly the inverse of
  `_cell`. The writer puts one backslash before every `|`; the reader takes away exactly that
  one, so a typed `\|` survives as `\|` (it is written as `\\|`).
- `set_criteria()`: each bullet is `- {one_line(b)}`.
- `_live_lines()`: a comment block opens only when the stripped line **starts with** `<!--`
  (CommonMark's HTML-block start) and closes on the first line containing `-->`. The writer
  always starts a row with `|` and a bullet with `- `, so user content can never open a
  comment, and the stamped template's `<!-- Example:` block is still skipped.
  Corpus check at plan time: all ten consumer backlogs and the DriveSteward fixture use only
  line-start comment blocks. The trade-off: a hand-written row followed by an inline
  `<!-- … -->` would now fail to parse loudly, where before it was trimmed. No corpus has
  that shape.
- `_read_back(text, item, criteria, backlog_file)` (new, private): parses `text` and refuses
  with `BacklogError` ("refused to write …; the file is unchanged") if the parse fails or the
  item's need, origin or (when given) criteria differ from what will be stored. `add` and `edit`
  call it **before** `path.write_text`. `edit`'s old after-the-write `parse(text)` is removed.

## Surfaces (same commit, REQ-094)

- `devsteward/cli.py`: `backlog-add` echoes `bl.one_line(need)`.
- `devsteward/dashboard/app.py`: the add flash shows `bl.one_line(need)`.
- `devsteward/templates/STEWARD.md`:
  - `backlog-add` and `backlog-edit` rows: line breaks in a need or criterion fold to one space.
  - "The backlog": Decision 5's rule replaces "a REQ is *translated from*" and "the intake
    probably starts from an item".
- `.claude/skills/intake/SKILL.md` (inode-shared with its template): §1 bullet and §2d step 1
  carry the rule.
- `devsteward/handbook/_01-format.qmd`: the §backlog intro ("which a REQ is translated from at
  intake") carries the rule, and the verb table notes the fold.

## Tests — `tests/test_req100_backlog_round_trip.py`

The fixture is a real stamped project under a temp root: ledger, config, a requirements dir
with one done REQ and its index row, a backlog seeded with an item before and after the
target, an acceptance section, the template's commented example, and `git init`. The
dashboard runs through `create_app(...).test_client()` and the CLI through `CliRunner` with
the project as cwd, the same entrypoints `test_dashboard.py` uses.

- **AC1** `test_multiline_need_and_criterion_fold_to_one_line_via_dashboard_and_cli`:
  dashboard add with CRLF and a blank line, dashboard edit with LF, `backlog-add` once per
  remaining boundary character, and `backlog-edit --criterion` with an embedded break. After
  each, the file has one row per item and each bullet is on one line. The project page renders
  with no backlog error, `steward lint` exits 0, and need and criterion read back folded.
- **AC2** `test_pipe_in_need_round_trips_without_drift`: add `a | b`, then three rewrites
  alternating dashboard edit (need and origin) and `backlog-edit --origin`. The need reads
  back as `a | b` every time, and the page and the edit textarea show `a | b` with no `\|`.
  Also checks that a typed `\|` survives exactly.
- **AC3** `test_comment_markers_in_need_and_criterion_round_trip`: needs with `<!--`, `-->`
  and `<!-- x -->`, and criteria with the same, through add and edit. Each reads back exactly,
  the items and criteria after them are all still parsed, and the commented example's
  `rapid-verdict` block is still not read.
- **AC4** `test_write_that_would_not_read_back_is_refused_and_the_file_untouched`:
  `_cell` is monkeypatched to skip the fold. Add and edit through the dashboard and the CLI
  must refuse: `BacklogError` is raised, the file is byte-identical, the CLI exits non-zero
  with the message, and the dashboard flashes an error with no success.

Existing suites (`test_backlog.py`, `test_dashboard.py`, `test_req093_doctrine_surfaces.py`)
must stay green. The last one pins doctrine wording, so the manual edits are checked against
it.
