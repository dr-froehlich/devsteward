# Plan 0012 — Acceptance taxonomy + intake rewrite (REQ-027)

**Design checkpoint for REQ-027** (plan 0011 step 1, driven interactively). Ship the
**seed**: a required per-AC `check:` routing key (`regression | artifact | manual`), the
optional `process:` frontmatter block (concept / lab / fused-vs-split declarations), the
`/intake` rewrite that institutionalises system-level, artifact-bound acceptance, and the
handbook chapter that explains the V-model mapping. **No engine routing** — the verifier
and step source are untouched (Decision 11); REQ-029/030 consume what this lands.

Interview-settled mechanics (Decisions 9–12, 2026-06-10): lint enforces `check:` on
**active** REQs only, no backfill; declarations live in one optional `process:` block with
defaults; the land gate stays blind (loud failure accepted while `steward run` is parked);
`manual` checks discharge by hand-flip + provenance until REQ-030.

## Surfaces (confirmed by reading the code)

- `devsteward/core/model.py` — `AcceptanceCheck` (frozen dataclass: id/text/test/status).
  Gains `check: str = ""` — empty means *undeclared*, so lint can distinguish absence from
  a default; the core stays content-agnostic (it carries the field, the profile gives it
  meaning).
- `devsteward/profiles/req/reqfile.py` — `_parse_acceptance` maps the YAML items; add
  `check=str(item.get("check", ""))`. `update_acceptance_status` round-trips the loaded
  YAML, so unknown/new keys already survive the surgical status write-back — verify with a
  test, don't re-implement. `ReqFile` gains a `process` property returning the block merged
  over defaults `{"develop": "fused", "concept": False, "lab": []}` — the accessor REQ-029/030
  will read; absent block ⇒ pure defaults (AC5 "defaults apply" made concrete).
- `devsteward/schema/req.schema.json` — `additionalProperties: false`, so the optional
  `process` property must be added: object, `additionalProperties: false`, with
  `develop: enum [fused, split]`, `concept: boolean`, `lab: array of ^REQ-[0-9]{3}[a-z]?$,
  uniqueItems`. Nothing required; no new top-level required keys.
