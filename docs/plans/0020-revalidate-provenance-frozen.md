# Plan 0020 — REQ-035: re-validating a done REQ leaves `verified_by` frozen

Covers **REQ-035**. A focused defect fix: a `done` re-validation (`steward validate` on a
done REQ → `revalidate`, `in_flight=False`) advertises itself as non-mutating (REQ-030 D5,
"status untouched"), but the mechanism silently rewrites the REQ's `verified_by`, clobbering
the original landing provenance with whatever a casual re-check happened to say. The
appended `events.jsonl` validation event (REQ-030 D3) is already the durable, dated
re-validation record, so the provenance field need not change — it stays frozen
("done is never weakened", REQ-001).

## Diagnosis (confirmed against the tree)

- `validate.py` `_validate` (green branch, step 5) calls `_write_verified_by` **before** the
  `if not in_flight: return` early-out — so the done re-validation path hits the writer on
  its way through. The fix is purely ordering: skip the writer when `in_flight=False`.
- `reqfile.py` `set_frontmatter_verified_by` is the unconditional in-place rewriter. It is
  left as-is — the chosen fix is *leave-untouched*, not an append mode (REQ-035 Notes:
  growing the line on every casual re-check only bloats it and risks a hollow note
  overwriting a substantive one). The in-flight landing path still calls it.
- `cli.py` prints `"(status untouched)"` — honest about the cursor, silent about the
  clobbered provenance line.

## Changes

1. **`devsteward/profiles/req/validate.py` `_validate`** — move the `if not in_flight:`
   early-out *above* `_write_verified_by`, so the done re-validation returns `DONE` with the
   evidence event already appended (step 4) and the REQ file untouched. The in-flight path is
   unchanged: it composes and writes `verified_by` (landing provenance being established) and
   lands mechanically. Refresh the step-5 comment and the `revalidate` docstring (which
   currently claims it "refreshes `verified_by`").

2. **`devsteward/cli.py` `validate`** — the done re-validation message states that fresh
   evidence was recorded and the REQ file is unchanged (status *and* `verified_by` both
   frozen); it neither claims nor performs a provenance rewrite. Update the command docstring
   to match.

## Acceptance tests — `tests/test_revalidate_provenance.py`

Wired like `test_system_test_phase.py` (real REQ source/verifier/flipper/land-gate/validate
routine around the fake System-Tester runner + in-memory git):

- **AC1** `test_done_revalidation_leaves_verified_by_and_status_frozen` — land a REQ green
  (writes `verified_by`), capture the file bytes, then `revalidate`: assert `verified_by`
  byte-identical, status still `done`, and a fresh `validation` event (`rerun=True`, per-AC
  results + artifact sha256s) appended.
- **AC2** `test_in_flight_validation_still_writes_verified_by` — an in-flight first green
  validation still composes and writes `verified_by` (the guard is scoped to the done re-run).
- **AC3** `test_revalidate_cli_message_is_honest` — the `steward validate` message on a done
  REQ names `verified_by` as frozen/unchanged and does not claim a rewrite (revalidate
  stubbed so the message branch is isolated from a real claude session).

## Out of scope

Committing the re-validation's event on the done path (REQ-032/034 clean-tree invariant);
what an in-flight validation writes (unchanged); a red on a done re-validation (supersede,
not rework — REQ-030 D5 / REQ-033 D3).
