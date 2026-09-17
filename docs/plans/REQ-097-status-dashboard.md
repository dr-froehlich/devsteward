# Plan — REQ-097: the status dashboard

**Concept:** `docs/concepts/REQ-097/concept.md` (frozen 2026-09-17). The prototype is the
build; this plan records the shape it took and what the acceptance tests pin.

## Files

| Path | Role |
|---|---|
| `devsteward/verbs.py` | **new** — one callable per state-changing verb (`activate`, `repeat`, `rework`, `revalidate`, `reland`, `answer_decision`): executor build + `check_invariants` + `transaction`, refusals as `LifecycleError`. The CLI and the dashboard both call these. |
| `devsteward/profiles/req/backlog.py` | + `Bits`/`bits`, `require_item`, `add`, `set_criteria`, `edit`, `record_verdict` — the file operations behind the backlog verbs, shared by both surfaces. `bits(cfg, reqs=…)` takes a parsed corpus. |
| `devsteward/cli.py` | the six verbs above become printers around `verbs`; `backlog-add`/`-list`/verdicts around `backlog.py`; **new** `backlog-edit HANDLE [--need] [--origin] [--criterion …]` and `dashboard [--root DIR] [--port N]` (flask checked with `find_spec`, install hint on absence). |
| `devsteward/profiles/req/source.py`, `devsteward/build.py` | `ReqStepSource(req_dir, reqs=None)`, `build_executor(cfg, reqs=None)`, `_validation_nodeids(cfg, reqs=None)` — an already-parsed corpus may be handed in; CLI paths pass nothing and read from disk as before. |
| `devsteward/dashboard/__init__.py` | the install hint. |
| `devsteward/dashboard/model.py` | pure reads: `resolve_root`, `scan_root`, `project_status`, `_offer`, `git_facts`, `humanize_age`, `attention`, `load_project`, `render_markdown`, `req_body_html`. |
| `devsteward/dashboard/app.py` | `create_app(root, templates_root=, backlog_template=)`: `GET /`, `/p/<name>`, `/p/<name>/req/<id>`; `POST /p/<name>/verb/<verb>`, `/decision/<id>`, `/backlog/add`, `/backlog/<h>/edit`, `/backlog/<h>/verdict`. One write lock. Loopback binding is the verb's. |
| `devsteward/dashboard/templates/*.html` | `base` (inline CSS), `overview`, `project`, `req`. |
| `pyproject.toml` | extra `dashboard = ["flask>=3,<4", "markdown>=3.5"]`; package-data `dashboard/templates/*`. |
| `devsteward/templates/STEWARD.md` | rows for `backlog-edit` and `dashboard` (REQ-094, same commit). |
| `devsteward/handbook/_01-format.qmd` | `backlog-edit` in the verb table; a line on the dashboard as the operator's surface. |
| `tests/test_dashboard.py` | AC1–AC4, AC6–AC10. |
| `tests/test_backlog.py` | AC5's `backlog-edit` half. |

## Data shapes

- `ProjectRef(name, root, stamped)`; `StepView(id, req, phase, status, eligible, note, attended, title, actions, shell)`; `StatusView(profile, cursor, steps, decisions, drift, terminal, drafts)`; `GitFacts(branch, dirty, remote, unpushed, gap, last_commit_ts, head, subject)`; `Attention(project, kind, ref, text, hint)`; `ProjectView(ref, cfg, status, git, reqs, backlog, backlog_file, backlog_error, attention, error)`.
- `backlog.Bits(items, reqs, events, criteria).standings()`.

## Tests (what each pins)

- **AC1** discovery over a temp root; per-project config paths honoured; status model == `steward status` lines.
- **AC2** git facts on throwaway repos (bare remote, unpushed, gap, dirty, no remote) and read-only (refs/index/HEAD byte-identical).
- **AC3** needs-me over the AC1 root.
- **AC4** every step action calls the CLI's function: refusal text equals the CLI's, ledger untouched on refusal, rework flips like `steward rework`; a `claude` shim on PATH sees zero calls; no `run`/`advance`/`validate` route.
- **AC5** `backlog-edit` rewrites one item and preserves the rest byte-for-byte; the page's backlog writes equal the CLI's file + events.
- **AC6** bare deps unchanged, extra names flask; verb refuses with the hint when flask is absent; binds 127.0.0.1.
- **AC7** end to end through the WSGI app: overview, project, REQ page, rework round trip.
- **AC8** the frozen page inventory (concept §1) is present.
- **AC9** the offered actions mirror the CLI's hints and nothing else.
- **AC10** one parse per REQ file per page load.

## Required environment

`flask` and `markdown` importable by the test interpreter (`.venv/bin/pip install flask markdown`)
and injected into the pipx engine (`pipx inject devsteward flask markdown`). Both done 2026-09-17.
