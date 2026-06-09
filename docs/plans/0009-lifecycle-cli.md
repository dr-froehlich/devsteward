# Plan 0009 — Lifecycle CLI (REQ-026)

Design checkpoint for REQ-026: three operator verbs that shape the queue —
`steward activate`, `steward recover`, and `--only REQ-NNN` on `run`/`advance`.
The eight decisions in REQ-026 are settled; this turns them into concrete data shapes,
interfaces, the files to touch, and the acceptance tests to write at Build.

## Shape of the change

Two pure status mutations (`activate`, `recover`) plus one eligibility filter (`--only`).
Nothing introduces a new `claude` invocation or a new skill — recovery is a ledger
status flip the existing `/advance` skill picks up (D5, out-of-scope note).

| Concern | Layer | Why there |
|---|---|---|
| `activate` (REQ frontmatter + index row) | new `devsteward/lifecycle.py` (CLI-orchestration layer, beside `lint.py`) | bridges the REQ profile (frontmatter) and the index; not core, not parsing |
| `recover` (FAILED → RECOVER ledger steps) | same `lifecycle.py` | a ledger mutation keyed by REQ id; keeps both operator verbs in the file the AC tests import (`test_lifecycle.py`) |
| `RECOVER` step status | `core/model.py` | a `StepStatus`, ledger-layer only — **no** `req.schema.json` change (D4) |
| eligibility incl. `RECOVER`, `--only` filter, recovery signal | `core/executor.py` | the executor owns step selection and command dispatch |
| surgical writers | `profiles/req/reqfile.py` (frontmatter) + new `profiles/req/index.py` (index row) | mirror the existing surgical `update_acceptance_status` |
| recovery awareness | `.claude/skills/advance/SKILL.md` + `templates/.claude/skills/advance/SKILL.md` | the skill must assess prior partial work when resumed |

## 1. `RECOVER` status (D4)

`core/model.py` — add to `StepStatus`:

```python
RECOVER = "recover"
```

That is the whole schema impact. The REQ frontmatter status set is untouched; the REQ
stays `open` while a step recovers (Notes "status-layer clarity").

## 2. Surgical file writers

`activate` must keep the index↔REQ same-commit invariant green (D1), so it edits two
files in lockstep, line-surgically (preserving prose/formatting like
`update_acceptance_status` already does).

**`profiles/req/reqfile.py`** — new:

```python
def set_frontmatter_status(path: Path, new_status: str) -> str:
    """Rewrite the `status:` line inside the `--- ... ---` frontmatter. Returns the old
    status. Edits only that line so surrounding frontmatter/prose is preserved."""
```

Implementation: reuse `_FRONTMATTER_RE` to bound the frontmatter span, regex-replace the
`^status:\s*...$` line within it (handles quoted/unquoted values).

**`profiles/req/index.py`** — new module owning the canonical index-row contract:

```python
INDEX_ROW_RE = re.compile(r"^\|\s*(REQ-\d{3}[a-z]?)\s*\|\s*(.*?)\s*\|\s*([A-Za-z-]+)\s*\|", re.MULTILINE)

def read_statuses(index_path: Path) -> dict[str, str]:   # id -> lowercased status
def set_status(index_path: Path, req_id: str, status: str) -> str:  # writes UPPERCASE cell, returns old
```

The index displays status in UPPERCASE (`DONE`/`OPEN`/`DRAFT`); the writer uppercases.
`lint.py` currently defines its own private `_INDEX_ROW_RE`/`_index_rows` — refactor it to
import `INDEX_ROW_RE`/`read_statuses` from `index.py` so the row contract lives in one
place (small, low-risk dedup; covered by the existing `test_lint.py`).

## 3. `lifecycle.py` (new) — the two verbs

```python
class LifecycleError(Exception): ...   # cli maps to a non-zero ClickException

@dataclass
class ActivateResult:
    req_id: str; old_status: str; new_status: str; changed: bool; message: str

def activate(cfg, req_id: str) -> ActivateResult:
    # unknown id                       -> LifecycleError
    # done | superseded                -> LifecycleError("... supersede instead ...")
    # open | in-progress | blocked     -> no-op: changed=False (no error)
    # draft | dropped                  -> set frontmatter `open` + index `OPEN`; changed=True
    # leaves both files UNCOMMITTED (D3)
```

`done`/`superseded` refusal text points at the supersede path (D2, REQ-001: never weaken a
finished requirement). `dropped → open` is the one terminal that legitimately reverses.

```python
@dataclass
class RecoverResult:
    req_id: str; steps: list[str]   # the step ids flipped FAILED -> RECOVER

def recover(ledger, req_id: str) -> RecoverResult:
    failed = [sid for sid, st in ledger.all_statuses().items()
              if sid.startswith(f"{req_id}:") and st is StepStatus.FAILED]
    if not failed:
        raise LifecycleError(f"{req_id} has no failed step to recover")
    for sid in failed:
        ledger.set_status(sid, StepStatus.RECOVER)
    ledger.save()
    ledger.append_event("step_recover", req=req_id, steps=failed)
    # working tree left as the failed attempt left it (D6) — no git touched
```

## 4. Executor changes (`core/executor.py`)

**Eligibility (D5)** — `RECOVER` joins `PENDING` as a candidate status, and an optional
`only` filter restricts to one REQ:

