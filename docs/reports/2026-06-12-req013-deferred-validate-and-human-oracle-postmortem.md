# Postmortem — DevSteward frictions on the validate path of settled REQs

- **Date:** 2026-06-12 (Findings 1–2); 2026-06-13 (Finding 2 third observation, Findings 3–4)
- **Projects:** FlowSteward (`/home/peter/projects/flowsteward`) for Findings 1–2 and 4;
  DevSteward itself for Finding 3.
- **Trigger:** Findings 1–2 — Peter went to record the deferred manual sign-off for
  REQ-013 AC5 (client-surface tag rendering) and hit two reproducible tool frictions.
  Finding 3 — the day after REQ-033 landed, a casual `steward validate REQ-033` on the
  already-`done` REQ silently clobbered its `verified_by` provenance. Finding 4 — walking
  the REQ-018 AC4 cutover sign-off, `steward validate` launched from inside a Claude Code
  session hung with no output and never returned.
- **Severity:** all low (workarounds exist; no data loss) — but all are *process* bugs in
  DevSteward itself, not in the consuming project. Findings 1–2 recur on every deferred
  manual AC; Finding 3 recurs any time a `done` REQ is re-validated; Finding 4 recurs any
  time `steward validate` is run from within a Claude Code session.
- **Status of the consuming work:** REQ-013 AC5 was signed off with a reservation and the
  REQ landed; REQ-033 is done and its `verified_by` was restored. This postmortem is only
  about the tool.

---

## Finding 1 — a deferred `validate` cannot be run later once `dev` advances

### What happened

REQ-013 AC5 is explicitly marked *"Deferrable to the end of the Scenario C run."* Peter
deferred it. In the meantime REQ-015 was developed and merged into `dev` (the integration
branch). When he later ran the deferred sign-off:

```
$ steward validate REQ-013
Error: refusing to reuse feature branch 'req-013-imap-keyword-tagging' — it has
diverged from 'dev' (the integration branch advanced since the branch was cut).
Reconcile it by hand, then re-run.
```

### Why

`REQ-013:validate` is still an **in-flight** step (the REQ is `status: open`; validate is
the step that flips it to `done` and merges). To land the validate step the executor tries
to **reuse the REQ's feature branch** (`req-{num}-{slug}`). But that branch was cut before
REQ-015 merged, so `dev` is now ahead of it — the engine sees divergence and refuses to
reuse, rather than reconciling or cutting fresh.

Repo state at the time (the branch was in fact *fully merged* — `git log dev..branch` was
empty — it was simply behind):

```
req-013-imap-keyword-tagging  13c0f3b   (fully merged into dev, 2 commits behind)
dev                           df658ac
```

### The contradiction

The REQ schema *invites* deferral ("Deferrable to the end of the Scenario C run"), but the
feature-branch lifecycle silently makes deferral impossible the moment any later REQ merges
into `dev` — which is exactly what "the end of the run" guarantees will have happened. The
promise and the mechanism disagree.

### Workaround used

The stale branch was fully merged, so deleting it was safe; the engine then cut a fresh
`req-013-…` from current `dev` and validate proceeded:

```
git branch -D req-013-imap-keyword-tagging   # fully merged; reflog-recoverable
steward validate REQ-013
```

### Recommendation (for a DevSteward session)

For a **deferred / re-run validate of an in-flight REQ**, the engine should not insist on
reusing the original feature branch. Options, in rough order of preference:

1. **Cut the validate land-branch fresh from current `dev`** (the validate commit is just
   the status-flip + `verified_by` + ledger; it has no dependency on the original branch).
2. If the original branch is **fully merged into `dev`**, reconcile automatically (delete +
   re-cut) instead of erroring — the "reconcile by hand" the message asks for is mechanical
   in this case.
3. At minimum, make the error *actionable*: detect the fully-merged case and print the exact
   safe command (`git branch -D …`) rather than the generic "reconcile it by hand."

The general principle DevSteward already holds elsewhere (the engine is the verifying
bookkeeper) argues for option 1: a deferred validate is a first-class, expected path, so the
branch topology for it should be engine-managed, not a manual git chore.

