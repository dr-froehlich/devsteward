# Ledger lost-update & the decision-recovery dead end — intake brief

- **Date:** 2026-07-03
- **Author:** Claude (Opus 4.8), at Peter's request
- **Purpose:** Food for an intake session. Defines a data-loss defect surfaced in
  FlowSteward, the recovery dead end that made it unrecoverable via any CLI verb, and a
  standing UX complaint about the `steward decision` mechanism — and frames how (and how
  *not*) they relate to the 2026-07-02 process review, so intake can take a comprehensive
  view rather than a per-symptom patch.
- **Evidence base:** FlowSteward ledger (`state.yaml` git history + `events.jsonl`), the
  engine source (`core/ledger.py`, `profiles/req/validate.py`, `cli.py`), and
  `docs/reviews/2026-07-02-process-review.md`.
- **Status:** Not intaken. FlowSteward's ledger was hand-reconciled (commit `089af9a` on
  its `dev`) to unstick the operator; the engine defects below are untouched.

---

## 1. The observed symptom

`steward status` in FlowSteward kept surfacing a parked decision after the operator had
already run the advertised remedy and approved:

```
parked decisions:
  DEC-044 [REQ-069:validate] REQ-069 validation: manual AC AC2 awaits its human oracle —
    run `steward validate REQ-069` attended to record the sign-off.
```

The operator ran `steward validate REQ-069` attended and signed off — twice — and the
decision never cleared. Both the advertised remedy and `steward decision answer` were
dead ends (§3). This is the *tool's* failure, not FlowSteward's, which is why it is
reported here against the engine.

---

## 2. The defect, precisely

There are **two coupled defects**. The first loses data; the second removes every path
back.

### D1 — Lost update: `Ledger.save()` blind-overwrites newer committed state

**What the ledger contract promises.** `state.yaml` is the cursor; `events.jsonl` is the
append-only truth. They must stay consistent.

**What happened (reconstructed from FlowSteward's own history):**

| Time (UTC, 2026-07-02) | Event log | `state.yaml` (committed) |
|---|---|---|
| 08:12:06 | `decision_parked DEC-044` (unattended validate → manual-AC await) | `REQ-069:validate = blocked`, `DEC-044 = open` |
| 12:40:10 | `step_started REQ-069:validate` (attended `steward validate` begins; `start()` sets RUNNING) | (in-memory snapshot of this process taken here) |
| 13:15:21 | `interrupted` | `REQ-069:validate = pending` |
| 13:37:24–25 | `validation ok=true` → `decision_answered DEC-044` → `checkpoint` | commit **`5b574e1`**: `REQ-069:validate = done`, `DEC-044 = answered` ✅ |
| 15:37–19:53 | *(no relevant event)* | commit **`10481c2`** and after: `REQ-069:validate = pending (updated 13:15:21)`, `DEC-044 = open` ❌ |

The land at 13:37 was **correct and committed**. A later `steward` invocation then
re-saved a **stale in-memory ledger snapshot** — carrying the 13:15 interrupt-vintage
values — over the newer committed state, silently rewinding the cursor to *pre-land*. The
append-only `events.jsonl` kept the truth, so `state.yaml` and the event log **diverged**,
and REQ-069's frontmatter (`done`) no longer agreed with its cursor entry (`pending`).

**Root cause.** `Ledger.save()` (`core/ledger.py:82`) is a blind whole-file write of an
in-memory dict. There is **no reload-before-save, no version/sequence guard, and no
mtime check**. Any process holding an older snapshot that saves after a newer commit wins
by last-write. Combined with the fact that the attended validate process is **long-lived**
(it loads the ledger in `start()`, then blocks for the entire interactive session before
its `record()` half saves), a single operator can produce overlapping writers without a
second human ever being involved.

The exact identity of the clobbering invocation is not pinned (candidates: the
12:40-started process persisting late, or an overlapping `steward run`), and it does not
need to be: the *structural* defect — blind save, no concurrency guard — is proven by the
divergence, and any fix must assume overlap can occur.

### D2 — No recovery path once diverged

Once `state.yaml` says `DEC-044 = open` while the REQ is `done`, **no CLI verb can close
it**:

- `steward validate REQ-069` → because the frontmatter is `done`, it routes to
  `revalidate` (`cli.py:706`). Revalidate is non-mutating **by design**: it appends a
  fresh evidence event and never touches decisions or the cursor. So every re-approval
  records evidence and leaves `DEC-044` open. This is the "advertised remedy that does
  nothing."
- `steward decision answer DEC-044` → **refused** (`cli.py:888`): a `:validate` decision
  is redirected back to `steward validate` (the REQ-057 guard against re-parking a
  validation hold). Which loops to the bullet above.

The two remedies point at each other. Unsticking the operator **required hand-editing
`state.yaml`** — the one thing STEWARD.md forbids — because no sanctioned verb exists for
"the ledger's cursor disagrees with its event log; reconcile it."

---

## 3. The `steward decision` UX is a third, related strand

Peter's standing feedback, folded in here because intake should see the whole picture:
he has used `steward decision` only a few times and each time **felt lost as a user**:

1. **Missing context.** `decision list` prints the id, step, and question text — but not
   the surrounding situation (what was tried, what the options mean, what each choice
   would *do*). The operator is handed a question with no briefing.
2. **"Can record an answer text but not a decision."** The `Decision` model *has* an
   `options` field (`core/model.py:89`), but nothing ever populates it — every parked
   decision carries `options: []` — and `decision answer` takes a **free-text string**
   (`cli.py:870`). So the operator cannot *choose* among defined branches; they type prose
   into a box. There is no mechanical link between what they type and what the engine then
   does.
3. **"No useful effect."** Because most parks are either `:validate` holds (refused, §D2)
   or the mechanical go-fix-and-retry states that REQ-056 already ruled should *not* be
   decisions, answering a decision frequently either refuses or flips the step
   `BLOCKED → PENDING` only to re-run and re-park. The verb rarely produces the
   resolution the operator expects.

This is consistent with the doctrine already on record — `[[decisions-are-real-forks-only]]`
(REQ-056) drained the develop-side mechanical parks, and the 2026-07-02 review §1.2 found
only **2 of 34** parked decisions were genuine design forks. The mechanism is now used
almost entirely for things it was *not* designed to resolve, and the UX reflects that
mismatch. Intake should decide whether `steward decision` earns its surface at all, or
should be reshaped into a genuine choose-an-option fork (with context) and nothing else.

---

## 4. Suggested remedies (bias: subtract / question the premise)

Ranked, cheapest-correct first. Intake should treat these as starting points, not a plan.

1. **D1 — a concurrency guard on `save()` (root fix).** Give `state.yaml` a monotonic
   `seq` (or persist mtime at load). On `save()`, if the on-disk `seq` is newer than the
   one this process loaded, **refuse the blind write and reconcile** — reload and re-apply
   this process's specific mutation, rather than overwriting. This turns a silent lost
   update into either a correct merge or a loud, recoverable error. Smallest change that
   makes the divergence impossible; aligns with the append-only event log already being
   the source of truth.
   - *Cheaper variant to consider:* have any long-lived path (`start()` … `record()`)
     `reload()` immediately before its terminal save. Narrower, but only closes the known
     shape, not the class — weigh against the seq-guard.

2. **D2 — a sanctioned reconciliation verb (recovery).** A `done` REQ with an open
   `:validate` decision is *self-evidently* resolvable: the land already happened and is
   in the event log. Provide a path that closes it — e.g. `steward validate` on a `done`
   REQ reconciles any lingering open decision for that step from `latest_validation`, or a
   dedicated `steward reconcile REQ-NNN` that replays the event log into the cursor. This
   is the verb whose absence forced a hand-edit and made "never hand-edit `state.yaml`"
   unenforceable on exactly this failure.

3. **The `steward decision` UX (§3) — reshape or subtract.** Either (a) make it a real
   fork tool — populate `options` at park time, let the operator *select* one, carry the
   context needed to choose, and drive a concrete engine action per option; or (b) accept
   that after REQ-056 there are almost no genuine forks left, and shrink the surface to
   match (list-only + the real verbs). Intake should pick a direction, not both.

Guardrails, from the house principles: prefer the seq-guard over new bookkeeping
machinery; do **not** add a general multi-writer locking subsystem for a single-operator
tool (a `seq` check is not a lock); and question whether `steward decision` should keep
its free-text answer path at all.

---

## 5. Relation to the 2026-07-02 process review

This is **a new discovery**, not a fold-in of an existing proposal — but it touches the
review at three points, and getting the relationship right prevents a mis-scoped intake.

- **New, not previously diagnosed.** The review's static sweep explicitly "found no
  correctness defect in the happy paths" (§3). D1 is a **concurrency-edge data-loss**
  defect — precisely what a happy-path static read cannot surface. The review's proposal
  list (§6) does not cover it.

- **It *contradicts* the review's dismissal of the single-writer concern (§5, last
  bullet).** The review parks multi-writer concurrency as ceremony to revisit only "*if* a
  second contributor ever appears," calling `_reconcile_stranded_running`'s process-shape
  ownership "single-operator-only reasoning." D1 shows the hazard is **temporal, not
  multi-user**: one operator's long-lived process overlapping later invocations already
  fired it. The intake should record that this revises the §5 conclusion.

