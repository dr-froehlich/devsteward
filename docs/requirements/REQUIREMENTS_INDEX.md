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
| REQ-017 | Converter (legacy prose) — parse prose-header REQs into the hybrid schema, on REQ-010's core | DONE | [REQ-017](REQ-017.md) | REQ-002, REQ-010 |
| REQ-018 | `steward checkpoint` — the engine is the verifying bookkeeper for interactive work | DONE | [REQ-018](REQ-018.md) | REQ-003, REQ-020, REQ-028, REQ-029 |
| REQ-019 | Branching regime — declaration on the integration branch; only implementation branches | DONE | [REQ-019](REQ-019.md) | REQ-011 |
| REQ-020 | Branch lifecycle automation — the executor manages the implementation feature branch end-to-end | DONE | [REQ-020](REQ-020.md) | REQ-011, REQ-019 |
| REQ-021 | Lettered REQ ids — accept a single-letter suffix for split-umbrella requirements | DONE | [REQ-021](REQ-021.md) | REQ-002 |
| REQ-022 | steward seed-ledger — seed a ledger for an already-built corpus so historic REQs read as done | DONE | [REQ-022](REQ-022.md) | REQ-003, REQ-004, REQ-021 |
| REQ-023 | Converter index splice — preserve a project's surrounding index prose | DONE | [REQ-023](REQ-023.md) | REQ-010 |
| REQ-024 | onboard skill — orchestrate migrating an existing project under the steward engine | DONE | [REQ-024](REQ-024.md) | REQ-007, REQ-009, REQ-010, REQ-021, REQ-022, REQ-023 |
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
| REQ-038 | Cross-host validation deploy channel — validate exports a clean release-candidate artifact; live fixes return as a patch (artifact-export, Finding 90 option A) | SUPERSEDED | [REQ-038](REQ-038.md) | REQ-030, REQ-033, REQ-034, REQ-037 |
| REQ-039 | Concept phase — an interactive architecture/exploration session that gates develop (left-arm counterpart of the System-Test phase) | DONE | [REQ-039](REQ-039.md) | REQ-027, REQ-029, REQ-030, REQ-034 |
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
| REQ-057 | Post-REQ-047 documentation refresh + a Claude-targeted `steward` black-box manual | DONE | [REQ-057](REQ-057.md) | REQ-007, REQ-034, REQ-047, REQ-054, REQ-055, REQ-056 |
| REQ-058 | Engine budget gate delegates to clauder — per-step `clauder gate`, no direct cswap, race-free with a background monitor | DONE | [REQ-058](REQ-058.md) | REQ-008, REQ-025 |
| REQ-059 | An interrupted run self-heals a stranded RUNNING step, and ineligibility names the real cause | DONE | [REQ-059](REQ-059.md) | REQ-025, REQ-026, REQ-053 |
| REQ-060 | A caught-up project reports an honest terminal state — the cursor never names a done step | DONE | [REQ-060](REQ-060.md) | REQ-018, REQ-047, REQ-056 |
| REQ-061 | Re-wire the account pin — `steward --pin N` forwards `clauder gate --pin N`, draining one account before its 7d reset | DONE | [REQ-061](REQ-061.md) | REQ-058 |
| REQ-062 | First onboarding — drive memzy under the engine via the onboard skill (the live proof run) | DONE | [REQ-062](REQ-062.md) | REQ-022, REQ-023, REQ-024 |
| REQ-063 | Non-destructive capture gate — withhold certification without destroying the work commit; an environment skip is not a capture gap | DONE | [REQ-063](REQ-063.md) | REQ-047, REQ-048, REQ-049, REQ-050 |
| REQ-064 | Intake screens environment-bound `regression` ACs — route by oracle coupling so a green can't silently become a skip | DONE | [REQ-064](REQ-064.md) | REQ-027 |
| REQ-065 | Validate pre-flight gate + steward reland — formality checks before the session, recovery without re-validation | DONE | [REQ-065](REQ-065.md) | REQ-029, REQ-039, REQ-056 |
| REQ-066 | sync covers STEWARD.md — track every engine-owned stamped artifact, not just skills | DONE | [REQ-066](REQ-066.md) | REQ-024, REQ-036, REQ-057 |
| REQ-067 | Concept phase may keep a committed prototype; the concept gate accepts a docs/concepts/REQ-NNN/ bundle directory | DONE | [REQ-067](REQ-067.md) | REQ-039, REQ-057 |
| REQ-068 | Deterministic acceptance-test execution — a `check: live` standing-regression lane, develop-gate routing by check:, fail-hard on a missing declared resource, one test flavor | DONE | [REQ-068](REQ-068.md) | REQ-027, REQ-028, REQ-063, REQ-064 |
| REQ-069 | Build delivers the validation fixtures it owes — close the REQ-051 pincer so a missing seeded fixture can't deadlock validation | DRAFT | [REQ-069](REQ-069.md) | REQ-051, REQ-030 |
| REQ-070 | Full-suite deselection must use only real node-ids — a manual/artifact AC's prose can't poison the develop gate into deselecting the whole suite | DONE | [REQ-070](REQ-070.md) | REQ-068 |
| REQ-071 | Concept-phase & wiring-gap doctrine — concept-phase-as-functional-spec, wire-through-the-live-entrypoint, don't-scope-a-known-defect-out, concept-phase-iterates-until-frozen, phase-model-placement | DONE | [REQ-071](REQ-071.md) | REQ-018, REQ-027, REQ-039, REQ-064, REQ-067, REQ-068 |
| REQ-072 | Capture gate runs in the operator's declared environment — carry the env-file into the extract, and diagnose an env gap honestly | DONE | [REQ-072](REQ-072.md) | REQ-063, REQ-068 |
| REQ-073 | Ledger lost-update guard + stale-decision recovery — a save can never silently rewind newer state, and a diverged cursor has a sanctioned way back | DONE | [REQ-073](REQ-073.md) | REQ-003, REQ-005, REQ-035, REQ-055, REQ-057 |
| REQ-074 | The `steward decision` surface earns its shape — a genuine-fork tool or a smaller one, decided from real usage | DONE | [REQ-074](REQ-074.md) | REQ-005, REQ-056, REQ-057 |
| REQ-075 | Per-AC revalidation — revalidate re-opens only the red ACs, carries green one-off evidence forward, and the engine hands the evidence dir to the grading tests | DONE | [REQ-075](REQ-075.md) | REQ-034, REQ-055, REQ-068, REQ-072 |
| REQ-076 | Scope the engine's headless code commit to what the command itself authored — a boundary-delta stage so a concurrent session's dirty files can't be swept into another REQ's commit | SUPERSEDED | [REQ-076](REQ-076.md) | REQ-048, REQ-049, REQ-050, REQ-063 |
| REQ-077 | The checkpoint commit is atomic — the status flip rides the code commit, a leftover is caught, and the ledger↔marker guard is symmetric | DONE | [REQ-077](REQ-077.md) | REQ-018, REQ-028, REQ-032, REQ-063, REQ-076 |
| REQ-078 | /advance targets the in-context REQ and treats validations as out of scope — no more validation-prep drift | DONE | [REQ-078](REQ-078.md) | REQ-030, REQ-042, REQ-065 |
| REQ-079 | Reestablish the whole-tree code commit — remove the REQ-076 boundary-delta scoping, keep REQ-077's guards, codify one-session-at-a-time as doctrine | DONE | [REQ-079](REQ-079.md) | REQ-063, REQ-076, REQ-077 |
| REQ-080 | steward run rides through a budget limit — clauder-corroborated classification, wait-and-relaunch via the gate, recovery-signaled resume | DONE | [REQ-080](REQ-080.md) | REQ-016, REQ-025, REQ-058, REQ-059 |
| REQ-081 | Warm validation cycle — steward validate start/record as real CLI verbs, the verdict recorded from a second shell, the System-Tester session survives a red through rework | DONE | [REQ-081](REQ-081.md) | REQ-030, REQ-033, REQ-034, REQ-055, REQ-075 |
| REQ-082 | steward cache — report the current project's Claude session cache warmth from a second shell, without touching the session | DONE | [REQ-082](REQ-082.md) | – |
| REQ-083 | Retire the roadmap artifact — delete the ROADMAP.md template + roadmap_file config seam, subtract roadmap steps from the stamped intake/bootstrap/onboard skills and the doctrine text; future-REQ layout lives in concept bundles with frozen slicing plans | DONE | [REQ-083](REQ-083.md) | – |
| REQ-084 | The doc layout is the consumer's, not the engine's — config seams for plans_dir/concepts_dir honored by the gates, the stamp and the stamped skills; and the operator-only onboard skill leaves the stamped set | DONE | [REQ-084](REQ-084.md) | REQ-024, REQ-029, REQ-036, REQ-039, REQ-066 |
| REQ-085 | THermo prose retrofit — extend the prose converter to the grammar the live corpus actually has, and drive the onboarding | DONE | [REQ-085](REQ-085.md) | REQ-017, REQ-024, REQ-084, REQ-086 |
| REQ-086 | Onboarding machinery repairs from the memzy run — commit-before-seed ordering, sync seeds _templates/, and the converter reports dropped keys | DONE | [REQ-086](REQ-086.md) | REQ-010, REQ-022, REQ-024, REQ-066 |
| REQ-087 | The north star lands at bootstrap — REQ-001 ships an extract-passable initialization check and /bootstrap closes it with steward checkpoint | DONE | [REQ-087](REQ-087.md) | REQ-007, REQ-063, REQ-077, REQ-084 |
| REQ-088 | Kill the suite's random reds — a collision-free evidence-dir mint and a land that always captures its own flip | DONE | [REQ-088](REQ-088.md) | REQ-075, REQ-077, REQ-079, REQ-081 |
| REQ-089 | The remote-host deployment seam — attended mid-phase push, a read-only land-gate preview, rework that carries prior sign-offs, and a flat discoverable CLI | DONE | [REQ-089](REQ-089.md) | REQ-030, REQ-033, REQ-055, REQ-063, REQ-071, REQ-075, REQ-081 |
| REQ-090 | No model identifiers in engine code — a generic co-author trailer, and the spawn model moved to config | DONE | [REQ-090](REQ-090.md) | REQ-029, REQ-036, REQ-048, REQ-079 |
| REQ-091 | A spawn never hides its model and a commit never misattributes it — surface the unset model, refuse it headless, retire the co-author trailer for `Assisted-by:`, and migrate the stamped consumers REQ-090 left behind | DONE | [REQ-091](REQ-091.md) | REQ-029, REQ-030, REQ-036, REQ-080, REQ-090 |

New requirement template: [`_templates/req.md`](../../devsteward/templates/docs/requirements/_templates/req.md)
