# REQ-089 — the remote-host deployment seam (implementation plan)

**REQ:** `docs/requirements/REQ-089-remote-host-deployment-seam.md`
**Shape:** `develop: fused` (Decision 11), one attended checkpoint. REQ-089 declares a
`manual` AC (AC2), so the develop close is `develop_committed` — the land defers to
`steward validate REQ-089`.

Four workstreams, one seam. Build order is A → D → C → B (doctrine first because it is the
reason the REQ exists; the CLI rename before `gate` so `gate` is authored in the flat world;
the carry last of the engine changes because it is the only one touching two files that must
agree).

---

## A. Doctrine — one rule on the attended axis

The defect is that `/advance` §4 states an absolute with **one enumerated exception**
(`concept: true`), while `/intake` §2b disclaims exactly that reading. Fix = restate the rule
as a **principle keyed on attended**, name the **trigger** (a round-trip through external
infrastructure), name the **mechanism** (plain git commits by the session), and keep
`steward checkpoint` terminal + the batch prohibition absolute.

The removal matters as much as the addition — AC1 asserts the stale wording is **gone**, so an
additive-only edit reds.

### Files (4 surfaces)

| # | File | Edit |
|---|------|------|
| A1 | `devsteward/templates/.claude/skills/advance/SKILL.md` §4 | Replace "The one sanctioned exception: mid-phase commits during an *empirical* `concept: true` phase" with the attended grant: **who** (attended only — `DEVSTEWARD_UNATTENDED` unset), **when** (the proof needs a round-trip through external infrastructure: CI building an image, a remote host, a deploy target), **how** (plain `git` commits by the session — `steward checkpoint` is never a mid-phase verb), **what does not change** (never writes `status:`, never edits the index row, `checkpoint` still the terminal act, batch never commits). |
| A2 | same file, §2 | Generalize the iterate-until-frozen clause **off** `concept: true`: state the pattern (work whose deliverable/proof requires round-trips through the real world iterates; the one-checkpoint frame bounds the *bookkeeping*, not the round-trips) and make the empirical concept phase **one instance** of it. Add the deploy-shaped-proof bullet: if the proof needs a deploy, it belongs **in this session**, fixable in place — not deferred to the fixless System-Test phase (REQ-030). |
| A3 | `devsteward/templates/.claude/skills/intake/SKILL.md` §2b | Name the deploy-shaped case explicitly in the live-proof-in-develop screen; keep the "grant, not a restriction" clause, now re-pointed at the attended rule `/advance` states (agreement, not compensation). |
| A4 | `devsteward/templates/STEWARD.md` | Drop the "(One exception: an *empirical* `concept: true` phase may commit mid-phase…)" parenthetical; state the attended rule in its place. |
| A5 | `devsteward/handbook/_00-method.qmd` rule 4 | Restate on the attended axis: the rule is about **attended** work that needs round-trips; the empirical concept phase is the named instance. |

**Hardlink discipline:** `.claude/skills/<name>/SKILL.md` and
`devsteward/templates/.claude/skills/<name>/SKILL.md` are **one inode**; repo-root
`STEWARD.md` is a **symlink** to `devsteward/templates/STEWARD.md`. Edit the template path
only, then re-`stat` the inodes — if an editor broke the link, restore it with
`ln -f <template> <repo-skill>` before committing.

---

## D. Flat, discoverable CLI (hard rename, Decision 8/9)

`devsteward/cli.py`:

- Delete the variadic `@click.argument("words", nargs=-1, …)` on `validate`. It becomes
  `@main.command() @click.argument("req_id")` — shape A only, unchanged behaviour.
- `_validate_start` / `_validate_record` get real command decorators:
  `@main.command("validate-start")` / `@main.command("validate-record")`, each
  `@click.argument("req_id")`. Bodies unchanged.
- `@main.group() decision` + its two subcommands collapse to
  `@main.command("decision-list")` and `@main.command("decision-answer")`
  (`decision_id`, `answer` arguments). The group disappears.
- No aliases, no deprecation shim (Decision 9).

**Every string that names a two-word form** must move in the same commit (AC6): `cli.py`
docstrings + hint strings, `devsteward/core/executor.py` (the warm-cycle hint),
`devsteward/profiles/req/validate.py` (two hints), `devsteward/templates/STEWARD.md`,
`devsteward/templates/.claude/skills/system-test/SKILL.md`,
`devsteward/templates/CLAUDE.md.tmpl`, `README.md`.

**What "historical records" covers (operator decision, this session).** AC6 enumerates
"landed REQ files and `docs/reports/`" but states the *reason*: append-only history. The
operator's call is to read the reason, so the scan also exempts **`docs/plans/`** — the plan a
landed REQ was built from is per-REQ history exactly like the REQ file and the postmortem, and
rewriting it would falsify the record (`docs/plans/REQ-081-warm-validate-halves.md` describes
the verbs REQ-081 actually shipped). `REQUIREMENTS_INDEX.md` is exempt on the same ground: its
REQ-081 row is lint-locked to that REQ's frontmatter title. Everything else under `docs/` is
instructional and is scanned. *Accepted cost:* a cold session orienting from an old plan can
still read a dead command name.

Existing tests invoking the old spelling migrate in the same commit:
`tests/test_req081_halves.py`, `tests/test_cli_smoke.py`, `tests/test_decision_refound.py`
(and any docstring mention that the AC6 scan does not read).

---

## C. `rework` carries prior sign-offs (Decisions 6/7)

Two halves — the write and the read. Either alone is inert, which is what makes AC4
disconfirmable.

