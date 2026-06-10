# Strategic assessment — DevSteward's process shape and token economics

- **Date:** 2026-06-10
- **Author:** Claude (Fable 5), at Peter's request
- **Audience:** Peter, and subsequent Opus sessions working on DevSteward (feed this file
  as context when cutting the follow-on REQs)
- **Evidence base:** FlowSteward ledger + postmortems (`flowsteward/docs/postmortems/`),
  DevSteward's own ledger, the ExamEngineer requirements corpus (81 REQs,
  `examengineer/docs/requirements/`), REQ-027 (draft), REQ-028 (done), the engine source
  (`devsteward/core/claude.py`, `executor.py`), and the stamped `/advance` + `/intake`
  skills.

## Verdict

DevSteward should continue — but repositioned. The durable value the FlowSteward
experiment actually demonstrated is the **verifying substrate**: the REQ registry, lint,
the ledger, marker↔ledger reconciliation, branch discipline, and a mechanical gate that
cannot be talked into green (REQ-028). What the experiment *disconfirmed* is the
three-session-per-REQ headless driver as the default way to work. The phase split
(design / build / land as separate `claude -p` sessions) tripled the fixed cost of every
requirement while two of the three gates verified nothing (marker trust), and none of the
failures in the postmortems would have been prevented by the session boundaries — all of
them are closed by gate semantics (REQ-028) and intake quality + independent validation
(REQ-027 and its follow-ons).

Peter's five proposals are right in substance. The sharpened version:

| # | Proposal | Assessment |
|---|----------|------------|
| 1 | Intake delivers non-watered-down validation criteria, agreed interactively, possibly run-once | **Yes — and make "run-once" first-class:** validation is a *recorded evidence event*, not a regression-suite member. This dissolves the skip paradox structurally (see §4.1). |
| 2 | Concept phase decided at intake | **Yes.** Already REQ-027 D6; cheap to honor (it is a declaration plus one optional attended step). |
| 3 | Design + build fused for token efficiency, incl. regression tests | **Yes, as the default.** Keep plan-first *discipline* inside the session (the plan artifact survives); drop the *session boundary*. Opt out per REQ at intake for genuinely risky work. |
| 4 | Separate system-test session only when system criteria exist | **Yes — and the separate session is a correctness feature, not a cost.** Context independence is what decouples the oracle from the builder. |
| 5 | Landing folded into the end of the last phase | **Yes, further than proposed:** on green, landing needs **zero Claude tokens** — it is engine bookkeeping. A land *session* is only ever a repair session, and should be spawned only on red. |

Per-REQ session count goes from 3 + retries to **1 + 0–1 + repairs-only**. That puts
`steward`-driven work at rough cost parity with interactive work while keeping the
guarantees — and the guarantees, not the autonomy, are the product.

---

## 1. What the evidence actually shows

### 1.1 The FlowSteward run, by the numbers

From `.devsteward/events.jsonl` (2026-06-09, one day, 8 small REQs):

- **29 headless `claude -p` sessions**, all Opus at high effort, totalling ~71
  session-minutes. Individual sessions ran 0.5–7 min — i.e. **orientation-dominated**:
  each one cold-starts, reads CLAUDE.md + skill + REQ + ledger + plan + code, does a
  small increment, reports, dies.
- **2 `quota_block` events** — batch marching collides with subscription rate windows in
  a way interactive pacing naturally avoids.
- **4 `step_recover`, 1 `step_failed`, 2 `branch_diverged`** — every retry is a fresh
  full-cost session.
- Of the 29 sessions, roughly **two thirds were design or build checkpoints that the
  engine verified on marker trust** — checkpoints that cost full sessions and guaranteed
  nothing.

DevSteward's own dogfood ledger has the same shape: 28 sessions (12 design / 8 build /
8 land), 2 usage-limit stops, 3 failures, 5 resets.

### 1.2 The postmortems, reduced to one sentence each

- **REQ-003a:** intake silently rewrote the contract (`.env` → `os.environ`), the
  acceptance suite was green precisely when the behaviour didn't run (skip == pass),
  design/build verified nothing (marker trust), and a failed land was hand-stamped `done`.
- **REQ-006:** a REQ may name any tests it likes, so it certified itself with offline
  tests while the behaviour it existed to prove failed, un-run, in a test no gate ever
  invoked.

**None of these failure modes involve the phase boundaries.** They are (a) gate semantics
— closed by REQ-028 (skip ≠ green, zero-collection ≠ green, full suite at land, project
venv, marker↔ledger lint) — and (b) seed quality and oracle coupling — addressed by
REQ-027 (taxonomy, intake rewrite) and its follow-ons (system-test phase, lab). The
three-session split bought checkpoint granularity that was never load-bearing.

### 1.3 ExamEngineer is the working baseline — read what it actually does

