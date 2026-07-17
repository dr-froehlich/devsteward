# Plan — REQ-082: `steward cache`, session cache warmth from a second shell

Covers **REQ-082**. Regression-only (Decision 7): no validate phase, no lab, no evidence.

## Shape

A read-only operator verb, ledger-free by construction: it never calls `_load_or_die()` /
`build_executor()`, so it works in any directory — including a non-steward one — and cannot
touch `.devsteward/`. The whole computation is `stat`, arithmetic, and a comparison.

Layout follows the house split (`lint.py` / `lifecycle.py` pattern): the logic lives in a new
top-level module, the click command in `cli.py` renders it and maps the verdict to an exit code.

## `devsteward/cache.py` (new)

| Name | Shape | Notes |
|---|---|---|
| `DEFAULT_TTL_MINUTES = 60` | int | Decision 2 — a threshold the operator owns, never probed. |
| `PROJECTS_DIR_ENV = "CLAUDE_PROJECTS_DIR"` | str | Decision 5 — the seam the suite points at a temp tree. |
| `INVALIDATION_CAVEAT` | str | Decision 3 — printed under both verdicts. |
| `projects_dir()` | `-> Path` | `$CLAUDE_PROJECTS_DIR` (expanded), else `~/.claude/projects`. |
| `project_root(cwd=None)` | `-> Path` | `git rev-parse --show-toplevel`, else resolved cwd (Decision 4). Any git failure (non-repo, no git binary) falls back — never raises. |
| `project_slug(root)` | `-> str` | The absolute path with `/` → `-`; verified against the real tree (`/home/peter/projects/devsteward` → `-home-peter-projects-devsteward`). |
| `newest_transcript(session_dir)` | `-> Path \| None` | `glob("*.jsonl")` — **non-recursive** (the project dir also holds a `memory/` subdir), files only, newest `st_mtime` wins (Decision 1). |
| `probe(ttl_minutes, cwd=None)` | `-> CacheReport` | Composes the above; the one entry point the CLI calls. |

`CacheReport` (frozen dataclass): `session_dir`, `transcript | None`, `age_minutes | None`,
`ttl_minutes`; properties `found`, `session_id`, `warm` (`found and age < ttl` — strictly under,
so exactly-at-TTL is cold), `exit_code` (0 warm / 1 cold / 2 not found, Decision 6).

Age is `time.time() - st_mtime`, kept as a float for the comparison and rendered rounded — the
verdict never rides on the display rounding.

## `devsteward/cli.py`

`@main.command() cache`, one `--ttl MINUTES` option (`default=DEFAULT_TTL_MINUTES`,
`show_default=True`), `@click.pass_context` for `ctx.exit(code)`.

- found → one line `<session-id>  last write <N>m ago  WARM|cold (ttl <T>m)` on stdout, then
  the caveat line; `ctx.exit(0|1)`.
- not found → a yellow message on **stderr** naming `report.session_dir` verbatim, `ctx.exit(2)`.

Exit 2 must not come from `click.ClickException` (that exits **1** — which means *cold* here),
hence the explicit `ctx.exit`. `--help` is the doc surface: STEWARD.md stays the *workflow*
contract and gains nothing from an operator hint verb (prefer subtraction).

## `tests/test_cache_verb.py` (new) — the three ACs

Shared local helpers: `_fake_projects(tmp_path)` builds a projects tree; `_age(path, minutes)`
sets a known mtime via `os.utime`; `_snapshot(dir)` maps relpath → `(bytes, st_mtime_ns)`.
Every test points `CLAUDE_PROJECTS_DIR` at the temp tree (monkeypatch) — no real `~/.claude`
is read, so a clean checkout is green (REQ-064 screen).

- `-k slug_discovery` — literal encoding assertion (`/home/x/p` → `-home-x-p`); git toplevel
  resolved from a **subdirectory**; cwd fallback outside a repo; newest `.jsonl` wins while a
  neighbouring project's dir, a newer `.md`/`.txt`, and a `memory/` subdir are ignored.
- `-k verdict_ttl` — 10-minute transcript is `WARM` by default, `cold` under `--ttl 5`; a
  transcript aged exactly at the threshold is cold; the caveat appears in both verdicts; the
  reported age matches the set mtime.
- `-k exit_readonly` — exit 0 / 1 / 2; the exit-2 message names the searched directory; a
  before/after snapshot of both the fake projects tree (contents **and** mtimes) and the
  invoking repo (worktree + `.devsteward/`, plus `git status --porcelain`) is unchanged.

## Risks

- **Slug fidelity.** Only `/` → `-` is specified and every real project dir on this host
  matches it. If Claude Code encodes some other character (a dotted path) differently, the verb
  degrades to exit 2 — the not-found message prints the directory it searched, so the wrong slug
  is visible rather than silent (REQ Notes; a wrong verdict is the failure mode that matters).
- **Clock skew** (mtime in the future) reads as warm. Left alone deliberately: guarding it is
  machinery for a case that cannot mislead in the risky direction.
