# FINDING (hard) — a live-host `manual` AC has no deploy channel during the validate phase

Surfaced live during the REQ-034 dogfood run, using **FlowSteward REQ-024** ("production
cutover") as the validation subject. REQ-024's **AC6** is a cross-machine manual oracle:
*deploy the stack on the homelab and verify it serves*. It cannot be satisfied through any
sanctioned channel while the REQ is in the validate phase. This is **not** a REQ-034
defect (REQ-034 is about ledger travel — where the validation bookkeeping lives, Decision
8); it is a distinct gap about **artifact travel** — how a deployable implementation crosses
a machine boundary so a human can validate it. It spawns its **own new REQ** (the
finding-50 → REQ-036 precedent).

## What is true (facts from the live run)

- REQ-024's entire implementation — `docker-compose.prod.yml`, the grown
  `docker-compose.yml` (**4036 B** on the branch vs **1234 B** on the homelab checkout),
  the README runbook, commit `65aa0e1` onward — lives on **exactly one ref**:
  the local branch `req-024-production-cutover`. `git branch -a --contains 65aa0e1`
  returns that branch and nothing else.
- It is on **neither `dev`/`main` nor any `origin/*` ref**. `docker-compose.prod.yml` is
  **absent** on `dev`, `main`, `origin/dev`, `origin/main`. The feature branch was never
  pushed — there is no `remotes/origin/req-024-production-cutover`.
- The homelab (`/opt/flowsteward`) can only `git pull` **`origin/dev`** (tip `9f1fa77` =
  "REQ-024: intake") or `origin/main`. `origin/dev` carries the **declaration only** — the
  REQ frontmatter, index row, roadmap — exactly as the branching model prescribes:
  *"Declaration lives on dev; only implementation branches."*
- The homelab checkout therefore reads `docker-compose.yml` at 1234 B and **no overlay**.
  This looked at first like a stale checkout / operator error. It is not: the deployable
  artifact has **never been published to anything the deploy host can reach**.

## The gap, precisely (chicken-and-egg)

- **AC4/AC5** (mechanical `artifact` oracles) are fine — they run **in place** on the
  validating box against the working tree. No machine boundary, no deploy channel. Passed.
- **AC6** is the one that crosses a machine boundary. The only clean deployment channel is
  **`git pull` of a published integration ref** — a manual `scp`/copy drags gitignored
  `.env`/config/artifacts and breaks clean-deploy hygiene, so it is not deployment.
- But under the branching model the artifact reaches a **pullable ref only after the land**
  (feature → `dev` merge), and **land comes after validation**. So the live-host AC
  presupposes a publish step the workflow defers **until after the live-host AC passes**.
  The phase that could make AC6 deployable is the phase AC6 is meant to precede.

## The proof is in the authority boundary

The unblock would be to **push the feature branch** (then `git fetch` it on the homelab)
or **merge to `dev` and pull that** — but both are **land-phase actions** (push / branch /
merge), and the System Tester is explicitly barred from committing, branching, or pushing.
The phase that could make AC6 deployable is the phase AC6 is supposed to precede. The
boundary that keeps validation honest is the same boundary that makes the gap visible.

## Two corrections to the obvious framings

1. **"Your checkout is stale" is wrong.** `origin/dev` is not behind by operator error —
   the artifact is *correctly withheld* because the validation that gates its publish has
   not passed. That is the V-model working, not a sync bug.
2. **"dev is done ⇒ dev must be the deployable one" overshoots.** REQ-024 is **not done**;
   it is mid-validate. The deployable version *should eventually* be on `dev`, but during
   validate it legitimately is not yet. The defect is narrower than "the model is broken."

## Root gap

DevSteward's validate phase has **no publish-for-validation hop**, and it conflates the
*validation environment* with the *production deploy target* (no staging concept). A
`manual` AC whose observation surface is on another host has no sanctioned way to receive
the implementation before land.

The premise that *creates* the chicken-and-egg is **"deployment must be `git pull` of a
ref."** The normal CD pattern is **build once, promote the artifact**. If the validate
phase *emits* a deployable RC (`git archive` of tracked files only — no `.git`, no
gitignored cruft — or a built image to a registry) and ships **that** cross-host, the
artifact travels **without** any ref being published early, and the ordering tension
dissolves. Candidate resolutions for the new REQ's design interview:

- **A (leaning) — artifact-export.** Validate produces a clean RC and ships it cross-host.
  Doesn't bend the branching model; matches real promote-the-artifact CD.
- **B — publish-for-validation ref.** Push the feature branch / an `rc-NNN` ref to
  `origin` so the host can `git fetch` it. Relaxes "feature branches stay local"; an
  unvalidated ref lives on `origin`.
- **C — beta-stage validation.** Land-as-beta (`vX.Y.Z-beta.N`, already allowed on `dev`),
  deploy the beta, validate it. Inverts validate/land for live-host ACs.

## ACs / scope touched

- REQ-024 AC6 (live homelab cutover) — unsatisfiable through the sanctioned channel during
  validate; blocked here, not by operator error.
- REQ-030 / REQ-034 validate model — no provision for a `manual` AC whose surface is on a
  separate machine. The in-place artifact path (AC4/AC5) is unaffected.
- Branching model ("declaration on dev; only implementation branches") — the constraint is
  correct; the missing piece is an artifact channel that respects it.

## Disposition

Routed (Peter, 2026-06-14): **its own new REQ + a design interview**, leaning **A**
(artifact-export). Intake on `dev` per the branching model — not from this feature branch.
FlowSteward's REQ-024 run drops its own `req024-ac6-deploy-channel-gap.txt`; this file is
the DevSteward-side capture so the dogfood run self-documents.

## Verdict authorship

None asserted. Reviewable evidence only; the design adjudication belongs to the new REQ's
intake interview.