The successful corpus (81 REQs, interactively driven) has two properties DevSteward
should institutionalize rather than replace:

1. **ACs are granular and artifact-bound** — observable behaviours of named, greppable
   things, not abstract claims. (REQ-027 already identifies this.)
2. **Validation is recorded as a dated event, not a permanent suite member.**
   REQ-031's `verified_by` reads: *"65 unit tests; smoke run 2026-04-17 against test
   student 104013 on assignment 35972 — 5 attempts graded correctly…"* That is exactly
   the "run once for this REQ, not as regression" pattern Peter is asking for. It was
   never a process invention — it is how the working process already behaved. DevSteward's
   job is to give it a slot (the System-Test phase), an evidence record (ledger event +
   captured artifact), and teeth (it must be able to fail).

---

## 2. The token-economics question, answered directly

> "Maybe just running the harness has an underlying operational cost which I hoped to
> avoid by the surrounding tooling."

The harness per se is not the cost. A headless `claude -p` session and an interactive
session burn tokens the same way. Three things made `steward run` feel expensive:

1. **Step granularity.** Cost ≈ sessions × (orientation tax + work). For REQs of
   FlowSteward's size, orientation (system prompt, CLAUDE.md, skill, REQ, ledger, plan,
   re-reading the code design just wrote about) dominates the work. Three sessions per
   REQ pays that tax three times, and the design→build handoff forces build to re-ingest
   through the plan file what design already held in context.
2. **No cache reuse across sessions.** Prompt caching works within a session (5-min TTL);
   every fresh `claude -p` re-reads everything cold. An interactive design-then-build
   conversation pays the context once and rides the cache. This is why "should I
   implement here or in a separate session?" is usually answered "here" — the model is
   correctly pricing the handoff.
3. **Uniform Opus-high for every step**, including lands that were mostly bookkeeping,
   and full-session retries on every red.

So the tooling didn't add a hidden surcharge — the *process shape* did. The fix is fewer,
larger, verified sessions, not less tooling. (If a split is ever wanted again, note that
`claude -p --resume <session-id>` can continue one conversation across engine steps —
keeping the cache and the context — which is strictly cheaper than a cold session per
phase. But fusion is simpler and matches how the work actually flows.)

---

## 3. The phase model that fits the evidence

```
intake    interactive, human — the sacred interview (REQ-027's rewrite)
          → REQ + classified ACs (check: regression | artifact | manual)
          → decisions recorded: concept phase? lab assets? fused or split build?
concept   optional, attended — spike / risk buy-down; freeze test specs + lab needs
develop   ONE session: plan (docs/plans) → implement → regression tests written & green
          → engine verifies with REQ-028 teeth (named ACs + full suite, project venv)
          → GREEN: engine lands mechanically — status flip, index sync, one commit,
            branch merge. Zero Claude tokens.
          → RED: engine spawns a bounded *repair* session (this is what "land" really was)
validate  only if the REQ carries artifact/manual ACs — a FRESH session that never saw
          develop's diff; runs lab/system tests; records evidence (ledger event +
          captured artifact + verified_by); manual ACs are a decision stop for Peter
release   human — dev → main PR; optionally re-run validation evidence (see §4.2)
```

Per-REQ Claude sessions: **1** (develop) **+ 0–1** (validate, only when declared)
**+ repairs only on red**. Human gates: intake always, concept when declared, manual ACs
and release when they exist. Machine gates: one verified regression gate (end of
develop), one verified validation gate (validate).

### Why each cut is safe

- **Fusing design+build** loses the mid-REQ review point — but in batch mode no human was
  looking at the design checkpoint anyway, and in interactive mode the human is *in* the
  session. For genuinely risky REQs, intake declares either a concept phase or a split
  with attended design review. Default fused, exception declared while a human is present.
- **Mechanical land** is what REQ-028 already made possible: the verifier is the
  authority, the flip + commit + merge are deterministic engine code. Keeping a Claude
  session there pays Opus to watch pytest run. The repair-on-red session inherits land's
  real historical function (both FlowSteward lands that "failed" were environment
  problems a repair loop would have surfaced immediately).
- **The independent validate session** is the one place a session boundary buys
  correctness: the nine-hollow-REQs failure was code and tests sharing one set of
  hallucinated assumptions. A System Tester that never sees the builder's diff, consuming
  only the lab's pass/fail signal, cannot re-couple the oracle. Spend the orientation tax
  here gladly — it is the cheapest decoupling available.

---

## 4. Two design points to settle while cutting the follow-on REQs

### 4.1 Validation evidence is an event, not a suite member

The REQ-028 skip-tension (a clean checkout must stay green, yet a skip must not satisfy a
gate) dissolves once validation leaves the regression suite entirely:

- The **regression suite** is the always-green floor — deterministic, offline, runs
  everywhere, full-suite-gated at every land. No live test in it, so nothing skips.
