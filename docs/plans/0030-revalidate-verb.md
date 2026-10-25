# Plan 0030 — `steward revalidate` (REQ-055)

The validate-layer mirror of `steward rework`. A red validation has two causes: the develop
was **hollow** (internal — `rework` reopens develop) or an **external** lab/setup issue was
fixed and the develop **stands** (re-run validate only — this verb). Today only `rework` is
named and the red-park brief steers unconditionally to it, pushing the external-cause human
into a needless develop redo. This REQ names the missing edge and fixes the brief.

A *rename-and-name* move, not new machinery: the re-validate-only action already exists
(`decision answer DEC` flips validate `BLOCKED→PENDING` with develop left `DONE`, then
`steward validate`). This gives it one honest verb and an honest brief.

## Data / interfaces

- `lifecycle.revalidate(cfg, ledger, req_id) -> RevalidateResult` — mirror of `rework`'s
  precondition checks (in-flight, red validation, validate `BLOCKED`); **opposite action**:
  - leaves `REQ:develop` **untouched at `DONE`** (no `set_status`),
  - sets `REQ:validate` `BLOCKED → PENDING`,
  - answers any open decision parked on the validate step,
  - appends a `revalidate` event carrying the red validation's `evidence` + `brief`.
  - touches no git, no REQ file.
- `RevalidateResult` dataclass: `req_id`, `validate_step`, `evidence`, `brief`, `decision`.
  (No `develop_step` field — develop is deliberately not the subject of this edge.)
- Refusal taxonomy identical to `rework` (`LifecycleError`): unknown id, `done` REQ →
  supersede pointer, no validate step (no artifact/manual AC), validate not `BLOCKED`-on-red.

## Brief fix (`validate.py:_park_red`)

Replace the single `rework = "Return it to develop…"` line with a two-edge choice naming
both `steward rework {req}` (develop was hollow — internal cause) and
`steward revalidate {req}` (an external lab/setup issue was fixed — develop stands), keyed
on the root cause. Applies to both the in-flight parked-decision `question` and the
non-in-flight `VERIFY_FAILED` detail. Keeps the literal `steward rework` substring (existing
`test_guided_validation.py` assertions depend on it).

## CLI

`steward revalidate REQ` mirrors `rework`: `check_invariants(allow_any_head=True)` inside an
atomic `transaction(pass_through=(LifecycleError,))`, prints the `validate → pending`
transition on success, maps `LifecycleError` to a non-zero `ClickException`.

## Tests — `tests/test_revalidate.py`

Reuses `test_rework.py`'s `_seed_red` harness (imported) for the identical red-validation
topology.

- AC1 `test_revalidate_rearms_validate_only` — validate `BLOCKED→PENDING`, develop stays
  `DONE`, decision answered, `revalidate` event with evidence+brief, REQ file byte-identical.
- AC2 `test_revalidate_refusals` — unknown id / done→supersede / no validate step / green
  (not blocked-red) / awaiting-oracle manual park.
- AC3 `test_red_park_brief_names_both_edges` — `_park_red` in-flight decision question AND
  non-in-flight VERIFY_FAILED detail both contain `steward rework` and `steward revalidate`.
- AC4 `test_revalidate_cli_wiring` — `revalidate` registered, succeeds regardless of HEAD in
  a transaction, prints `validate → pending`, non-zero on `LifecycleError`.
