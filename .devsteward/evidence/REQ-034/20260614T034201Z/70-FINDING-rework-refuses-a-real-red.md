# FINDING (hard) — `steward rework` refuses a genuinely-red validation

Surfaced after the AC6 decline (this evidence run + the 050606Z re-run). REQ-034's
validation went **red** — Peter declined AC6 twice (`d`), the engine recorded
`validation … ok:false` and parked the red decision, and the park itself printed the
correct next step:

    Return it to develop for a fix with `steward rework REQ-034` (the V-model return edge).

Following that printed instruction from a plain shell **fails**:

    $ steward rework REQ-034
    Error: REQ-034 has no red validation to rework — REQ-034:validate is not
    blocked on a red System-Test result. Run `steward validate REQ-034` to
    validate it, or `steward recover REQ-034` if a step actually failed.

`steward recover REQ-034` also refuses ("no failed step to recover"). So a real red
decline has **no working return edge** — the V-model edge REQ-033/REQ-034 exists to
provide is unreachable in exactly the case it was built for.

## Why rework refuses (mechanism)

`lifecycle.rework` (devsteward/lifecycle.py:166-176) gates on TWO facts read from the
ledger **of the branch it runs on**:

1. `ledger.latest_validation("REQ-034").get("ok") is False` — the latest `validation`
   event is red, AND
2. `ledger.status_of("REQ-034:validate") is StepStatus.BLOCKED`.

Peter ran `rework` from `dev` (the integration branch — the documented home of the
ledger and of operator verbs). On `dev`:

| Gate | dev (HEAD where rework runs) | feature branch `req-034-…` |
|---|---|---|
| `REQ-034:validate` status | `blocked-on-decision` ✓ BLOCKED | `blocked-on-decision` |
| latest `validation` event for REQ-034 | **absent** → `latest_validation` = `None` | present, `ok:false` (04:58:09Z, 05:07:01Z) |
| parked red decision | DEC-002 (the pre-verdict **placeholder**, open) | DEC-002 + DEC-003 (red), both open |

The red `validation` events and the red park (DEC-003) were written to the **feature
branch's** ledger. `dev`'s ledger still holds only the pre-verdict placeholder DEC-002
and **no validation event at all**. So gate (1) is false on dev → `is_red` is `False`
→ rework refuses. The error message ("not blocked on a red System-Test result") is
**misleading**: the step *is* blocked, and a red System-Test result *does* exist — just
not on the branch where rework looks.

## This is the downstream consequence of Finding 60

Finding 60 (`60-FINDING-park-not-resumable-from-dev.md`) found that an async-QA park
writes all its bookkeeping to the feature branch and leaves no trace on `dev`, so the
park is not resumable from dev. **The same gap breaks the red return edge:** the red
verdict is recorded on the feature branch, never reconciled onto dev, so every
dev-side verb that reads the validation outcome (`rework`, `status`) is blind to it.
60 = "can't resume a pending park from dev"; 70 = "can't rework a red verdict from
dev". One root cause (the verdict half lands only on the feature branch), two broken
verbs.

## ACs / Decisions touched

- REQ-033 AC (rework is the human-authorized return edge from a red validation) — the
  edge is documented and code-present, but unreachable from dev after a real red.
- REQ-034 Decision 7 (a declined validation routes the human to `steward rework`) — the
  routing message is printed, then the routed-to command refuses. A self-broken promise,
  same shape as the park's self-broken instruction in Finding 60.
- North-star D3 ("the engine is the bookkeeper"): the human is told to hand-reason about
  which branch holds the red, or to re-run `steward validate` (which re-parks, not
  reworks) — the bookkeeping the engine should own.

## Root gap (same as 60) + a message defect

1. **Reconciliation gap (shared with 60):** a red verdict recorded async on the feature
   branch must land where dev's verbs can see it — recorded on dev's ledger (with a
   pointer to the feature branch) OR the dev-side verbs must scan branches for it. Until
   then `rework` (and `recover`, and `status`) cannot act on the red.
2. **Message defect (rework-local):** even granting the reconciliation gap, the refusal
   text asserts "not blocked on a red System-Test result" when the step IS blocked. It
   conflates "no red event on THIS ledger" with "no red anywhere," giving the operator
   no hint that the red is on a feature branch awaiting reconciliation.

## Verdict authorship

None asserted. Reviewable evidence only; AC6 remains Peter's manual decision.