---

## Finding 2 — manual-AC instructions are written at "coding-agent" altitude, not for a human oracle

### What happened

REQ-013 AC5 is a `check: manual` AC whose oracle points at a runbook
(`labs/imap/README.md`, "Tags in your clients"). `steward validate` presents the AC text +
the oracle pointer, then asks `Sign off AC5? [y/N]`. The human is expected to *follow the
runbook* and answer. But the runbook prose was imprecise/incorrect for a human tester:

> Thunderbird (desktop): keywords appear as message tags. Right-click a message → Tag to
> add/remove; the taxonomy names (`werbung`, `wartet_auf_antwort`, …) render as the tag
> labels …

Peter's (correct) objection:

- He should **not** add/remove tags — the test is to **observe** that the tagging run
  already applied them.
- `wartet_auf_antwort` "renders" is false in Thunderbird (see the companion FlowSteward
  finding: Thunderbird only shows a keyword if a tag whose *key* equals that keyword is
  registered locally).
- The runbook never said the one thing a human needs: *"Go to the `DEVSTEWARD-LAB-KW`
  folder, open the seeded messages, and check whether tags are attached."*

In short, the instructions assumed a reader who would figure out the gaps (a coding agent
would). A human oracle needs them to be **idiot-safe**: exact folder, exact messages, exact
observation, exact pass/fail condition — no inference.

### Why this is a DevSteward concern, not just a FlowSteward doc bug

The runbook is FlowSteward's to fix (and it was). But the *systemic* gap is that DevSteward
has no authoring discipline ensuring a `check: manual` AC's referenced procedure is written
for an unassisted human:

- The **intake** skill classifies an AC as `manual` but does not require the procedure to be
  observation-precise (folder / artifact / exact pass condition spelled out).
- The **`steward validate` presentation** shows the AC text + oracle pointer but gives the
  human no structured "here is what to open, here is what you should see, here is the
  pass/fail line" scaffold — it trusts the prose the AC author happened to write.
- The contrast is sharp because the **artifact** path is rigorously specified (a named test
  the engine runs), while the **manual** path degrades to free prose at exactly the moment a
  human — the least context-loaded reader in the system — is the one consuming it.

### Recommendation (for a DevSteward session)

1. **Intake**: when an AC is classified `manual`, require its `test:`/procedure to name the
   concrete observation surface (where to look, which artifact/folder/message) and an
   explicit pass/fail condition — lint it the way other AC fields are linted.
2. **Validate presentation**: have `steward validate` render a manual AC as a short,
   structured checklist (Open → Observe → Pass-if), not just the raw AC sentence + a doc
   pointer. The human should not have to context-switch into a separate doc and reverse-
   engineer which sentences are instructions vs. background.
3. **Authoring guidance / handbook**: add a "writing manual ACs for a human oracle" note —
   the reader has the least context and cannot infer; prefer "observe X in location Y" over
   "X works." Treat the human tester as the idiot-safe target, *more* precise than a coding
   agent would require.

### Second observation (2026-06-13) — REQ-017 AC6: the named procedure, and the surface it needs, were never built

The same failure recurred on FlowSteward **REQ-017 AC6** (search-quality sign-off), and a
side-by-side of the two descriptions makes the gap concrete. The AC's own `test:` reads:

> `manual: run the documented search-quality session (README, 'Search sign-off') against
> real synced mail and sign off`

That is the *entire* instruction the human is handed. Peter's report, going to run it:

> "I have no idea how to bring up a frontend (should that exist), nor how to search for
> 'Lufthansa' nor what I should sync to do that. … I require a detailed step-wise test
> procedure I can follow."

What investigation found (the description a human actually needs, now written into the
README as a six-step "Search sign-off" runbook — start Postgres + migrate → fill account
profiles → `flowsteward sync --all-profiles` + `flowsteward reindex` → create login + start
the page → run the Lufthansa-class cases against Thunderbird → an explicit pass/fail line):

- The AC points at a README section, **`README, 'Search sign-off'`, that did not exist** —
  the oracle pointer dangled. (In Finding 2 the runbook existed but was imprecise; here it
  was absent, a strictly worse version of the same defect.)