**Write** — `devsteward/lifecycle.py::rework`: after resolving the red validation, do what
`revalidate` already does — `scope, carried = _scope_revalidation(req, ledger.latest_validation(req_id))`
— and put `scope` + `carried` on the `rework` event when `scope is not None`. `ReworkResult`
grows `scope` / `carried` fields (mirroring `RevalidateResult`). Develop still → `RECOVER`;
validate still → `PENDING`. The carry is **unconditional** (Decision 7): every recorded-green
AC carries, with `source_evidence` + `source_event` provenance already written by
`_scope_revalidation`.

**Read** — `devsteward/profiles/req/validate.py::_pending_revalidate`: match
`ev.get("event") in ("revalidate", "rework")` with a `scope`. A `validation` event still
clears the pending scope. Everything downstream (`ctx.reval`, `_ac_flag`, `_carry_forward`,
the `scoped re-run (REQ-075): …` announcement, the provenance on the validation event) is
already built and needs no change. Rename the helper's docstring, not the helper.

Degenerate cases are untouched: no per-AC results / nothing green → `_scope_revalidation`
returns `(None, None)` → the event omits `scope` → full re-run.

`cli.py::rework` prints the carried ACs so the operator sees what is **not** being re-walked
before the walkthrough starts (the Decision 7 mitigation).

---

## B. `steward gate` — read-only verdict preview (Decisions 4/5)

New `@main.command()` in `cli.py`:

```
steward gate [REQ_ID] [PHASE]     # PHASE defaults to develop; no REQ_ID → the cursor step
```

Body:

1. `cfg = _load_or_die()`; `ex = build_executor(cfg)`.
2. Resolve the step exactly as `checkpoint` does (cursor via `ex.live_ledger().cursor_step`
   when no id; `ex.step_by_id`; the same not-a-derivable-step message).
3. `ok, detail = ex.verifier.verify(step)` — **the same verifier object the develop gate
   uses**, built by `build_verifier(cfg)`. That is how requirement 6's three properties
   (resolved interpreter, `check:`-routed selection, `verify.env_file` carry) hold *by
   construction* rather than by a re-implementation that can drift: the selection is
   `step.verify` from the same `ReqStepSource`, the interpreter is `resolve_test_interpreter`
   inside `ReqVerifier`, and the tests run in the repo root where the declared env-file
   already lives.
4. Print the verdict + `detail` (which already names each failing test), then the standing
   disclaimer (AC3/requirement 8): this is the **verify** gate, not REQ-063's capture check —
   a green `gate` does not promise `steward checkpoint` will land.
5. `raise SystemExit(1)` on red.

**Read-only contract (AC3).** What `gate` must *not* do, and why each is reachable:

- no `check_invariants(ex)` — a precondition guard is for mutations; `gate` has none, and
  refusing on a non-`dev` HEAD would make the preview unusable exactly when it helps.
- no `transaction(...)` — nothing to roll back.
- no `ledger.save()` / `append_event` — `Ledger.__init__` only *reads* `state.yaml`
  (verified: it constructs, reads if the file exists, and writes nothing).
- no evidence dir — that is the validate phase's mint (REQ-088).
- **no capture-gate extract** (Decision 5): `_stage_and_write_tree` → `git add -A` is an
  index mutation, which would break byte-identity of the index and is precisely the staging
  path REQ-077/079/088 all found defects in.

The one thing the test must tolerate: pytest's own gitignored droppings
(`.pytest_cache/`, `__pycache__/`). They do not appear in `git status --porcelain` and are
not part of the asserted set.

---

## Tests — `tests/test_req089_deployment_seam.py`

All five `check: regression`, hermetic, no network, no lab.

| test | asserts |
|------|---------|
| `test_doctrine_surfaces_state_the_attended_rule` (AC1) | Per file: the new wording is present **and** the stale absolute is gone. Reads the four **template** paths (what `steward new`/`sync` stamp). |
| `test_gate_previews_verdict_and_mutates_nothing` (AC3) | Temp project, REQ naming a passing test → exit 0 + green; flip the test red → non-zero + the failing test named. In **both** runs: SHA-256 of `state.yaml`, `events.jsonl`, the REQ file + `git rev-parse HEAD` + `git status --porcelain` + `.git/index` mtime identical before/after; no evidence dir minted. Output names the verify gate. |
| `test_rework_carries_green_acs_forward` (AC4) | Red validation with a green `artifact` AC, a green `manual` AC (recorded sign-off) and a red `artifact` AC → `rework` sets develop `RECOVER` **and** writes `scope == [red AC]` + `carried` naming both greens with `source_evidence` / `source_event` (+ the manual signoff). `_pending_revalidate` returns that rework event. The resumed validation re-opens only the red AC, the carried artifact lands as a **real file** in the fresh evidence dir, the carried manual replays with **no** new sign-off call, and the validation event records the carry provenance. Disconfirmability is covered by two in-test monkeypatched reversions (write-only and read-only). |
| `test_cli_is_flat_and_discoverable` (AC5) | Walk `main.commands`: the four flat names exist with declared params; **no** command has a `nargs=-1` positional; `steward validate REQ-001` still resolves; `["validate","start","REQ-001"]` and `["decision","list"]` no longer resolve; every command in the tree appears in `steward --help`. |
| `test_no_surface_names_a_two_word_command` (AC6) | Scan `devsteward/templates/.claude/skills/`, `devsteward/templates/STEWARD.md`, `devsteward/handbook/`, `docs/` for the four two-word forms; skip `docs/requirements/REQ-*.md` and `docs/reports/` (append-only history). |

AC2 is `check: manual` — the human oracle. It routes to `REQ-089:validate`, so this develop
close commits the work (`develop_committed`) and the land fires after
`steward validate REQ-089`.

## Out of scope

Consumer-owned runbooks (the stated blast radius of Decision 9), the `check:` taxonomy,
REQ-030's System-Test design, any schema or lint change.
