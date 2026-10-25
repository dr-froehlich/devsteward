# Plan 0034 — REQ-060: a caught-up project reports an honest terminal state

Covers **REQ-060**. A display-only fix (Decision 4: the persisted cursor and its semantics
are unchanged). Two CLI command bodies change in `devsteward/cli.py`; no executor seam, no
ledger write, no new machinery.

## The defect

After the last REQ lands, the persisted cursor stays pinned to that now-`done` step
(`set_cursor` is written on start/land, never cleared). `steps()` derives steps only for
*active* REQs, so the cursor names a step the engine itself refuses to derive — and three
surfaces then contradict each other:

1. `steward status` prints `cursor: REQ-NNN:develop` (a done step) and then "no active
   steps" — pending-looking cursor over a "nothing here" line.
2. `steward checkpoint REQ-NNN` on that done REQ fails with the generic *"is REQ-NNN active
   (not draft/done)…?"* question — interrogating the user about a state the engine knows.
3. No-arg `steward checkpoint` pushes the stale cursor into the same "not a derivable step"
   error.

## The fix — three touches in `cli.py`

### 1. `status` — show the cursor only while it is derivable; otherwise affirm the terminal (AC1)

In the `status()` body:
- Compute `derivable = {s.id for s in steps}` and `cursor = led.cursor_step`.
- Print the `cursor:` line **only** when `cursor in derivable`; otherwise print the bare
  `profile:` line (no misleading cursor).
- When `steps()` is empty, replace the flat *"no active steps…"* line with a forward-path
  line: when any REQ is still `draft`, point at `steward activate`; otherwise the
  all-caught-up line *"all requirements done — nothing to do; add the next with `/intake`."*
  Draft detection: `any(r.status == "draft" for r in load_reqs(cfg.req_dir))`.

### 2. `checkpoint REQ-NNN` on a done REQ names *done* (AC2)

When `step_by_id(step_id)` is `None` for an explicit target, load the REQ via
`cfg.req_dir`; if its status is `done`, raise *"REQ-NNN is done — nothing to checkpoint;
supersede it to change direction"*. Only fall back to the existing generic
active/draft/done question for the genuinely-not-done causes (draft, missing, wrong phase).

### 3. No-arg `checkpoint` with a stale/unset cursor says "nothing in flight" (AC3)

In the `req_id is None` branch, after resolving `step_id` from the cursor, raise *"nothing
in flight to checkpoint"* when the cursor is unset **or** `step_by_id(step_id) is None`
(it names a done/non-derivable step) — instead of falling through to the derivable error.

## Out of scope (Decision 4)

No reset-on-completion, no clearing write, no removal of the `cursor` field — the persisted
cursor's write sites and the no-arg resolution of an *in-flight* develop step are untouched.

## Tests (all regression, CliRunner over the engine's own surface)

- `tests/test_cli_smoke.py::test_status_all_done_terminal_state` — a scaffolded project with
  its only REQ `done` and the cursor pinned to that done step: status prints the `/intake`
  terminal line and **no** `cursor:` line naming the done step.
- `tests/test_checkpoint.py::test_checkpoint_done_req_names_done` — `checkpoint REQ-001` on a
  done REQ exits non-zero, names it *done*, points at *supersede*, and does **not** ask the
  generic *"active (not draft/done)…?"* question.
- `tests/test_checkpoint.py::test_checkpoint_no_arg_stale_cursor_nothing_in_flight` — no-arg
  `checkpoint` with the cursor pinned to a done step reports *"nothing in flight to
  checkpoint"*, not the *"not a derivable step"* error.