- Worse, the **surface the procedure needs did not exist either.** REQ-017's AC1–AC5 were
  all satisfiable through the Django *test client* (AC4) and a lab API golden-compare (AC5),
  neither of which boots a web server. So the product shipped **no `runserver`/`manage.py`
  wiring and no operator-account creation path** outside the test fixtures — there was
  literally no way for a human to open the page the REQ is named after. A local launcher
  (`scripts/serve.py`, with a `create-user` step) had to be written before the sign-off was
  performable at all.

The deeper lesson sharpens recommendation 1: a `manual` AC is not just under-specified prose,
it can name a **deliverable the automated ACs never forced into existence**. When every other
AC on a REQ is reachable by a test harness, the human-facing entrypoint (a runnable UI, the
account to log in with, the runbook that names them) is exactly what slips through — because
nothing in the gate fails without it. This is acute under `steward run`, which builds many
REQs back-to-back with no interim production deliverable: from the human oracle's seat the
project is an **unknown internal state**, and a one-line `test:` pointing at a section that
was never written is the only bridge offered.

Reinforced / added recommendations:

4. **Lint the oracle pointer's referent, not just its presence.** If a `manual` AC's `test:`
   names a doc section (`README, 'Search sign-off'`), `steward lint` should verify that
   anchor *resolves* — a dangling runbook pointer is a red gate, the same class of check as a
   missing test file for an artifact AC.
5. **A `manual` AC must name its operator entrypoint.** When the REQ delivers a human-facing
   surface, intake should require the AC (or its runbook) to state how a human *brings it up*
   — the command to run, the account to use — not assume a coding-agent-grade reader who can
   reconstruct it. If the automated ACs can all pass without that entrypoint existing, that is
   the smell to catch at declaration time.
6. **Surface the "unknown internal state" cost of long headless runs.** When a batch
   (`steward run`) defers several manual ACs to the end, the human returns with zero context.
   The deferred-validate handoff should carry a built-from-scratch "how to exercise this"
   preamble, not just the AC sentence — the reader has been absent for the whole run.

### Third observation (2026-06-13) — REQ-018 AC4: the runbook's first step assumed a deliverable nothing built

The exact pattern of recommendation 5 recurred on FlowSteward **REQ-018 AC4** (the
process-folder cutover sign-off). The AC's `test:` points at a README runbook
(`README, 'Process folders'`); the human follows it on the first real account. Step 1 read
*"confirm the folder names render on every surface (Thunderbird / FairEmail / webmail)."*
Peter, correctly, was stuck: nothing in the runbook had **created** those folders on the
account, so there was nothing to confirm — on a fresh account `Aktion` / `Warten` / `Termin`
/ `Archive` simply weren't there.

Investigation found the same missing-entrypoint shape as REQ-017 AC6:

- The function that creates the process-folder set, `provision()`, existed — but was **only
  ever called from the test harness** (`tests/test_req018_validation.py`). There was **no
  operator-facing `flowsteward provision` command**. The runbook had no provisioning step
  and silently presumed folders already on the server.
- Why the gate never caught it: REQ-018's automated ACs each provision the folders **inside
  their own fixtures** — AC1 (transitions over fakes), AC2 (freeze over a fake account), AC3
  (lab choreography) all call `provision()` against a test/lab sink before exercising the
  workflow. So every automated AC passed while the human-facing path to put the folders on a
  *real* account did not exist. Nothing in the gate fails for a missing operator command when
  every test brings its own folders.

The fix (made in FlowSteward) was to add a `flowsteward provision --profile … [--live]`
command (shadow by default, idempotent) mirroring `freeze`, and to insert it as step 1 of the
runbook before "confirm the names render." This is recommendation 5 almost verbatim, now seen
twice in two consecutive REQs: **when every automated AC carries its own setup, the operator
entrypoint the manual AC depends on is exactly what slips through declaration.** It argues for
making recommendation 5 a lint, not just guidance — a `manual` AC whose runbook names an
action (`provision`, `freeze`, "bring up the page") should be cross-checked against an
operator-invocable command of that name.

