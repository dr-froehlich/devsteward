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
| non-governed-joint-tasks | The joint-project-task works for DevSteward governed projects only. I want my custom, non-DevSteward governed repository to interact with any of the governed projects in a comparable way. | operator |
| sysadmin-open-0201 | A joint task wakes no one: a session sees a new thread entry only when it runs steward joint-list. Sessions working in parallel on one machine therefore reach for Claude Code's own cross-session messages, which leave no trace in either repository; on 2026-10-12 the requests and answers between system-admin and sarah around REQ-055 (the broker grant, the live check, a worktree that blocked a checkpoint) went partly that way | proposed |
| open-items | Projects generate tasks for me or open items, like obtaining an external input or approval, waiting for an external service, a team discussion. I want to be able to manage the tasks within DevSteward including the dashboard with a project but also a global, overarching scope. Open items shall be created in project e.g. during intake, advance or validate but also outside of these governed phased. Project documents shall be able to reference these open items and Claude sessions be able to efficiently read those references. The items shall be tracked with a simple status. They are commited with the projects. | operator |

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

### joint-project-tasks
- A project creates a demand which requires another project to act on.
- When I tell the target project to "intake the other project's request", it finds it, presents me with the possible candidates and picks up the handover.
- Both projects' Claude Code sessions find the feedback and questions the other has issued to them, and process those automatically.
- What travels between them: requests for action; requests for feedback, information or a decision; information pushed to the other; and the finished-job handshake.
- The communication is kept up until both acknowledge that the activity is finished. Each session determines with me how it judges the job finished: in a develop session, by a successful validation, or something else.
- system-admin can participate if it obeys the rules; the main scope is DevSteward projects.

### non-governed-joint-tasks
- system-admin creates a demand which requires a governed project to act on, and a governed project creates one which requires system-admin to act on.
- When I tell system-admin to take up a governed project's request, a command or skill in system-admin stands in for /intake: it finds the request, presents me with the possible candidates and picks up the handover.
- system-admin's sessions find the feedback and questions a governed project has issued to them and process those automatically, through a command or skill that stands in for /advance. The governed project's sessions do the same with what system-admin issued to them.
- What travels between them is what travels between governed projects: requests for action; requests for feedback, information or a decision; information pushed to the other; and the finished-job handshake. The communication is kept up until both acknowledge that the activity is finished.
- For the governed project it makes no difference that the other side is system-admin: nothing in how it uses the steward tool changes, and no target project has to learn how to deal with system-admin.
- On the system-admin side we are flexible to accommodate what the others need.

### sysadmin-open-0201
- Sessions working in parallel get each other's reaction without my carrying anything between them: direct messaging gets the reaction, the DevSteward thread carries the content.
- What a later session needs to understand, audit or act on is on record in the repositories. Only coordination nobody will read later may travel by direct message alone.
- My approval never travels by direct message. A peer's report of what I decided is not my approval.
- Nothing depends on both sessions running on one machine: the thread stays the general path that can later reach other machines over ssh.
- STEWARD.md states how a joint-task message reaches a running session, and where the seam between a direct message and a thread entry lies.
