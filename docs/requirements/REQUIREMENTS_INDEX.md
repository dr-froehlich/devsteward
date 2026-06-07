# Requirements Index

DevSteward's own requirements, dogfooded in the hybrid format it ships. Kept in sync with
the REQ files by `steward lint` (status must match). Move a REQ's row in the **same
commit** as its frontmatter and the code.

| ID | Title | Status | File | Depends on |
|----|-------|--------|------|------------|
| REQ-001 | DevSteward — a controlled baseline + automation engine | DONE | [REQ-001](REQ-001.md) | – |
| REQ-002 | Hybrid machine-readable REQ format, schema, and linter | DONE | [REQ-002](REQ-002.md) | REQ-001 |
| REQ-003 | Generic executor core — ledger, eligibility, commit/advance | DONE | [REQ-003](REQ-003.md) | REQ-001 |
| REQ-004 | REQ-workflow profile — Design/Build/Land in dependency order | DONE | [REQ-004](REQ-004.md) | REQ-002, REQ-003 |
| REQ-005 | Park-and-surface — record forks while unattended, resume | DONE | [REQ-005](REQ-005.md) | REQ-003 |
| REQ-006 | Verification gate — engine runs named tests; only green is done | DONE | [REQ-006](REQ-006.md) | REQ-003 |
| REQ-007 | `steward new` — stamp scaffolding into a consumer project | DONE | [REQ-007](REQ-007.md) | REQ-002 |
| REQ-008 | Account/quota provider — claude-swap with degradation | DONE | [REQ-008](REQ-008.md) | REQ-003 |
| REQ-009 | Bundle the three skills with the park-and-surface contract | DONE | [REQ-009](REQ-009.md) | REQ-002, REQ-005 |
| REQ-010 | Converter — back-port legacy prose REQs (backlog) | DRAFT | [REQ-010](REQ-010.md) | REQ-002 |
| REQ-011 | Branch governance — engine enforces branch-before-main; config-driven branch names | OPEN | [REQ-011](REQ-011.md) | REQ-003, REQ-007 |
| REQ-012 | Rework the cswap account provider for the claude-swap 0.11 switcher CLI | DRAFT | [REQ-012](REQ-012.md) | REQ-008 |

New requirement template: [`_templates/req.md`](../../devsteward/templates/docs/requirements/_templates/req.md)
