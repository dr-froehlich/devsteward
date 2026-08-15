# REQ-091 — the spawn names its model, and the commit discloses it

Plan for the fused develop checkpoint of **REQ-091**. Two halves of one defect: the engine
writes a model-shaped claim it has no way to keep true. At the **spawn** boundary the claim is
silence (a model nobody chose, unreported); at the **commit** boundary it is a false
co-authorship trailer. Both are cured by the same move — resolve once, say it out loud, and
make a gap visible instead of plausible.

## Shape of the change

```
devsteward/core/attribution.py     NEW  — trailer construction, no model identifier
devsteward/core/executor.py        — _resolve_spawn(), announce, _message(), _TRAILER dies
devsteward/profiles/req/validate.py— the validate spawn goes through _resolve_spawn
devsteward/config.py               — attribution_trailer property
devsteward/build.py                — wire announce + attribution into the Executor
devsteward/templates/CLAUDE.md.tmpl        — house-conventions bullet
devsteward/templates/.devsteward/config.yaml.tmpl — attribution_trailer key
devsteward/templates/.claude/skills/{advance,intake,bootstrap,onboard}/SKILL.md
CLAUDE.md                          — this repo's own copy of the bullet
devsteward/handbook/_04-skills.qmd — doctrine text
tests/test_req091_model_surfacing.py  NEW  — AC1–AC4
tests/test_req091_assisted_by.py      NEW  — AC6–AC10
tests/test_coauthor_trailer.py        DELETED — invariants re-homed (see below)
```

## 1. The spawn surface (AC1–AC3)

Four call sites resolve `(model, effort)` today, each with a bare
`ex._claude_for(kind)` and no output: `Executor.run_step` (`develop`),
`Executor._repair_loop` (`repair`), `Executor.bring_up_guided_session` (`validate`,
interactive foreground), and `profiles/req/validate.py::_run_session` (`validate`, headless).
All four move onto one method:

```python
def _resolve_spawn(self, kind, *, step=None, unattended=True) -> tuple[str | None, str | None, str | None]
```

returning `(model, effort, refusal)`. It:

- resolves through the existing `_claude_for` (no second resolution path — Decision 10);
- **records** `self._spawn_model = model`, which the trailer reads later (§2);
- **announces** on the progress channel and appends a `spawn_model` ledger event carrying
  `kind`, `model`, `effort`;
- when the model is `None`: `unattended=True` → returns a refusal string and spawns nothing;
  `unattended=False` → announces the warning and returns `(None, effort, None)` so the session
  spawns with no `--model` flag, preserving REQ-090's contract for the interactive case.

The refusal/warning text names `claude.model`, `claude.steps.<kind>.model` and
`.devsteward/config.yaml` — **keys, never a value**. It lives in `attribution.py`'s sibling
constants in `executor.py` so the no-model-identifier scan (AC4) covers it.

`Executor` gains an `announce: Callable[[str], None] | None` (the same
`_stderr_announcer` sink `build_accounts` already receives — one visibility channel, not a
new one) and `_announce()` that no-ops when unset.

A CLI `--model` override needs no special case: `build_executor` already folds it into the
`step_claude["develop"]` tuple, so it arrives as *configured* and draws no warning (AC3).

Refusal at the call sites returns `StepResult(step, RunOutcome.REFUSED, notice)` — the outcome
already exists and already means "the engine declined to act", so no new terminal state.

## 2. The trailer (AC6–AC8)

New `devsteward/core/attribution.py`, ~40 lines, no model identifier anywhere in it:

```python
TRAILER_KEY = "Assisted-by"
AGENT       = "Claude"
UNKNOWN     = "unknown"
IDENTITY_ENV = "DEVSTEWARD_ASSISTED_BY"

def identity(spawn_model=None, env=None) -> str      # "Claude:<version>" | "Claude:unknown"
def trailer(spawn_model=None, env=None) -> str       # "Assisted-by: Claude:<version>"
def sign(message, *, spawn_model=None, enabled=True, env=None) -> str
```

Precedence in `identity()`:

1. `spawn_model` (the engine resolved it itself — accurate by construction);
2. `os.environ[DEVSTEWARD_ASSISTED_BY]`, normalized: stripped, and prefixed with `Claude:`
   when it carries no `<agent>:` part, so a session may export either
   `claude-opus-5` or `Claude:claude-opus-5`;
3. `Claude:unknown`.

A value carrying `@`, `<`, `>`, or a newline is **rejected back to `unknown`** rather than
sanitized — an address must never enter this trailer, and a malformed identity is exactly the
case `unknown` exists for. Never a bare `Claude` with the version dropped (Decision 11).

`sign()` with `enabled=False` returns the message untouched — no trailer of any kind (AC8).

`executor.py`'s `_TRAILER` constant is deleted; `_commit` and `_commit_ledger_close` build
their messages through `sign(..., spawn_model=self._spawn_model, enabled=self.attribution)`.
`self._spawn_model` is `None` in an interactive `steward checkpoint` (nothing was spawned),
which is precisely when the env var / `unknown` path applies.

`Config.attribution_trailer` reads a **top-level** `attribution_trailer` key, default `True`
(a falsy or `null` value disables — the same convention `verify.full_suite: null` already
uses). `build_executor` passes it as `attribution=`.

## 3. Doctrine and templates (AC10)

The house-conventions bullet in `devsteward/templates/CLAUDE.md.tmpl` and this repo's own
`CLAUDE.md` is rewritten to mandate `Assisted-by: Claude:<model-id>`, state that the engine
stamps the model it resolved (or `Claude:unknown`), keep the human as sole `Author:`, and add
the `Signed-off-by:` prohibition (Decision 14). The four stamped skills (`advance`, `intake`,
`bootstrap`, `onboard`) and `handbook/_04-skills.qmd` say "co-author trailer" in passing —
each becomes "attribution trailer". **The skills are hardlinked** to the repo's own
`.claude/skills/` copies (one inode), so each is edited exactly once.

No consumer `CLAUDE.md` is touched (Decision 13); the migration note lives in REQ-091's Notes.

## 4. Test re-homing

`tests/test_coauthor_trailer.py` (REQ-090's four ACs) is **deleted**, not left to rot:

| REQ-090 test | Fate |
|---|---|
| `test_no_model_or_email_in_any_coauthor_trailer` | → AC9, `test_no_coauthor_trailer_survives_in_live_text` (strictly stronger: forbids the *key*, not just a model inside it) |
| `test_engine_commits_carry_generic_trailer` | **Superseded** by AC6 — it asserts the exact string REQ-091 retires |
| `test_engine_source_names_no_model` | → AC4, `test_no_model_identifier_in_engine_code` |
| `test_stamped_config_pins_model_and_reaches_spawn` | → AC4 (same test, config half) |

Its `MODEL_TOKEN` regex, `_scannable_files()` walker (deliberately **not** `git ls-files` —
REQ-063's capture check re-runs each acceptance test from a bare extract that is not a git
repo) and `PRUNE_DIRS` move into `tests/test_req091_assisted_by.py` unchanged; AC4 imports
them from there. A one-line supersession note goes into REQ-090's Notes.

The exclusion list (`QUOTES_THE_DEFECT`) grows to cover the historical records that quote the
retired form on purpose: REQ-090's REQ + plan, REQ-091's REQ + this plan, the index row naming
REQ-090's title, the old plans `0001`/`0005`/`0006`/`0038`, REQ-019/020/024/062, and the test
files themselves. Explicit paths, never a wildcard over `docs/` (AC9).

## 5. The consumer config migration (AC5)

Unchanged from intake: twelve repos, the identical `claude:` block, `.devsteward/config.yaml`
committed **alone** on each repo's integration branch, **no push**, mid-flight repos skipped
and reported by name. Performed in this session (mechanical, fixable in place); the results
land in REQ-091's Notes.

## Order of work

1. `attribution.py` + config property + executor rewiring + build wiring.
2. Templates, CLAUDE.md, skills, handbook.
3. Tests (both files), delete the old one.
4. Green: named ACs + `python -m pytest` + `steward lint`.
5. The twelve-repo config migration, reported in Notes.
6. `steward checkpoint REQ-091 develop` — the develop gate defers the land (AC5 is `manual`,
   so a System-Test phase exists).