- **It must NOT be conflated with the §4.6 / §3.3 `_park_red` no-dedupe gap.** Same
  symptom class ("a decision keeps reappearing"), *different mechanism*:
  - §4.6 = `_park_red` mints **multiple genuine** decisions for a repeated red
    (REQ-022 × 5); each is real and each was answered.
  - This defect = **one** decision that **was answered**, whose answer was **lost** by a
    save race.
  The §4.6 dedupe fix (Proposal #2) would do nothing here. Do not let this intake be
  absorbed into that one.

- **It reinforces Proposal #5 / the "never hand-edit `state.yaml`" rule.** The review
  wants to retire even the one sanctioned hand-edit of the ledger. This case shows the
  rule needs a **sanctioned recovery verb** behind it (remedy §4.2), or it is
  unenforceable exactly when the ledger self-inconsistency arises.

- **The §3 UX strand relates to REQ-056 / review §1.2**, not to a defect: it is the
  accumulated evidence that `steward decision` is used almost entirely for non-forks, and
  its interface never matched its one legitimate job.

---

## 6. What intake should weigh (comprehensive framing)

1. Is the correct root fix a `save()` seq-guard, a narrower reload-before-terminal-save,
   or does the long-lived attended-validate shape itself deserve rethinking (does the
   parent process need to hold a mutable ledger across the whole interactive session)?
2. Should recovery be a general `steward reconcile` (event log → cursor) or a targeted
   close-on-`done` inside `validate`? The general one also covers future divergences; the
   targeted one is smaller. Subtraction says start targeted unless a second divergence
   shape is already known.
3. Does `steward decision` survive as a fork tool with real options + context, or shrink
   to list-only? This is a premise question (per `[[decisions-are-real-forks-only]]`),
   not a UX-polish question — answer it before touching the command.
4. One REQ or two? D1 (persistence) and the `decision` UX (§3) are separable; D2 is the
   bridge (recovery is where they meet). Recommend intake decide scope explicitly rather
   than defaulting to a bundle.
