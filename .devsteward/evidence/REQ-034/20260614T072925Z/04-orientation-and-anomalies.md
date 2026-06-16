# REQ-034 — System Tester orientation & anomalies (guided AC6 session)

**Session:** `/system-test REQ-034 --evidence …/20260614T072925Z --guided`
**Date:** 2026-06-14 · **Mode:** guided / attended · inside a Claude session (`CLAUDECODE=1`)

## What AC6 actually asks (the recursion)

REQ-034 *is* the guided-human-validation feature. Its one `manual` AC (AC6) validates the
feature by **using it live on a consumer**: from a plain shell, run `steward validate
REQ-024` on FlowSteward's parked production-cutover and watch the reworked engine behave
per Decisions 1–7 (guided session, engine-recorded verdict, non-frozen pipeline, clean
resume + land, declined-is-reworkable).

So the procedure is driven by **Peter in a plain FlowSteward terminal**, not by this
session — see "Why this session does not run it" below. This session prepares the
surfaces, captures the before-state, guides, and ends; the **engine records Peter's
verdict** (the session never self-certifies — Decision 2).

## Confirmed surfaces (live, before the procedure)

- **Engine under test is the reworked one.** `steward` →
  `/home/peter/projects/devsteward/.venv/bin/steward`, importing `devsteward` from the
  working tree, which is on branch `req-034-human-validation-as-a-guided`. So the
  `steward validate REQ-024` Peter runs *is* the REQ-034 code. (00-engine-identity.txt)
- **FlowSteward REQ-024 is parked at `validate`**, clean tree, on branch
  `req-024-production-cutover`. Prior `manual` AC6 was **declined** 2026-06-13 (DEC-017).
  (01-…-parked-state.txt)

## Anomalies to know before driving (surfaced, not judged)

1. **The existing park is stranded on the FEATURE branch (finding-60 "before").** The
   REQ-024 validation park (4 events) lives only on `req-024-production-cutover`; **dev's
   ledger has zero `REQ-024:validate` events** and dev's cursor is at `REQ-016:validate`.
   HEAD is currently on the feature branch, not dev. This is precisely the pre-rework
   condition Decision 8 fixes — so the first `steward validate REQ-024` run is itself the
   test of whether the reworked engine reconciles a park the old engine stranded.
   (03-park-stranded-on-feature.txt)

2. **dev has NOT advanced past the merge-base.** `req-024` is 5 commits *ahead* of `dev`
   and `dev` carries nothing `req-024` lacks (merge-base = dev tip = 9f1fa77, the REQ-024
   intake). So the "behind-but-merged after dev genuinely advanced" reconcile scenario
   (Decision 5 / AC4) is **not naturally set up**: to exercise the reconcile-from-advanced
   -dev path, dev must first advance (land another eligible REQ) while REQ-024 is pending.
   (02-branch-topology.txt)

3. **dev's ledger cursor (`REQ-016:validate`) is stale** relative to dev's own index
   (REQ-016 reads DONE). This is FlowSteward-internal ledger drift, independent of
   REQ-034, but may shape how cleanly the resume-from-dev lands — flagged so it is not
   mistaken for a REQ-034 defect.

## Why this session does not run `steward validate REQ-024` itself

- AC6 says **"from a plain shell"** — the test is specifically shape (A), the
  shell-launched editor pattern. This session is inside Claude (`CLAUDECODE=1`); the
  bring-up path is *designed to refuse* here (Decision 6). Running it from here would not
  exercise the path under test.
- `steward validate` owns engine bookkeeping (RUNNING, branch reconcile, ledger commits).
  The System Tester never touches state/branches; that is the engine's and the human's to
  drive. So Peter drives it in a plain FlowSteward terminal and the engine records the
  verdict.
