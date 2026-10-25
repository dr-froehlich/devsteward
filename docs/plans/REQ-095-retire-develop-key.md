# Plan — REQ-095: retire the `process.develop` key

**REQ:** [REQ-095](../requirements/REQ-095.md) · one fused develop checkpoint, no concept
phase, no lab, no System-Test phase (all six ACs are `regression`).

## Approach

A subtraction in the shape REQ-083 established: delete the reader, delete every live
mention, and make the legacy value inert *by construction* rather than by a migration.
The one structural difference from REQ-083 is that tolerance is not free here — the
`process` block is `additionalProperties: false`, so the `develop` property must stay
**declared** in both schema copies or 125 REQs across 7 repos red at once through the
shared pipx engine.

Order of work: engine (the reader) → schema (tolerance) → shipped surfaces → doctrine →
tests. Nothing depends on a later step, so the sequence is only for reviewability.

## 1. Engine — remove the only reader

| File | Change |
|---|---|
| `devsteward/profiles/req/source.py:84-92` | Delete the `if proc.get("develop") == "split"` branch; `attended_reason` is set by `proc.get("concept")` alone (`if`, no longer `elif`). |
| `devsteward/profiles/req/reqfile.py:44-47,119-125` | Drop `"develop": "fused"` from `PROCESS_DEFAULTS`; update the comment and the `process` docstring to name concept/lab/fixtures only. A legacy raw `develop:` still merges through `merged.update(raw)` and is read by nothing — that is the tolerance, and it is structural. |
| `devsteward/core/model.py:64-65` | The `attended` comment names the concept phase only. |

After this, `grep -rn 'process\["develop"\]\|get("develop")' devsteward/` returns nothing.

## 2. Schema — declared, accepted, ignored (both copies)

`devsteward/schema/req.schema.json` (the one `lint` actually reads) and
`devsteward/templates/docs/requirements/schema/req.schema.json` (the stamped reference).

Keep the property and **keep its `enum: ["fused", "split"]`** — the tightest tolerance:
historical values stay valid, a typo like `develop: turbo` still fails schema (the
existing `test_process_block` case (c) survives unchanged). Only the `description` changes,
to state that the key is retired and the engine does not read it.

This is the sole place REQ-095 leaves explanatory residue, and deliberately so (REQ-095
decision 7): the key must remain *declared* to do its tolerance job, so it must say why.

## 3. Shipped surfaces — no live `develop:` declaration

| File | Change |
|---|---|
| `docs/requirements/_templates/req.md:15` and `devsteward/templates/docs/requirements/_templates/req.md:15` | Drop the `#   develop: fused …` line from the commented `process:` example. |
| `devsteward/templates/STEWARD.md:94` | The phase-model fork loses the flag (see §4). |
| `devsteward/templates/STEWARD.md:141` | "A REQ that needs a human (e.g. `develop: split`)" → the concept phase as the attended need. |
| `devsteward/templates/STEWARD.md:247` | D/H row: "no plan artifact, or split/attended need" → "no plan artifact, or a declared concept phase". |
| `devsteward/templates/CLAUDE.md.tmpl:37-40` | Replace the false flat-path-only bullet (decision 6). |

The repo-root `STEWARD.md` is a **symlink** to the template — one file, edited once.

### The CLAUDE.md.tmpl bullet

Today it asserts the concept doc "**must** be written at the flat path
`docs/concepts/REQ-NNN.md` (not a subdirectory …)" and that "the develop land gate enforces
this". Both are false: `ConceptArtifactGate` accepts a non-empty `<concepts_dir>/REQ-NNN/`
bundle (REQ-067) and the directory is configurable (REQ-084). The replacement states the
two accepted shapes, the `concept_refs:` link requirement, and uses `concepts_dir`.

## 4. Doctrine — REQ-071 rule 5 restated without the fiction

Three surfaces carry the phase-model fork: the intake skill §2c, `STEWARD.md`, and
`devsteward/handbook/_00-method.qmd:59-65`. Each currently offers "`develop: split` (a
post-freeze develop phase authors the target ACs) **or** a named downstream REQ".

