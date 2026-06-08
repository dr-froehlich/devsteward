# Stub for intake — executor manages the implementation-branch lifecycle

> Raw idea note. Not a schema-valid REQ. Feed to `/intake` (likely **REQ-020**) so the
> interview can interrogate the tensions below before writing frontmatter.

## The idea

When the executor hits a guarded `build` step on the integration branch, instead of *only*
refusing (REQ-019), it should **manage the branch topology end-to-end**: create the feature
branch, run build + land on it, then merge back into the integration branch — the
create → implement → test → merge dance that is currently manual.

## Why it came up

Before REQ-019 landed (the integration-branch guard + the CLAUDE.md / memory edits that say
"declaration on `dev`, only implementation branches"), feature branches were getting
auto-created all over the place — *including while merely writing a REQ*. That over-eager,
undisciplined branching is exactly what REQ-019 stopped. But the swing left a real gap: now
the engine refuses and hands the whole git dance back to the human. The wish is to automate
it again — but *correctly* this time: branch only for **implementation**, never for
declaration.

## The central tension intake must resolve

This **directly reverses REQ-011 Decision 1** and REQ-019's *Out of scope*:

> "the engine guards, it does not manage git topology."

So this is not a bugfix — it is a deliberate policy reversal, and intake should argue *why*
managing topology is now acceptable when it was previously refused, and what makes the
*new* automation safe where the *old* auto-branching was harmful (the difference: gated on
`step.phase == build/land`, never on declaration/intake).

## Open questions for the interview

- **Branch naming**: derive from the REQ id/slug (e.g. `req-010-memzy-converter`)? Config-driven?
  Reuse the REQ-011 config that already names branches?
- **Merge style**: `--no-ff` into the integration branch (matches the manual convention in
  CLAUDE.md)? Who writes the merge commit message / co-author trailer?
- **When does the branch get created** — lazily on the first guarded `build`, or eagerly when
  a REQ's first implementation step becomes eligible?
- **Idempotency / resume**: if the feature branch already exists (partial prior run), reuse it
  rather than erroring. What if it has diverged?
- **Failure & park**: if build/land fails or parks a decision (`DEVSTEWARD_UNATTENDED=1`),
  does the branch stay put for inspection? No auto-merge on a parked/failed step.
- **The ledger's home (REQ-019 Decision 4)**: the cursor advances *on the feature branch* mid-run
  and must reconcile cleanly on merge. Does auto-merge make the "ledger current on `dev` at rest"
  invariant easier or harder? Interaction with `steward checkpoint` ([[REQ-018]]).
- **Does the guard stay?** Presumably the refusal becomes the *fallback* when automation is
  disabled; auto-management is opt-in via config. Or does automation replace the guard entirely?
- **PRs out of scope still?** `dev → main` stays a PR (REQ-019); this is only the feature↔`dev`
  seam. Confirm no PR automation creeps in.

## Dependencies (likely)

REQ-011 (branch governance / config-driven names), REQ-019 (the guard this builds on),
possibly REQ-018 (`steward checkpoint`, ledger reconciliation).
