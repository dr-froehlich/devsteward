# REQ-090 — model identifiers leave the code (implementation plan)

**REQ:** `docs/requirements/REQ-090.md`
**Shape:** `develop: fused`, one attended checkpoint. All four ACs are `check: regression`,
so the develop gate lands the REQ directly — no System-Test phase.

**The rule, in the owner's words:** *the specific model lives in config.yaml and not in any
python module, full stop. That is why there is a config.yaml. It is stamped into the
consumer project, and it needs a default model there, visible.*

The asymmetry that motivates it: today a project can override the model **per step kind**
via `claude.steps.<kind>`, but the **global** default is invisible — hardcoded in
`devsteward/config.py` and merely a commented example in the stamped config. Being able to
override an invisible default while being unable to set the visible one is backwards. The
fix makes every model identifier live in one visible, consumer-owned file.

---

## Correction to the intake diagnosis

REQ-090's Context says `DEFAULT_MODEL` (claude.py) is the spawn pin and is "largely
vestigial — an unset config already omits the flag". **That is wrong**, found while
building. The real pins are in `devsteward/config.py`:

| Site | Value | Effect |
|---|---|---|
| `Config.claude` default dict (l.61) | `claude-opus-4-8` | flat default when no config file key |
| `Config.model` property (l.93) | `.get("model", "claude-opus-4-8")` | **fallback whenever the key is absent** |
| `STEP_CLAUDE_DEFAULTS` (l.27-31) | `repair: claude-sonnet-4-6`, `validate: claude-sonnet-5` | built-in per-step pins |
| `claude.py` `DEFAULT_MODEL` (l.66) | `claude-opus-4-8` | only a kwarg default; executor always passes `model=` |

`Config.step_claude()` ends with `merged.get("model") or self.model`, so it **always**
resolves to a concrete string and `--model` is **always** passed. Consumers' headless runs
have genuinely been driven by Opus 4.8 / Sonnet 4.6 — the defect is materially bigger than
the trailer it was reported as. The REQ text is corrected as part of this build (prose
only; `status:` and the index row stay engine-owned).

---

## A. The trailer — `devsteward/core/executor.py`

`_TRAILER` becomes `"Co-Authored-By: Claude"`. No model, no email (Decisions 1-2). Both
consumers (`_commit` l.951, `_commit_ledger_close` l.996) are unchanged — they interpolate
the constant.

## B. Model identifiers out of Python

| # | File | Edit |
|---|------|------|
| B1 | `core/claude.py` | Delete `DEFAULT_MODEL`; `run_claude(model=None)`. The existing falsy-omits-the-flag branch already handles it. Rewrite the comment to point at config. `DEFAULT_EFFORT` **stays** — an effort level is not a model and does not age. |
| B2 | `config.py` | Delete `STEP_CLAUDE_DEFAULTS`' values (the dict goes; `step_claude` starts from `{}`). Drop `"model"` from the `Config.claude` default dict. `Config.model` returns `str \| None` — the config value or `None`, never a literal. |
| B3 | `cli.py` l.607, l.1043 | `--model` help text stops advertising a model id; it points at `claude.model` in the config. |
| B4 | `handbook/_02-engine.qmd`, `_03-workflow.qmd` | The "defaults Opus-high / repair Sonnet" statements become **false** once the values live in config. Restate as "the model configured for the step kind (`claude.steps.<kind>`, falling back to `claude.model`)" without naming any model. |

`Config.model` returning `None` is safe by construction: `step_claude` returns
`merged.get("model") or self.model`, `build.py` passes the pair straight into
`Executor(step_claude=…)`, and `run_claude` omits `--model` on a falsy value. A project
that configures nothing therefore spawns with **claude's own default** — never-stale
behaviour, and the honest meaning of "unset".

## C. The stamped config carries them, visibly

`devsteward/templates/.devsteward/config.yaml.tmpl` ships an **active** block:

```yaml
claude:
  permission_mode: dangerously-skip
  model: claude-opus-5      # the global default for every step kind
  effort: high
  steps:                    # per-step overrides — cheaper models where Opus buys nothing
    repair:   {model: claude-sonnet-5}
    validate: {model: claude-sonnet-5}
```

Both levels visible in the one file the consumer owns and edits — that is the asymmetry
fixed. The per-step policy (REQ-029 D4 / REQ-030 D2: a cold repair restart and the System
Tester's procedure-following do not need the top model) survives as *configuration* rather
than as a Python constant. DevSteward's own `.devsteward/config.yaml` gets the same block,
since it dogfoods the stamp.

## D. The convention text

`devsteward/templates/CLAUDE.md.tmpl` l.42 and the repo's own `CLAUDE.md` l.51 state the
rule in placeholder form, naming no model and carrying no address:

```
- **Co-author trailer** on commits names the model actually driving the session:
  `Co-Authored-By: <modelname>` — never a hardcoded model string, and no email address.
  Engine-made commits (`steward checkpoint`) carry a plain `Co-Authored-By: Claude`,
  because the engine cannot know what model is driving the session.
```

## E. Tests

New `tests/test_coauthor_trailer.py` with the four ACs. Two existing tests assert the
built-in defaults this REQ deletes and must be rewritten to assert the **seam** instead of
the values:

- `tests/test_phase_model.py::test_per_step_model_config` (l.289-314) — asserts
  `step_claude("develop") == ("claude-opus-4-8", "high")` and `repair → claude-sonnet-4-6`.
  Rewrite: an empty config resolves to `(None, "high")` (no built-in model); a configured
  flat model reaches every kind; a per-step override changes only its kind. The end-to-end
  half (c) keeps model ids — they are **fixture inputs**, which is legitimate: AC3 scopes
  the ban to `devsteward/`, not `tests/`.
- `tests/test_claude_stream.py::test_new_session_and_model_effort` (l.59-99) — asserts
  `--model claude-opus-4-8` as `run_claude`'s default. Rewrite: `--model` is **absent** by
  default, `--effort high` still present. The sibling
  `test_model_effort_omitted_when_falsy` already covers the falsy path and is untouched.

### AC design notes

- **AC1** scans live files for `Co-Authored-By:` lines; a model token or an `@` fails.
  `.devsteward/evidence/**` is excluded — it holds hash-recorded frozen artifacts
  (`REQ-057/*/CLAUDE.stamped.md` contains the old trailer *by design*), and rewriting them
  would falsify recorded evidence. `.git/**`, `docs/requirements/REQ-090.md` and this plan
  are excluded too: they *quote* the defect as prose, which is the point of a bug REQ.
- **AC2** asserts the observable the bug report measured — a real commit body in a temp git
  repo, both the code commit and the ledger commit.
- **AC3** scans `devsteward/**` for model tokens with exactly one exempt path, asserted by
  name so widening the exemption requires editing the test.
- **AC4** stamps a project and asserts the config's active `model:` reaches `--model`, and
  that a config without the key spawns with no `--model` at all.

## Build order

A → B → C → D → E. The trailer first (it is the reported defect and touches one line), the
Python subtraction next, the config template before the docs that describe it, tests last
so they are written against the finished shape.
