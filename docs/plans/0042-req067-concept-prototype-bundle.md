# Plan 0042 — REQ-067: committed-prototype doctrine + concept bundle directory

Unblocks FlowSteward REQ-055. Two moves, both subtraction-shaped:

1. **Doctrine** — amend REQ-039 Decision 4. The "spikes/prototypes are throwaway, never
   committed" absolute becomes: a `concept: true` REQ MAY keep a durable, committed, frozen
   prototype as its deliverable (author decides per REQ, no engine-enforced criterion); the
   throwaway spike stays a valid choice. No engine enforcement — committing a prototype is just
   committing tracked code; the land is already non-destructive (REQ-063).

2. **Gate** — widen `ConceptArtifactGate` (`devsteward/profiles/req/checkpoint.py`) from a flat
   `docs/concepts/REQ-NNN.md`-only check to also accept a non-empty bundle directory
   `docs/concepts/REQ-NNN/`.

## Files touched

- `devsteward/profiles/req/checkpoint.py` — `ConceptArtifactGate.__call__`:
  - **Existence:** satisfied by the flat file `concepts_dir/REQ-NNN.md` **or** a directory
    `concepts_dir/REQ-NNN/` containing at least one file (`any(p.is_file() for p in
    bundle.rglob("*"))`). Empty/absent → refuse.
  - **Link:** satisfied by a `concept_refs` entry containing `REQ-NNN.md` **or** `REQ-NNN/`
    (points inside the bundle). Otherwise refuse, message still names `concept_refs`.
  - Refusal strings updated to name both forms; keep the substrings the existing AC2/AC3 assert
    (`"no" … "REQ-NNN.md"` for existence; `"concept_refs"` for link).
- `tests/test_concept_phase.py` — add helpers `_write_bundle` + 3 tests (AC1/AC2/AC3 of REQ-067).
  Existing REQ-039 tests (AC1–AC4) stay green (back-compat).
- `docs/requirements/REQ-039.md` — a Note amending D4 + cross-link to REQ-067.
- Handbook concept text: `_01-format.qmd`, `_02-engine.qmd`, `_03-workflow.qmd` — name the
  bundle-directory form + committed-prototype option.
- `devsteward/templates/STEWARD.md` — concept-gate description names the bundle form.
- `.claude/skills/intake/SKILL.md` §2c — `concept:` guidance states the bundle layout + that a
  prototype may be kept (hardlinked to the stamped template).

## Tests (REQ-067 ACs)

- **AC1** `test_concept_bundle_directory_satisfies_gate` — non-empty `docs/concepts/REQ-NNN/`,
  no flat file, ref points inside → admitted.
- **AC2** `test_flat_form_admits_and_absent_or_empty_bundle_refused` — flat form still admits;
  neither artifact → refused; empty bundle dir → refused.
- **AC3** `test_concept_bundle_must_be_linked_in_concept_refs` — dir present but unreferenced →
  refused (names `concept_refs`); linked inside the dir → admitted.

All hermetic regression (gate return over a `tmp_path` tree). No new step/verb/skill.
