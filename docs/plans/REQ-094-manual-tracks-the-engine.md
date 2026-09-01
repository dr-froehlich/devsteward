# Plan — REQ-094: the shipped manual tracks the engine

## Approach

Three deliverables, in dependency order: a **command-reference table** in the manual (the
structure that makes coverage checkable at all), a **derived guard** over it, and a **House
convention** in DevSteward's own `CLAUDE.md` for the residual class no guard can see.

Build order is test-first for the guard: write the coverage check, watch it go red on today's
manual (29 verbs missing, since no reference section exists), then write the section and watch it
go green. That sequence is the disconfirmability proof AC2 formalizes.

## Correction to the REQ text (Decision 11)

A first pass claimed the hand-enumerated allowlist in `test_docs_and_skills_use_current_verbs`
*could not* be removed, because it is REQ-057's AC3 test and REQ-057 is `done`. That was wrong,
and the REQ's Decision 11 now records the correction:

* `lint.py` checks only that an AC's `test:` field is **non-empty**, and only on **active** REQs —
  terminal ones are skipped entirely.
* Nothing re-runs a done REQ's named tests. The develop gate runs *this* REQ's named tests plus
  the full suite, where the file is an ordinary member.
* Retiring a landed REQ's acceptance test is the corpus's dominant pattern, not an exception:
  **51 of 292** AC node-ids already do not resolve — whole files removed by the REQ-047 pivot,
  and by REQ-079/REQ-091 superseding REQ-076/REQ-090.

An acceptance criterion records what was accepted *then*; it is not a permanent fixture on the
suite. So the allowlist is deleted as originally specified. Its `steward recover` denylist
survives on independent merit — the derived guard reads neither the handbook nor the bundled
skills — under the honest name `test_no_surface_presents_a_retired_verb`. REQ-057 AC3 stands as
the historical record of what that REQ delivered.

## Files touched

| File | Change |
|---|---|
| `devsteward/templates/STEWARD.md` | new `## Command reference` table (29 verbs, 3 columns); new `## The backlog — user needs above the REQ` section; `gate` / `reland` / `sync` woven into the prose sections that own them |
| `tests/test_steward_manual.py` | four new tests + two parser helpers; existing tests untouched |
| `CLAUDE.md` (repo root, **not** shipped) | new House convention: consumer-visible change ⇒ update `devsteward/templates/STEWARD.md` in the same commit |
| `docs/requirements/REQ-094.md` | Decision 11; Requirement text corrected |

`STEWARD.md` at the repo root is a **symlink** to the template — edit the template path only, and
`git add` that path.

## The command-reference table

Three columns, one row per registered command:

```
| Verb | What it does | Run by / when |
|---|---|---|
| `steward status` | … | The agent — first thing, every session. |
```

First cell is the verb alone in backticks (`` `steward <verb>` ``), no arguments — that is what
makes the row machine-parseable. Arguments live in the "what it does" cell.

The four verbs an in-project agent does not run in the normal cycle carry that fact explicitly
rather than being excluded (REQ Decision 3):

* `new`, `init` — the operator, from outside / at the start of a project.
* `seed-ledger` — the `/onboard` skill, which is `OPERATOR_ONLY` and never stamped into a consumer.
* `cache` — **a second shell**; never from inside a session, because measuring the session's cache
  warmth from inside it warms what it measures.

`sync-skills` gets its own row as the back-compat alias of `sync` (it is a separately registered
command, so the derived check sees it).

## The derived guard

Two helpers in `tests/test_steward_manual.py`:

* `_registered_verbs()` → `set(devsteward.cli.main.commands)`, read at call time so a
  test-time registration is visible (this is what AC2 exploits).
* `_reference_rows()` → parse the manual's `## Command reference` section into
  `{verb: annotation}`: take lines between that heading and the next `## `, keep `|`-rows, drop
  the header and separator, extract `` `steward <verb>` `` from cell 1 and the third cell as the
  annotation.

| AC | Test | Claim |
|---|---|---|
| AC1 | `test_manual_covers_every_registered_verb` | `_registered_verbs() == set(_reference_rows())`, both directions |
| AC2 | `test_verb_coverage_is_derived_not_enumerated` | inject a throwaway click command → AC1's set difference reports exactly it |
| AC3 | `test_command_reference_annotates_who_runs_each_verb` | every annotation non-empty; `cache`'s names the second shell and forbids in-session use |
| AC4 | `test_manual_documents_backlog_take_up` | manual names `backlog_refs` and "advisory to the REQ and blocking to the item" |

**Reverse-check scope (REQ Decision 5):** the "documented verb that no longer exists" direction
reads the *table*, not the whole file — the manual deliberately says "There is no `steward
degrade`", which a whole-file scan would flag.

All four are `check: regression`: hermetic, no service/secret/network, pure filesystem + import.

## Out of scope (from the REQ)

Consumer sync sweep; any `docs/BACKLOG.md` sync machinery; a schema-coverage guard for frontmatter
fields; documenting CLI flags (verb granularity only — `--help` is the flag reference and cannot
drift).
