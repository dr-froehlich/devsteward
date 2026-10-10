# Backlog

User needs, in the user's words. This is the level of requirement *above* the REQ: a need
here says what someone wants and why, and a REQ says what must be true and how it is proven.
`/intake` performs the translation between them.

**What an item is.** A need, not a solution. How the need is met is decided at intake or in
a concept phase, never here — an item that names a mechanism has already made a decision
nobody asked it to make.

**Why the handle is not a REQ id.** An id in a table reads as a commitment to build that
thing, in that order. Items carry a short handle instead; a REQ id is allocated when the item
is taken up. This list commits to no order and schedules nothing.

**Where status lives: nowhere.** There is no status column and no "taken up by" column on
purpose. Take-up is recorded once, in the taking-up REQ's `backlog_refs:`, and the owner's
acceptance verdict is recorded in an append-only log — so `steward backlog-list` can derive
the truth and no second copy can drift out of step with it.

**How an item leaves.** `steward backlog-accept <handle>` when the delivered result satisfies
the need; `steward backlog-retire <handle> --reason "…"` when it is no longer wanted. Nothing
is ever deleted — a retirement is a decision, and the next person to have the same idea should
be able to read why.

**When a need is not being worked.** `steward backlog-hold <handle> --reason "…"` records
that the need stands but is deliberately parked — waiting on something the owner names, not
on a session. Taking the item up in a REQ lifts the hold.

**When acceptance is denied.** `steward backlog-deny <handle> --reason "…"` records that a REQ
attempted this need and did not satisfy it. The REQ is unaffected — it closes on its own
verification result — and the item stays open for another REQ to take up, be reprioritized,
or be retired. The stated reason is what stops the next attempt repeating the last one.

**Origin.** `operator` = the owner's own words. `proposed` = a session proposed it and the
owner chose it from alternatives. Items a session derived on its own do not belong here.

| Handle | Need | Origin |
|---|---|---|
| all-projects-one-view | I want to see every DevSteward project on this box in one place: where the steward cursor stands and what git says, without opening each project. | operator |
| needs-me | I want to see at a glance what is waiting on me across all projects: parked decisions, validations to sign off, failed steps. | proposed |
| browse-reqs | I want to browse and read a project's REQs. | operator |
| backlog-review-author | I want to review, author and modify backlog items for any of my projects. | operator |
| backlog-req-trace | I want to see which REQ fulfils which backlog item and whether it succeeded or only attempted, since a REQ can fail to resolve the item. | operator |
| error-resolution | When a step has failed or a validation is red, I want to repeat it or send it back to the previous step from the same place, changing the status, without starting any Claude session. | operator |
| up-when-wanted | I want the dashboard available on this box whenever I want it, in my browser, seeing the same working copies my sessions use. | operator |
| simpler-state-changes | Steward's state changes are overly rigid: recently I had to run a validation I already knew would fail, because I cannot rework without a failed validation. I want only the two moves I actually use: repeat the same step, or go back to the previous step. | operator |
| backlog-commit-ui-changes | From a consumer project: "  - Uncommitted backlog changes. docs/BACKLOG.md is modified and .devsteward/backlog.jsonl (the new verdict log holding your two accepts) is untracked. The ledger is meant to be committed. If they stay dirty, the next checkpoint sweeps them into the next REQ's commit. I can commit them now as their own commit on dev if you say so." The need is to commit backlog changes from the UI in safe way. Safe means: If the operation is accepted and performed it does not disturb a running session or cause issues because of the repo's current state. We only commit to dev in DevSteward. | operator |
| prose-converter-fidelity | Onboarding sarah (2026-09-23) showed that the prose REQ converter still loses or misreads content without saying so. An index split into several phase tables came out with stale duplicate rows, and lint went red. A note written on the Acceptance criteria line itself was dropped silently (REQ-035's '(provisional — confirm during the Phase-1 interview)'). A test file's name in a criterion's prose (tests/test_devices.py) was taken as a runnable test, so an open REQ with nothing runnable was not imported as draft. I want a prose-corpus conversion to either carry everything across faithfully or stop and name what it could not handle, so I never have to find a loss by hand. | proposed |
| joint-project-tasks | Handover between projects works like this: from sarah I ran `steward backlog-add --origin proposed --handle sysadmin-open-0177 "A target set on a zone's thermostat in Home Assistant shows there up to a minute late"`. I want this to become fully automated. My DevSteward projects shall be able to hand over tasks without many manual involvment. Once a joint task has been initiated, a bidirectional communication channel shall remain open until the job has finished, which should be acknowledged from both sides. | operator |

## Acceptance criteria

The owner's conditions of satisfaction, per item, in the owner's own words — what would make
them say "yes, that solves it". These are **not** the REQ's verification criteria: those say
whether the system does what was specified, these say whether what was specified was worth
building. `/intake` authors them here *before* translating the need into a requirement,
because criteria written after the solution is known get quietly bent to fit it.

One `###` heading per handle, then a bullet list. Only headings inside this section are read
as handles.

<!-- Example:

### rapid-verdict
- In under five minutes I can see whether this drive is worth repairing.
- The verdict is understandable without reading a manual.

-->

### all-projects-one-view
- Every folder under my projects directory that has a ledger is shown; folders without a ledger are listed for information as not yet stamped.
- For each project I see the steward status as the CLI reports it, and the git side: branch, clean or dirty, unpushed commits on dev, the gap between dev and main, last commit age, and "no remote" where there is none.
- I do not have to open a project or a shell to know where it stands.

### needs-me
- One glance across all projects tells me what waits on me: parked decisions, validations to sign off, failed steps.

### browse-reqs
- I can open a project's requirements index and read any REQ from it. Read-only: I never edit a REQ here.

### backlog-review-author
- I can read every project's backlog items together with their acceptance criteria.
- I can add an item, reword its need and its acceptance criteria, and change its origin.
- I can give the verdicts: accept, deny with a reason, hold with a reason, retire with a reason.

### backlog-req-trace
- For each item I see which REQ took it up, and whether that REQ succeeded, is still running, or was attempted and denied, with the denial reason.

### error-resolution
- Every state change the CLI offers is available here, and nothing more: what the CLI offers is what the UI shows.
- Making a change never starts a Claude session; the run itself stays a shell command.
- Right after the change the project shows the new state, the same as if I had typed the CLI command.

### up-when-wanted
- One command on this box brings it up and my browser shows it; no docker, no server elsewhere.
- What it shows and changes is the working copy my sessions use, never a copy.

### simpler-state-changes
- I can go back from a pending validation to develop without first running a validation I know will fail.
- The moves are the two I actually use: repeat the same step, or go back to the previous step.
