---
id: REQ-NNN
title: One-line imperative title
status: draft            # draft | open | in-progress | blocked | done | dropped | superseded
kind: feature            # feature | fix | chore | refactor | spec | design | docs
added: YYYY-MM-DD
completed: null
verified_by: null
depends_on: []           # [REQ-001, ...]
concept_refs: []
scenario_refs: []        # [SCN-001, ...]
supersedes: null
tags: []
---

## Context

Why this exists. The problem, who hits it, what's wrong today. Rich prose — this is the
reasoning density that makes a REQ worth reading a year later. Keep it honest about
trade-offs.

## Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | …        | …         |

## Requirement

What must be true when this is done. Concrete, testable behaviour — not implementation
notes. Sub-sections as needed.

```yaml acceptance
- id: AC1
  text: A human-readable statement of one acceptance criterion.
  test: "pytest tests/test_thing.py::test_specific_behaviour"
  status: pending        # pending | pass | fail  (engine-owned — do not hand-edit)
```

## Notes

Anything else: future extensions explicitly out of scope, risks, links.