---

## Finding 3 — re-validating a `done` REQ silently clobbers its `verified_by` provenance

### What happened

The day after REQ-033 landed, Peter ran `steward validate REQ-033` again — a casual re-check
of a `done` REQ. Per REQ-030 Decision 5 this is a sanctioned path: a done REQ's re-validation
records fresh evidence and **leaves status untouched** (the CLI even prints *"fresh evidence
recorded for REQ-033 (status untouched)."*). But it also silently **overwrote the REQ's
`verified_by` field** with the new sign-off note:

```
- verified_by: "… AC4 signed off by Peter Froehlich — reworked FlowSteward's REQ-012; …"
+ verified_by: "… AC4 signed off by Peter Froehlich — was already validated, nothing changed; …"
```

The original note recorded the *true provenance* — that AC4's live case (FlowSteward REQ-012
driven red → `rework` → green → land) was actually carried out. The re-run, a no-op poke,
downgraded it to a hollow line. No prompt, no warning, no indication that a `done` REQ's
durable record was being rewritten.

### Why

`steward validate` writes `verified_by` from the latest validation event unconditionally. The
status guard (REQ-030 D5) protects `status:` but not the sibling `verified_by:` field — so the
"status untouched" promise the CLI prints is only half true: the *cursor* is untouched, but the
REQ file's provenance line is rewritten in place.

### The contradiction