- **Validation checks** (`check: artifact|manual`) live in the System-Test phase, run in
  the lab environment (where credentials/servers exist and a skip is therefore a hard
  failure), and produce a **dated evidence record**: ledger event, captured artifact
  (hashable output, the fetched mail, the produced report), `verified_by` entry — the
  ExamEngineer smoke-run pattern, formalized.

This is the precise meaning of "run once for this REQ, not watered down": not weaker
tests, but tests whose obligation is to *prove the behaviour happened*, recorded, rather
than to stay green on every checkout forever.

### 4.2 Evidence rots — decide the re-run policy deliberately

A validation event from June proves nothing about November. Two cheap mitigations, pick
at intake of the System-Test REQ:

- Re-run a REQ's validation evidence at the **release gate** (dev → main PR), at least
  for REQs whose `check: artifact` touches surfaces the release changes; and/or
- `steward validate REQ-NNN` as an on-demand re-run that appends a fresh evidence event.

Do **not** try to auto-detect staleness; declared surface tags or a human decision at
release is enough for a single-developer project.

---

## 5. Strategic repositioning — what DevSteward is *for*

The honest reading of the experiment: for a single developer, **interactive is the
default driving mode and the engine's job is to make interactive work trustworthy** —
then batch mode is an option you earn, not the premise.

1. **The engine is a verifying bookkeeper always, a driver only when chosen.** Today the
   handbook says interactive mode has "no engine guarantees" — that is backwards.
   `steward checkpoint` (the REQ-018 direction) is the right spine: whoever did the
   cognition (interactive session or headless step), the *engine* runs the tests, flips
   the status, syncs the index, makes the one commit, advances the ledger. One bookkeeper,
   two drivers. The false-`done` of REQ-003a is impossible in either mode once the
   bookkeeper is shared.
2. **`steward run` is repositioned as the overnight batch lane** for queues of
   well-specified, low-fork REQs — exactly where its economics work (forks parked, no
   human latency, quota windows burned while Peter sleeps). The FlowSteward data shows
   early-project work is fork- and retry-dense: drive that interactively; batch the
   well-understood mid-tail.
3. **Engine work should originate from consumer postmortems.** DevSteward now has ~28
   REQs about itself versus FlowSteward's 8 about email — the tool is outgrowing its
   consumer. REQ-028 is the model case: a consumer failure, a postmortem, a targeted
   engine fix. Adopt that as the rule and measure DevSteward by consumer outcomes
   (REQs landed per token/hour, defects that escaped to a postmortem), not by engine
   feature count.

---

## 6. Recommended sequence (concrete cuts for the next intakes)

1. **Land REQ-027 as specced** — the `check:` taxonomy, the intake rewrite, the handbook.
   It is the seed everything else routes on. (Add to the intake skill: record the
   fused-vs-split decision and the concept-phase decision explicitly.)
2. **New REQ — phase-model rework:** fuse design+build into one `develop` step (plan
   artifact still required); land becomes engine-mechanical on green; bounded repair
   session on red; per-phase model/effort config (repairs don't need Opus-high). This
   changes the step source (`profiles/req/source.py`) and the executor loop — do it
   *before* the System-Test phase so that phase plugs into the final step model.
3. **New REQ — interactive-first bookkeeping:** finish/confirm `steward checkpoint` as
   the single committer-verifier for interactive mode; update `/advance` and the handbook
   so interactive mode carries the same guarantees as batch.
4. **New REQ — System-Test phase + System Tester skill:** conditional on
   `artifact|manual` ACs; fresh context, never sees develop's diff; consumes the lab's
   pass/fail signal; evidence recorded as ledger event + artifact + `verified_by`;
   `manual` = decision stop. Include the §4.2 re-run policy decision.
5. **New REQ — the first lab (IMAP):** the dedicated IMAP test server as an owned,
   versioned fixture with documented provenance (reality-derived seed corpus). FlowSteward
   becomes the proving ground again: re-drive its REQ-003a/006/007 surface through the
   new validate phase — the live-socket proof is the perfect first evidence event.

## 7. Open decisions for Peter

- **Default driving mode in the handbook:** recommend interactive-first with batch as the
  earned option (my recommendation), or keep batch as the headline?
- **Re-run policy for validation evidence** (§4.2): release-gate re-run, on-demand only,
  or both?
- **Repair-session budget:** how many engine-spawned repair attempts before a step parks
  for a human (suggest 2)?
- **Model policy:** keep Opus-high for develop/validate, drop to Sonnet for repairs and
  any remaining mechanical prompts?

## The one-sentence direction

Keep the registry, the lint, the ledger, and the teeth; collapse the cognition into one
verified session plus one independent validation session; let the engine do landings for
free — and let the headless Autobahn be the special case, not the method.