New wording, in all three: the post-freeze work is authored either by **the concept session
itself, once the deliverable is frozen**, or by a **named downstream REQ** — and the
upstream REQ must **never carry the downstream REQ's acceptance bar**. That is what all
eight concept+split REQs actually did; only the fictional phase is removed. The
"unexamined combination is the defect" sentence goes with it (there is no longer a
combination to leave unexamined).

## 5. Remaining doc surfaces

| File | Change |
|---|---|
| `devsteward/handbook/_01-format.qmd:22,31-36` | Drop `develop:` from the example block; the `process:` prose describes concept + lab only, and the "absent block" defaults lose `develop: fused`. |
| `devsteward/handbook/_02-engine.qmd:91-92` | "A REQ that declared `develop: split` or `concept: true` is batch-ineligible" → concept only. |
| `devsteward/handbook/_03-workflow.qmd:26-28,261` | Same substitution in the land paragraph and the D/H recovery row. |
| `.claude/skills/intake/SKILL.md` §2c l.232-234 | Delete the `develop:` bullet — §2c asks **two** declarations (`concept:`, `lab:`), and its heading text drops "three". |
| `.claude/skills/intake/SKILL.md:176` | The live-proof-in-develop guidance states the obligation without naming a flag. |

The intake skill and its stamped template are **one inode** — edit once, never twice.
`/advance` needs no change: it carries no `split` handling and its concept section is
already correct.

## 6. Tests

**New — `tests/test_req095_develop_key_retired.py`**, owning all six ACs:

| AC | Test | Oracle |
|---|---|---|
| AC1 | `test_legacy_split_req_is_not_attended` | `ReqStepSource` yields `attended is False` for a `develop: split` / concept-false REQ, **and** a full `Executor.run()` lands it (`RunOutcome.DONE`) instead of parking — the behavioural proof that the reader is gone. |
| AC2 | `test_concept_still_parks_and_gates` | A `concept: true` REQ still parks with the concept hold note, and `ConceptArtifactGate` still refuses a land with no deliverable — the `if`/`elif` collapse regresses neither. |
| AC3 | `test_legacy_develop_key_lints_green_and_is_ignored` | `lint` returns `[]` for REQs carrying `develop: split` and `develop: fused`; `ReqFile.process` has no `develop` key of its own. |
| AC4 | `test_no_live_develop_declaration_in_package` | Package-wide line scan of `devsteward/` (the REQ-083 guard pattern): no `develop: split` / `develop: fused` and no "design review" wording, with the two schema files' legacy `description` lines the only permitted hits. |
| AC5 | `test_claude_tmpl_concept_path_bullet_is_accurate` | The tmpl bullet mentions the bundle directory and `concept_refs:`, and asserts the absence of the flat-path-only claim. |
| AC6 | `test_phase_model_rule_restated_without_a_flag` | All three doctrine surfaces carry the new fork and the no-imported-bar clause, and none names `develop: split`. |

**Updated (they assert the retired behaviour today):**

- `tests/test_phase_model.py::test_split_and_concept_park_in_batch` → renamed to
  `test_concept_parks_in_batch`; the `develop: split` REQ becomes the *negative* case
  (it now lands), keeping REQ-029 Decision 9's real content — concept parks, default lands.
- `tests/test_process_block.py` → the two `develop: split` expectations drop `develop`
  from the `ReqFile.process` dicts; case (c)'s out-of-enum check survives unchanged
  (§2 keeps the enum); one case gains a legacy-tolerance assertion.
- `tests/test_req071_doctrine_surfaces.py` → the two `assert "develop: split" in …`
  assertions invert to the restated fork (rule 5 keeps its `_NO_IMPORTED_BAR` anchor).

## Verification

`python -m pytest` green in full, plus `steward lint`. Close with
`steward checkpoint REQ-095 develop`.

## Out of scope

The packaged↔stamped schema drift (`process.fixtures`, the pre-REQ-048 `supersedes` shape)
is REQ-095 decision 8's named follow-on, **REQ-096** — this plan touches only the
`develop` property's description in the stamped copy and leaves the drift as it found it.
