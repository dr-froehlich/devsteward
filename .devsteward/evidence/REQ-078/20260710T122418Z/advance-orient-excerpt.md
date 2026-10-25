## 1. Orient (always)

- Run **`steward status`** for the cursor (`cursor.step`, e.g. `REQ-007:develop`) and step
  statuses — never hand-read `.devsteward/state.yaml`. `steward status` is the one sanctioned
  read of the live ledger (there is a single ledger on `dev`). If invoked as
  `/advance REQ-NNN develop`, that is your target.
- **Choosing the target when none is named (interactive) (REQ-078).** Batch is always
  launched with an explicit `REQ-NNN develop` target — this whole bullet is *interactive-only*
  and does not touch the batch path. When a person runs `/advance` with **no** `REQ-NNN develop`
  argument:
  - **In-context, then ask (Decision 1).** If a REQ is fresh in the session context (e.g. one
    you just `/intake`-d this session), **ask** via `AskUserQuestion` whether to advance *that*
    REQ's develop step. On decline — or when nothing is in context — auto-select the next
    eligible step. The just-intook REQ is almost always what the operator means; asking removes
    the cursor-roulette that otherwise lands on an unrelated pending step.
  - **Skip validations when auto-selecting (Decision 2).** Auto-selection **skips any eligible
    `validate`/System-Test step** and advances the next **develop**-eligible step instead.
    `/advance` is the fused-develop skill; a validate step is `/system-test`'s job, run only via
    `steward validate REQ-NNN` in a plain shell — never adopted as an `/advance` target.
  - **No develop step eligible → surface and stop (Decision 3).** If nothing but validations is
    pending, **do not run one in-session** (the guided validate path refuses inside a live
    Claude/CLAUDECODE session by design). Surface the pending validation(s) with the exact
    `steward validate REQ-NNN` shell command and **stop** — the one honest terminal state
    (mirrors `steward run`'s caught-up report). `/advance` never runs a validation session.