```python
def eligible_steps(self, only: str | None = None) -> list[Step]:
    ...
    for s in steps:
        if only is not None and s.req != only:
            continue
        if self.ledger.status_of(s.id) not in (StepStatus.PENDING, StepStatus.RECOVER):
            continue
        if all(dep DONE ...):
            eligible.append(s)

def next_eligible(self, only: str | None = None) -> Step | None: ...
```

**Recovery signal in the command (D5, AC4)** — captured *before* `run_step` flips the
status to `RUNNING`:

```python
# top of run_step, before set_status(RUNNING):
recovering = led.status_of(step.id) is StepStatus.RECOVER
command = step.command + (" --recover" if recovering else "")
led.append_event("step_started", step=step.id, command=command, recover=recovering)
...
result = self.runner(command, ...)   # was step.command
```

No other run_step change is needed: a clean run already sets `DONE`; a hard error / red
verify already sets `FAILED` (D5 "a second failure back to FAILED"). The dirty tree from
the prior failure is left in place for the skill to reconcile (D6) — the executor only
commits on success.

**`--only` plumbed through the drivers:**

```python
def advance_once(self, *, only=None, unattended=True, on_event=None): ...   # next_eligible(only)
def run(self, *, only=None, max_steps=None, on_event=None): ...             # next_eligible(only)
```

**Ineligibility diagnosis (D8, AC7)** — when `--only REQ-X` selects nothing, name why:

```python
def only_ineligibility_reason(self, req_id: str) -> str:
    steps = [s for s in self.steps() if s.req == req_id]
    if not steps:
        return f"{req_id} is not active (activate it first, or it does not exist)."
    statuses = [self.ledger.status_of(s.id) for s in steps]
    if all(st is StepStatus.DONE for st in statuses):
        return f"{req_id} is already done — all its steps are complete."
    return f"{req_id} has no eligible step — it is blocked on an unfinished dependency."
```

The branch guard, dependency order, park-and-surface, and REQ-020 branch topology are all
unchanged (D7). On recovery of a `build`/`land` step, `prepare_branch` reuses the REQ's
existing feature branch (Notes "REQ-020 interaction").

## 5. CLI (`cli.py`)

Two new top-level commands and one shared option:

```python
@main.command()
@click.argument("req_id")
def activate(req_id): ...   # calls lifecycle.activate; LifecycleError -> ClickException
                            # echoes "activated REQ-X (draft -> open)" or "REQ-X already active (no-op)"

@main.command()
@click.argument("req_id")
def recover(req_id): ...    # calls lifecycle.recover; no-failed-step -> ClickException (non-zero)
                            # echoes "recovered REQ-X: REQ-X:land -> recover; re-run `steward run`."

# add to BOTH run and advance:
@click.option("--only", default=None, help="Restrict to one REQ's steps (fails if none eligible).")
```

`run`/`advance` thread `only=` into the executor. When `--only` is set and the result is
empty/`None`, raise `click.ClickException(ex.only_ineligibility_reason(only))` (exit 1)
instead of the benign "Nothing eligible" message. `cli_exposes_documented_commands` /
`test_skills.py` expectations: register `activate` and `recover` in the documented set.

## 6. Skill prompt — recovery awareness

`.claude/skills/advance/SKILL.md` (and the shipped `templates/.claude/skills/advance/`
copy) gain a short note in the orient section: *if the step command includes `--recover`,
you are resuming a step that previously failed — its partial edits are already in the
working tree; read and assess them (reconcile or fix) before continuing, rather than
starting clean.* Operational English only; no German strings introduced (Notes).

## Acceptance tests (written at Build)

Reuse `tests/conftest.py` fakes: `FakeRunner` (records each call's `command` — so the
`--recover` signal is assertable), `ListStepSource`, `RecordingCommitter`, the `project`
fixture.

| AC | Test | Sketch |
|----|------|--------|
| AC1 | `test_lifecycle.py::test_activate_draft_to_open` | temp project, draft REQ + `DRAFT` row → `activate` → frontmatter `open` + row `OPEN`; `steward lint` green |
| AC2 | `test_lifecycle.py::test_activate_guards` | `dropped→open` works; `done`/`superseded` raise w/ supersede pointer; unknown id raises; already-open → `changed=False`, no raise |
| AC3 | `test_lifecycle.py::test_recover_flips_failed_step` | ledger w/ FAILED `REQ-X:land` → `recover` flips to RECOVER + `step_recover` event; no failed step → raises (maps to non-zero) |
| AC4 | `test_executor.py::test_recover_status_eligible_and_signalled` | RECOVER step ∈ `eligible_steps()`; FakeRunner call `command` contains `--recover`; clean run → `DONE` |
| AC5 | `test_executor.py::test_run_only_isolates_req` | two eligible REQs; `run(only="REQ-X")` drives only REQ-X's steps, never the other |
| AC6 | `test_executor.py::test_advance_only_targets_named_req` | lower-id REQ also eligible; `advance_once(only="REQ-X")` runs REQ-X's next step |
| AC7 | `test_cli_smoke.py::test_only_not_eligible_errors` | `CliRunner` `run`/`advance --only REQ-X` where X not eligible → exit ≠ 0 + reason string |

## Out of scope (REQ-026 Notes)

No repair skill / extra `claude` invocation; no `deactivate`/`drop` verb; no reopening
`done` via ledger reset (supersede is the path).
