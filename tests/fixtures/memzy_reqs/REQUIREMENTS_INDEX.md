# Requirements Index — Memzy

A multi-student spaced-repetition Latin vocabulary trainer (Django + py-fsrs). See
[REQ-001](REQ-001.md) for the north-star architecture.

| ID | Title | Status | File | Depends on |
|----|-------|--------|------|------------|
| REQ-001 | System architecture (north star) — Django + py-fsrs vocabulary trainer | draft | [REQ-001](REQ-001.md) | – |
| REQ-002 | Project bootstrap — Django + Postgres + Docker shell | done | [REQ-002](REQ-002.md) | REQ-001 |
| REQ-003 | Core data model & migrations | done | [REQ-003](REQ-003.md) | REQ-001, REQ-002 |
| REQ-018 | Per-Lektion drag ordering in the console — scoped reorder view | superseded *(by REQ-020)* | [REQ-018](REQ-018.md) | REQ-001, REQ-003 |
| REQ-020 | Decouple the source compilation from server-held data | done | [REQ-020](REQ-020.md) | REQ-001, REQ-003 |
