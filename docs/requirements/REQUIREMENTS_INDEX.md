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
| REQ-010 | Converter — normalize memzy's frontmatter REQ dialect into the hybrid schema | DONE | [REQ-010](REQ-010.md) | REQ-002 |
| REQ-011 | Branch governance — engine enforces branch-before-main; config-driven branch names | DONE | [REQ-011](REQ-011.md) | REQ-003, REQ-007 |
| REQ-012 | Rework the cswap account provider for the claude-swap 0.11 switcher CLI | DONE | [REQ-012](REQ-012.md) | REQ-008 |
| REQ-013 | Reality harness — an opt-in end-to-end test that drives a real claude -p | DONE | [REQ-013](REQ-013.md) | REQ-003 |
| REQ-014 | Headless claude -p runs with a permission mode so it can edit autonomously | DONE | [REQ-014](REQ-014.md) | REQ-003 |
| REQ-015 | Verify teeth — a REQ cannot land on marker-trust | DONE | [REQ-015](REQ-015.md) | REQ-004, REQ-006 |
| REQ-016 | Usage-limit detection trusts the runtime signal, not echoed content | DONE | [REQ-016](REQ-016.md) | REQ-003, REQ-012 |
| REQ-017 | Converter (legacy prose) — back-port ExamEngineer's prose-header REQs (backlog) | DRAFT | [REQ-017](REQ-017.md) | REQ-002, REQ-010 |
| REQ-018 | `steward checkpoint` — the engine is the verifying bookkeeper for interactive work | DONE | [REQ-018](REQ-018.md) | REQ-003, REQ-020, REQ-028, REQ-029 |
| REQ-019 | Branching regime — declaration on the integration branch; only implementation branches | DONE | [REQ-019](REQ-019.md) | REQ-011 |
| REQ-020 | Branch lifecycle automation — the executor manages the implementation feature branch end-to-end | DONE | [REQ-020](REQ-020.md) | REQ-011, REQ-019 |
| REQ-021 | Lettered REQ ids — accept a single-letter suffix for split-umbrella requirements | DONE | [REQ-021](REQ-021.md) | REQ-002 |
| REQ-022 | steward seed-ledger — seed a ledger for an already-built corpus so historic REQs read as done | DRAFT | [REQ-022](REQ-022.md) | REQ-003, REQ-004, REQ-021 |
| REQ-023 | Converter index splice — preserve a project's surrounding index prose | DRAFT | [REQ-023](REQ-023.md) | REQ-010 |
| REQ-024 | onboard skill — orchestrate migrating an existing project under the steward engine | DRAFT | [REQ-024](REQ-024.md) | REQ-007, REQ-009, REQ-010, REQ-021, REQ-022, REQ-023 |
| REQ-025 | Visible account rotation, fixed-quota gating, and graceful stop for unattended runs | DONE | [REQ-025](REQ-025.md) | REQ-003, REQ-012 |
| REQ-026 | Lifecycle CLI — activate a REQ, recover a failed step, and target one REQ with --only | DONE | [REQ-026](REQ-026.md) | REQ-002, REQ-003 |
| REQ-027 | Acceptance test taxonomy — regression/artifact/manual that steers the V-model flow, seeded by intake | DONE | [REQ-027](REQ-027.md) | REQ-002, REQ-004, REQ-009 |
| REQ-028 | Gating integrity — skip isn't green, the named behaviour must run, verifier uses project venv + full suite, lint reconciles marker↔ledger | DONE | [REQ-028](REQ-028.md) | REQ-002, REQ-006, REQ-015 |
| REQ-029 | Phase-model rework — one fused develop step, mechanical land on green, bounded repair on red | DONE | [REQ-029](REQ-029.md) | REQ-004, REQ-020, REQ-027, REQ-028 |
| REQ-030 | System-Test phase — independent validation session, evidence events, and the System Tester skill | DONE | [REQ-030](REQ-030.md) | REQ-005, REQ-027, REQ-029 |
| REQ-031 | The first lab — consume FlowSteward's IMAP lab through the System-Test phase; FlowSteward re-drive | DONE | [REQ-031](REQ-031.md) | REQ-030 |
| REQ-032 | Ledger always committed — every terminal step outcome leaves a clean tree | DONE | [REQ-032](REQ-032.md) | REQ-018, REQ-020, REQ-030 |
| REQ-033 | Rework loop — steward rework returns a red validation to develop for a fix-and-revalidate cycle | DONE | [REQ-033](REQ-033.md) | REQ-026, REQ-030 |
| REQ-034 | Human validation as a guided, asynchronous activity — interactive System-Tester session, QA-ticket parking, clean re-entry | DONE | [REQ-034](REQ-034.md) | REQ-020, REQ-030, REQ-032, REQ-033 |
| REQ-035 | Re-validating a done REQ leaves verified_by frozen — provenance is not clobbered | DONE | [REQ-035](REQ-035.md) | REQ-030 |
| REQ-036 | steward sync-skills — refresh stamped bundled skills from the installed template, with a provenance manifest and a drift signal | DONE | [REQ-036](REQ-036.md) | REQ-007, REQ-030 |
| REQ-037 | The ledger lives on dev only — feature branches carry pure code, and topology operations are atomic and recoverable | SUPERSEDED | [REQ-037](REQ-037.md) | REQ-020, REQ-032, REQ-034 |
| REQ-038 | Cross-host validation deploy channel — validate exports a clean release-candidate artifact; live fixes return as a patch (artifact-export, Finding 90 option A) | DRAFT | [REQ-038](REQ-038.md) | REQ-030, REQ-033, REQ-034, REQ-037 |
| REQ-039 | Concept phase — an interactive architecture/exploration session that gates develop (left-arm counterpart of the System-Test phase) | DRAFT | [REQ-039](REQ-039.md) | REQ-027, REQ-029, REQ-030, REQ-034 |
| REQ-040 | Read commands resolve the live integration-branch ledger, and checkpoint refuses an already-done step | SUPERSEDED | [REQ-040](REQ-040.md) | REQ-018, REQ-037 |
| REQ-041 | Every read-side ledger access resolves the live integration-branch ledger — not just steward status | SUPERSEDED | [REQ-041](REQ-041.md) | REQ-037, REQ-040 |
| REQ-042 | Positional REQ target for advance/run — name the REQ to steer which eligible step runs | DONE | [REQ-042](REQ-042.md) | REQ-002, REQ-026 |
| REQ-043 | A surfaced branch divergence leaves no uncommitted ledger write, and the topology close-out switch never crashes on a dirty tree | SUPERSEDED | [REQ-043](REQ-043.md) | REQ-032, REQ-037 |
| REQ-044 | steward supersede — close an already-superseded feature branch without a false merge-by-hand recovery | SUPERSEDED | [REQ-044](REQ-044.md) | REQ-037, REQ-043 |
| REQ-047 | Single-source-of-truth state model — trunk-based on dev with a universal transaction boundary, so engine state cannot diverge or strand | DONE | [REQ-047](REQ-047.md) | REQ-002, REQ-018, REQ-020, REQ-032 |
| REQ-048 | Trunk-based model — all work on dev, deleting the worktree/switch/branch machinery | DONE | [REQ-048](REQ-048.md) | REQ-047 |
| REQ-049 | Universal transaction boundary + central invariants — no mutation can diverge or strand | DONE | [REQ-049](REQ-049.md) | REQ-047, REQ-048 |
| REQ-050 | Commit integrity — land refuses a green the recorded commit does not capture | DONE | [REQ-050](REQ-050.md) | REQ-047, REQ-048, REQ-049 |
| REQ-051 | Lab fixtures upstream — a missing fixture is a hard red and the System Tester never improvises | DONE | [REQ-051](REQ-051.md) | REQ-047, REQ-048 |
| REQ-052 | Post-REQ-047 cleanup — code + skill review for stale/bent legacy, with a sign-off report | DONE | [REQ-052](REQ-052.md) | REQ-047 |
| REQ-053 | Process resilience — every red step has an available forward path; audit the rework-vs-repeat model | DONE | [REQ-053](REQ-053.md) | REQ-047 |
| REQ-054 | Rename the recover verb to repeat — the run-it-again action, named honestly | DONE | [REQ-054](REQ-054.md) | REQ-026 |
| REQ-055 | steward revalidate — re-run a red validation without redoing sound develop work | DONE | [REQ-055](REQ-055.md) | REQ-033, REQ-047 |
| REQ-056 | Repair-exhausted and land-refused fail to a repeatable step, not a decision park (states D/H) | DONE | [REQ-056](REQ-056.md) | REQ-029, REQ-053, REQ-054 |
| REQ-057 | Post-REQ-047 documentation refresh + a Claude-targeted `steward` black-box manual | OPEN | [REQ-057](REQ-057.md) | REQ-007, REQ-034, REQ-047, REQ-054, REQ-055, REQ-056 |
| REQ-058 | Engine budget gate delegates to clauder — per-step `clauder gate`, no direct cswap, race-free with a background monitor | OPEN | [REQ-058](REQ-058.md) | REQ-008, REQ-025 |
| REQ-059 | An interrupted run self-heals a stranded RUNNING step, and ineligibility names the real cause | OPEN | [REQ-059](REQ-059.md) | REQ-025, REQ-026, REQ-053 |
| REQ-060 | A caught-up project reports an honest terminal state — the cursor never names a done step | OPEN | [REQ-060](REQ-060.md) | REQ-018, REQ-047, REQ-056 |

New requirement template: [`_templates/req.md`](../../devsteward/templates/docs/requirements/_templates/req.md)