- `devsteward/lint.py` — rule 5's active-only loop is the model. Two additions:
  the `check:` presence+enum rule folded into that same loop (active REQs only,
  Decision 9), and `process.lab` resolution folded into rule 2 next to `depends_on`
  (lab refs resolve for **all** REQs, like other references — they're cheap and static).
  Out-of-enum `develop:` is caught by rule 1 (schema validation); lint adds no duplicate
  enum check.
- `.claude/skills/intake/SKILL.md` + `devsteward/templates/.claude/skills/intake/SKILL.md`
  — currently byte-identical; the rewrite keeps them identical (existing
  `tests/test_skills.py` parametrizes over both copies — extend that pattern).
- `devsteward/templates/docs/requirements/_templates/req.md` — the stub intake stamps
  from: example acceptance gains `check:`, frontmatter gains a commented optional
  `process:` block.
- `devsteward/handbook/01-format.md` (layers 1+2: the contract) and `03-workflow.md`
  (the V-model phase mapping).
- **Not touched (Decision 11):** `devsteward/profiles/req/verify.py`,
  `devsteward/profiles/req/source.py`, the executor.

## AC1 — `check:` field, lint-enforced on active REQs

Extend lint rule 5's loop (already scoped `if not r.is_active: continue`):

- `check` empty → `"{r.id}: acceptance {ac.id} has no check: classification
  (regression | artifact | manual)"`.
- `check` not in `{"regression", "artifact", "manual"}` → out-of-enum problem naming the
  value.

Drafts and terminal REQs are untouched — same rationale as rule 5 (drafts may be
incomplete; terminal REQs are history, incl. imported governance records).

`tests/test_lint_acceptance_taxonomy.py::test_check_field_required_and_enumerated`:
temp project with four fixture REQs — (a) **active**, AC missing `check:` → problem;
(b) **active**, `check: smoke` → problem naming the value; (c) **draft** without `check:`
→ clean; (d) **done** without `check:` → clean. Plus an active fully-classified REQ →
clean (the enum is accepted).

## AC5 — the `process:` frontmatter block

Schema addition as above. Lint resolves each `process.lab` entry against loaded REQ ids,
mirroring the `depends_on` loop ("process.lab 'REQ-099' does not resolve to a REQ").
`ReqFile.process` applies defaults.

`tests/test_process_block.py::test_process_block_schema_and_lab_resolution`:
(a) REQ with a full valid block → schema-clean, `process` property echoes it;
(b) REQ **without** the block → schema-clean, property returns the defaults
(`fused` / `False` / `[]`); (c) `develop: turbo` → schema problem (rule 1);
(d) `lab: [REQ-099]` with no REQ-099 → lint problem.

## AC2 — the `/intake` rewrite (the music)

Same content in both copies. The rewrite restructures §2 (Interrogate) and §3 (Emit):

- **Acceptance interrogation goes system-level.** Drive every criterion toward an
  end-to-end chain with a **measurable, captured deliverable** ("fetch *this* captured
  mail and compare", not "connects to a server"). The screening question is the
  **oracle**: *what decides pass/fail, and is it coupled to the code under test?* A
  criterion whose only oracle is a same-session mock is a `regression` check by
  definition — name it as such or sharpen it.
- **Classify every AC's `check:`** with the decision rule (oracle coupling, not test
  name): coupled/mock, headless → `regression`; decoupled durable observable produced by
  a lab, engine reads only the signal → `artifact`; human judgment → `manual`.
- **Honest deferral:** an `artifact`/`manual` check whose lab doesn't exist yet names the
  follow-on REQ in `process.lab` — never downgrade the check to `regression` to make it
  runnable, never fake a lab inline.
- **The three declarations, while the human is present** (emitted as the `process:`
  block): concept phase yes/no (risk buy-down/spike where final test specs and lab needs
  freeze), lab assets the System-Test phase will need, develop **fused** (default) vs
  **split** with an attended design review — split only for genuinely risky REQs, and the
  interview must extract *why*.
- §3 Emit: every criterion has `id`, `test:`, **`check:`**; the `process:` block is
  written only when it deviates from defaults *or* declares a lab; lint must stay green.

`tests/test_intake_skill_contract.py::test_intake_seeds_taxonomy_and_concept` (the AC2
name) asserts, on the **stamped** copy, the required markers: the enum triple, the oracle question, the
`process:` block with its three keys, the fused-default + split-exception instruction,
and the honest-deferral instruction. A second assertion (or the existing
`test_skills.py` parametrization) holds both copies byte-identical.

## AC3 — the handbook chapter

- `01-format.md`, Layer 1: document the optional `process:` block + defaults.
- `01-format.md`, Layer 2: `check:` field + enum; the **oracle glossary** (oracle vs
  fixture vs system-under-test; coupled vs decoupled vs human); one **fully-tagged
  example `yaml acceptance` block** showing all three values.
- `03-workflow.md`: the **V-model mapping** — `regression` → Build (verification, left
  side); `artifact`/`manual` → System-Test (validation, right side); the phase exists
  only if such a check exists; `manual` is a decision stop inside that phase. State
  plainly that the System-Test phase itself is REQ-030 (forward reference, not vapor).

`tests/test_handbook_taxonomy.py::test_handbook_documents_taxonomy_and_example` asserts
the anchors/sections and the example block exist in the packaged handbook files.

## AC4 — manual discharge (after merge, Decision 12)

Not a build artifact. After the implementation merges to `dev`, the next real `/intake`
run is reviewed end-to-end against this REQ's Decisions; the reviewer (Peter) flips AC4
`status: pass` by hand and records date/reviewer/scope in `verified_by`. The `done` flip +
index `DONE` sync happen in that same commit (same-commit discipline) — REQ-027 stays
`in-progress` until then. No ledger advance (interactive, pre-REQ-018).

## Dogfood impact (checked)

- REQ-027 is the **only active** REQ and its five ACs are classified — the new lint rule
  fires on nothing else. Drafts 029–031 already carry `check:`; stale drafts (017/018/
  022–024) are exempt until promotion.
- No existing REQ has a `process:` block — optional + defaults keeps schema rule 1 green.
- `update_acceptance_status` already preserves unknown keys (ruamel round-trip), so the
  engine's status write-back cannot strip `check:` — covered by a regression test in
  `tests/test_reqfile.py` rather than trusted.

## Build order (one feature branch: `req-027-acceptance-taxonomy`)

1. Model + parser: `AcceptanceCheck.check`, `_parse_acceptance`, `ReqFile.process`
   (+ `test_reqfile.py` additions incl. round-trip preservation).
2. Schema: `process` property (AC5 test, schema half).
3. Lint: check-enum rule in the rule-5 loop; `process.lab` resolution in rule 2
   (AC1 + AC5 tests complete).
4. Intake SKILL.md rewrite, both copies + `_templates/req.md` stub (AC2 test).
5. Handbook (AC3 test).
6. `steward lint` + full `python -m pytest` green → flip REQ-027 `in-progress` at branch
   start, merge plain into `dev` (no PR). AC4 + `done` follow per above.

## Invariants preserved

- Lint stays **static and presence-only** (Decision 5): no quality/granularity policing,
  no waiver machinery.
- design/build marker-trust and the REQ-028 land teeth are untouched; nothing here makes
  a previously-red gate green or vice versa for `regression`-only REQs.
- The acceptance block stays the **only** home of per-AC data; checkpoint state stays in
  the ledger (REQ format contract intact — parser change is additive).
- English-only technical text; no localized strings.

## Forks

None open — the four forks this REQ had (lint scope, declaration home, gate blindness,
manual discharge) were settled in the 2026-06-10 interview and are recorded as
Decisions 9–12 in the REQ.
