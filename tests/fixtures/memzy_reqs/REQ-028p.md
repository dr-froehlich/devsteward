---
id: REQ-028p
title: Persistent cart — a teacher's in-progress selection survives a logout
status: done
added: 2026-06-04
completed: 2026-06-06
verified_by: pytest
depends_on: [REQ-001, REQ-003]
concept_refs: []
scenario_refs: []
supersedes: []
tags: [cart, persistence, console]
---

## Context

`REQ-028` (the cart umbrella) split after the fact into two lettered sub-parts so neither
half had to renumber everything downstream: `REQ-028p` (this one — the cart *persists*) and
`REQ-028s` (cart *sharing*, still on the roadmap). The letter is a sub-part marker on the
existing number, not a new requirement id space.

## Requirement

A teacher's in-progress vocabulary selection is stored server-side keyed to their account,
so logging out and back in restores the cart rather than discarding it.

## Acceptance criteria

- [x] A cart with three entries survives a logout/login round-trip — a test
      `test_cart_persists_across_session` asserts the entries are restored.
- [x] The cart is scoped to the owning teacher; another account never sees it.

## Notes

- `REQ-028s` (sharing) will build on this persisted shape; it is out of scope here.
</content>
</invoke>
