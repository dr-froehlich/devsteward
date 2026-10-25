# Plan 0011 — Process repositioning: interactive-first, one verified session, free landings

- **Date:** 2026-06-10
- **Source:** [Strategic assessment — process shape and token economics](../reports/2026-06-10-strategic-assessment-process-and-token-economics.md)
- **Status:** roadmap — each step below is fleshed out, planned, and implemented in its
  own interactive session.

## Direction (one sentence)

Keep the registry, the lint, the ledger, and the teeth; collapse the cognition into one
verified `develop` session plus one independent `validate` session; let the engine do
landings for free — and make the headless Autobahn the special case, not the method.

## Adopted decisions (the report's §7, settled)

These are fixed now so the flesh-out sessions don't re-litigate them. Revisit only if an
implementation session surfaces a contradiction.

| Decision | Resolution |
|----------|------------|
| Default driving mode in the handbook | **Interactive-first.** The engine is the verifying bookkeeper always, a driver only when chosen. `steward run` is repositioned as the overnight batch lane for queues of well-specified, low-fork REQs. |
| Re-run policy for validation evidence | **Both cheap mitigations:** `steward validate REQ-NNN` as an on-demand re-run that appends a fresh evidence event, plus a human decision at the release gate (dev → main PR) for REQs whose `check: artifact` touches surfaces the release changes. No auto-staleness detection. |
| Repair-session budget | **2** engine-spawned repair attempts on a red gate, then the step parks for a human. |
| Model policy | Opus-high for `develop` and `validate`; **Sonnet for repairs** and any remaining mechanical prompts. Per-step-kind config, overridable. |
| Engine-work origination | New engine REQs should originate from **consumer postmortems** (the REQ-028 pattern). Measure DevSteward by consumer outcomes, not engine feature count. |

## How this migration itself is driven

**Interactively, not by `steward run`.** Evolving a broken-ish tool with itself doesn't
guarantee convergence; the parts of DevSteward that are *proven* stay in the loop as
gates, the part under reconstruction (the headless driver) does not:

- Each step = one interactive session: review/flesh out the REQ (intake-quality
  interrogation, agree the acceptance block), write the plan in `docs/plans/`, implement
  on a feature branch, merge to `dev`.
- `steward lint` and `python -m pytest` (full suite — REQ-028 semantics) gate every
  merge, run by hand. These are the already-trusted substrate.
- Ledger bookkeeping for these REQs is done via `steward checkpoint` once REQ-018 lands;
  before that, the ledger is simply not advanced for interactively-driven REQs (the REQ
  frontmatter + index row remain the source of truth, as for all pre-ledger work).
- `steward run` is not used again until the new phase model exists and has driven at
  least one trivial REQ green end-to-end.

## The migration path

Work the steps in order; each maps the report's §6 sequence onto a concrete REQ. Feed
the **assessment report** and **this plan** as context into each flesh-out session.

### Step 1 — Land REQ-027 as amended (acceptance taxonomy + intake rewrite)

- REQ-027 is already fully specced; it has been amended so intake also records the
  **fused-vs-split** develop decision alongside the concept-phase and lab declarations.
- This is the seed everything else routes on: the `check:` field is the routing key for
  the System-Test phase (step 4).
- Session: plan + implement (lint enum, intake skill rewrite, handbook taxonomy chapter).

### Step 2 — REQ-029: phase-model rework (develop fusion, mechanical land, repair-on-red)

- Fuse design+build into one `develop` step (the plan artifact in `docs/plans/` survives
  as an in-session discipline, not a session boundary). On green, the engine lands
  mechanically — status flip, index sync, one commit, branch merge (REQ-020 machinery),
  **zero Claude tokens**. On red, a bounded repair session (budget 2, Sonnet).
- Do this **before** the System-Test phase so that phase plugs into the final step model.
- Touches `profiles/req/source.py` and the executor loop; per-step-kind model/effort
  config lands here.

### Step 3 — REQ-018 (revised): interactive-first bookkeeping

- `steward checkpoint` becomes the single **committer-verifier** for interactive work:
  it runs the same REQ-028-toothed gate as a batch land, and on green performs the same
  mechanical bookkeeping (shared code with REQ-029's land). Provenance records *who
  drove*; the engine certifies in both modes.
- The handbook flips to interactive-first here; `/advance` ends with `steward checkpoint`.
- After this step, the migration's own remaining REQs get proper ledger records again.

### Step 4 — REQ-030: System-Test phase + System Tester skill

- Conditional on `artifact|manual` ACs (REQ-027's routing key). A **fresh session** that
  never sees develop's diff consumes only the lab's pass/fail signal and records
  **evidence**: ledger event + captured artifact + `verified_by` entry. `manual` checks
  are a decision stop. Includes `steward validate REQ-NNN` (adopted re-run policy above).

### Step 5 — REQ-031: the first lab (IMAP) + FlowSteward re-drive

- The dedicated IMAP test server as an owned, versioned fixture with documented,
  reality-derived provenance. FlowSteward becomes the proving ground again: re-drive its
  REQ-003a/006/007 surface through the new validate phase — the live-socket proof is the
  first real evidence event.

### Step 6 — Re-earn batch mode

- Not a REQ yet. Once steps 1–5 are merged, pick a small queue of well-specified REQs
  (consumer side, e.g. FlowSteward mid-tail) and run `steward run` overnight under the
  new model. Postmortem the run; cut engine REQs only from what it surfaces.

## Recommendation → artifact map

| Report recommendation | Where it lands |
|---|---|
| §6.1 taxonomy + intake (incl. fused/split + concept declarations) | REQ-027 (amended) |
| §6.2 develop fusion, mechanical land, repair-on-red, model policy | REQ-029 |
| §6.3 interactive-first bookkeeping, handbook repositioning | REQ-018 (revised) |
| §6.4 System-Test phase, evidence events, re-run policy | REQ-030 |
| §6.5 IMAP lab, FlowSteward re-drive | REQ-031 |
| §5.3 postmortem-driven engine work | Standing rule (this plan + handbook, via REQ-018's handbook pass) |

## Done when

- All five REQs are `done` with green REQ-028-semantics gates.
- The handbook describes interactive-first with batch as the earned option, and the
  taxonomy/V-model mapping.
- One overnight batch run under the new model has completed and been postmortemed
  (step 6) — that postmortem, not this plan, decides what comes next.
