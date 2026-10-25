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
