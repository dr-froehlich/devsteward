# 01 · The hybrid machine-readable REQ format

A REQ file is Markdown with three layers, each tuned for a different reader.

## Layer 1 — YAML frontmatter (the machine contract)

```yaml
id: REQ-007
title: Group scope — shared access for co-deployed courses
status: open            # draft | open | in-progress | blocked | done | dropped | superseded
kind: feature           # feature | fix | chore | refactor | spec | design | docs
added: 2026-05-26
completed: null
verified_by: null
depends_on: [REQ-005, REQ-006]
concept_refs: []
scenario_refs: [SCN-002]
supersedes: null
tags: [access]
```

Validated against `req.schema.json` by `steward lint`. The `id` must match the filename
(`REQ-007.md`). This is the layer the engine reads to build the dependency graph.

## Layer 2 — the acceptance block (the verification contract)

A single fenced block the verifier can run and track:

````
```yaml acceptance
- id: AC1
  text: A token scoped to the group authorizes every child course path.
  test: "pytest tests/test_scope.py::test_group_token_authorizes_children"
  status: pending        # pending | pass | fail  (engine-owned)
```
````

Every criterion has an `id`, a human `text`, and a runnable `test`. The `status` field is
**engine-owned**: the verifier writes `pass`/`fail` back after running the test. Do not
hand-edit it. `steward lint` fails if any active/done REQ has a criterion without a test.

## Layer 3 — prose (the reasoning, untouched)

`## Context`, a `## Decisions` table, the `## Requirement` body, and `## Notes`. This is
where the density that makes a REQ valuable a year later lives. The machine never parses
it; humans always do. Keep it honest about trade-offs and explicit about what is *not* in
scope.

## Why hybrid

Strict schema + parseable blocks give tools exactly what they need; rich prose stays
rich. The schema and linter make the format a **contract, not a convention** — you can't
half-follow it and stay green.

## What is *not* in the REQ

Checkpoint and cursor state. **REQ = spec, ledger = cursor.** The ledger lives in
`.devsteward/`. The only engine-written field inside a REQ is acceptance `status:`.