REQ-030 D5 invites re-validation of a done REQ as a safe, non-mutating check ("status
untouched"), but the mechanism mutates the one field that records *why* the REQ is trusted —
and replaces a meaningful note with whatever the re-run happened to say. A path advertised as
read-only-to-status is destructive to provenance.

### Workaround used

The clobber was uncommitted, so it was reverted (`git checkout -- docs/requirements/REQ-033.md
.devsteward/events.jsonl`), restoring the true 2026-06-12 note and dropping the hollow
re-validation event.

### Recommendation (for a DevSteward session)

1. **On a `done` REQ, do not rewrite `verified_by` in place.** Either leave it untouched
   (matching the "status untouched" contract) or *append* the re-validation as a dated line,
   never replace the original provenance.
2. If the field is updated at all on a done re-validation, **require a non-trivial sign-off
   scope** (reject empty / "nothing changed" notes from overwriting a substantive one), or
   warn that an existing `verified_by` will be replaced and confirm.
3. Make the CLI message honest: if `verified_by` is rewritten, "status untouched" should read
   "status untouched; verified_by updated" so the operator knows a durable field moved.

This is a sibling to Finding 1: both are the **validate path doing something surprising on an
already-settled REQ** — Finding 1 erroring on a merged branch, Finding 3 mutating provenance
the operator believed was frozen.

---

## Finding 4 — `steward validate` from inside a Claude Code session forks the live session and wedges

### What happened

Recording the REQ-018 AC4 sign-off, Peter ran `steward validate REQ-018` in a terminal that
was **inside a Claude Code session** (`CLAUDECODE=1` in the environment). The command produced
no output and never returned the shell prompt. It was not slow — it was wedged, and stayed
wedged across re-runs ("now stale").

The validate flow reached step 1 of `_validate` — the fresh System-Tester session that preps
the lab and captures evidence for the one **artifact** AC (AC3, the live lab choreography). To
run that session the engine spawned `claude`. But instead of a clean headless `claude -p`, the
spawned process was:

```
claude --session-id <new> --fork-session \
       --resume …/<ambient-session>.jsonl --effort medium --permission-mode default
```

— a **fork-and-resume of the ambient interactive session**, not a fresh one. That child
daemonized (`claude daemon run`), grabbed the controlling terminal's pty (`--bg-pty-host`),
did nothing (empty evidence dir; a 2-line `ai-title`/`agent-name` transcript stub), and was
orphaned to `init` when the foreground `steward validate` exited. The dead command left a live
background daemon holding the TTY — hence "no output, no prompt." Recovery required manually
killing the orphan tree (`kill <daemon-pid> …`; one pty-host needed `kill -9`).

### Why

The System-Tester spawn does not isolate its child `claude` from an ambient Claude Code
session. When `CLAUDECODE=1` / `CLAUDE_CODE_SESSION_ID` / `CLAUDE_CODE_*` are present in the
environment, the `claude` the engine launches resolves to a **fork+resume of the current
session** rather than a new headless run — so the System Tester is not the "fresh, diff-free"
session Decision 2 promises; it is a clone of the operator's session that then detaches and
dies. Two corroborating tells in the orphan's argv:

- `--fork-session --resume <ambient>.jsonl` — it inherited the live session, the opposite of
  a fresh tester.
- `--permission-mode default` — the project's configured `claude.permission_mode:
  dangerously-skip` (`.devsteward/config.yaml`) **did not reach the child**. A headless tester
  with `default` permissions cannot act autonomously anyway, compounding the wedge.

### The contradiction

Decision 2 specifies the System Tester as a **fresh session that never sees the builder's
diff**. Run from inside a Claude session, the spawn delivers the exact opposite — a fork of the
operator's own loaded session — and on top of that drops the configured permission mode. The
isolation the design depends on is silently lost precisely in the common case where an operator
is already working inside Claude Code.

### Workaround used

Kill the orphaned daemon/session tree, then run `steward validate REQ-018` from a **plain login
shell outside any Claude Code session** (`echo $CLAUDECODE` prints nothing). The System Tester
then spawns clean, captures AC3 evidence, the engine re-runs AC3 green, and the AC4 sign-off
prompt finally appears. AC3 was independently confirmed green by running its test directly
(`pytest …::test_lab_workflow_choreography`, live lab, 6.85 s) — proving the wedge was purely
the spawn, not the test or the product.

### Recommendation (for a DevSteward session)

1. **Scrub the ambient Claude env from the System-Tester child.** Before spawning, drop
   `CLAUDECODE`, `CLAUDE_CODE_*`, `CLAUDE_CODE_SESSION_ID`, `CLAUDE_CODE_CHILD_SESSION` (and
   any `--resume`/`--fork-session` inheritance) from the child environment so the tester is a
   genuinely fresh `claude -p`, as Decision 2 requires — never a fork of the caller's session.
2. **Guarantee the configured permission mode reaches the child.** The orphan ran
   `--permission-mode default` despite `config.yaml` saying `dangerously-skip`; the spawn must
   pass the resolved `claude.permission_mode` explicitly.
3. **Fail fast on nesting instead of hanging.** At `steward validate` (and `run`) startup,
   detect `CLAUDECODE=1` and either (a) auto-scrub per rec 1, or (b) refuse with an actionable
   message — *"do not run `steward validate` from inside a Claude Code session; open a plain
   shell"* — rather than silently spawning a session that daemonizes, captures the pty, and
   dies. A wedged pty with no output is the worst possible failure mode for an interactive
   command.

This compounds Finding 2's lesson from the *tooling* side: even once a manual AC's runbook is
human-precise, the operator still cannot reach the sign-off prompt if the validate entrypoint
itself wedges. Both halves — the procedure and the machinery that presents it — have to work
for a human oracle to function.

---

## One-line summary for triage

DevSteward should (1) treat a **deferred validate** as an engine-managed, fresh-branch path
instead of erroring on a stale-but-merged feature branch, (2) hold **manual ACs** to the same
precision bar as artifact ACs — observation-precise, idiot-safe procedures that name their
operator entrypoint (and lint that a runbook action like `provision`/`freeze` maps to a real
command — seen missing twice, REQ-017 AC6 and REQ-018 AC4), surfaced as a structured checklist
at sign-off time, (3) stop a **done-REQ re-validation** from silently clobbering `verified_by`
— honor the "status untouched" promise for provenance too (leave or append, never replace), and
(4) **isolate the System-Tester spawn from an ambient Claude Code session** — scrub
`CLAUDE_CODE_*`/`CLAUDECODE` and never fork+resume the caller's session, pass the configured
permission mode through, and fail fast (not hang on a captured pty) when run from inside Claude.
