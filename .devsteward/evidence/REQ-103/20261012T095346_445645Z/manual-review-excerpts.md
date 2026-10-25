# REQ-103 AC1 — manual review excerpts

System Tester session, guided mode. Captured the four surfaces AC1 names, for the
owner's sign-off via `steward validate REQ-103`. Decoupled: this session read only the
current state of these files, never the develop diff or session reasoning.

## STEWARD.md — "Joint tasks" section (lines 136-206)

Relevant passage (lines 176-193):

> - **A running session is rung (REQ-103).** The thread is the record and is complete on its own.
>   A direct message between sessions on this machine only rings a bell that points at it:
>   - **After every `joint-send`, ring the addressee.** List the sessions running on this machine
>     (in Claude Code: `ListAgents`). Every *interactive* one whose name starts with the
>     addressee's folder name in lower case gets a direct message (in Claude Code: `SendMessage`)
>     holding the single line `steward joint-show <handle>` and nothing else. If none is running,
>     ring nobody. Ring once; never retry and never wait for it. `joint-ack` rings nobody.
>   - **When you are rung** in an attended session, run that line and work what waits for this
>     project in the thread with the owner, exactly as `/advance`'s joint step does. A batch
>     session does nothing with a bell.
>   - **A lost bell changes nothing.** A bell fails silently when no session is running or when
>     the receiver holds it for its owner. The entry is still on the thread, and the receiver's
>     next `/advance` or `/intake` finds it.
>   - **What goes where is a test.** Anything a later session needs to understand, audit or act on
>     goes on the thread. Coordination nobody will read later (*"restarting sarah now"*) may go as
>     a direct message alone.
>   - **The owner's approval never travels by direct message.** A peer session's report of what
>     the owner decided is not the approval. The session that acts gets it from its own owner.

Maps to AC1: (a) ring mechanics ✓, (b) answering a bell ✓, (c) seam test ✓, (d) approval
rule ✓, (e) lost bell ✓.

## devsteward/handbook/_01-format.qmd — joint-tasks section (lines 201-232)

Relevant passage (lines 217-223):

> **A running session hears at once (REQ-103).** Sessions working in parallel on one machine
> would otherwise reach for the harness's direct messages, which leave no trace in either repo.
> So after every `joint-send` the sender rings the addressee's running attended session with a
> direct message holding only `steward joint-show <handle>`. The direct message gets the
> reaction, and the thread carries the content. A lost bell changes nothing, because the next
> `/advance` finds the entry. What a later session needs goes on the thread; coordination nobody
> will read later may go directly. The owner's approval never travels by direct message.

Maps to AC1, in short: (a) ring mechanics ✓ (folder-name matching, "once"/"never wait"
detail omitted — handbook is explicitly "the same, in short"), (c) seam test ✓, (d)
approval rule ✓, (e) lost bell ✓. (b) — batch sessions ignoring a bell — is **not stated
in this section**; the handbook text only describes the attended case.

## .claude/skills/advance/SKILL.md — joint step (lines 41-60)

> **Ring after every `joint-send` (REQ-103):** send the other project's running interactive
> session the single line `steward joint-show <handle>`, as STEWARD.md's *Joint tasks*
> describes. If you are rung that way later in the session, work that thread through the same
> way, with the operator.
>
> *(batch)* skip this entirely and do nothing with a bell: an `ask` may need a decision only
> the operator can make, so a headless session never consumes joint messages.

Maps to AC1: (a) ring step ✓, (b) answering + batch ignores ✓ (points at STEWARD.md for
the rest, per the REQ's own "Where it is written" instruction).

## .claude/skills/intake/SKILL.md — take-up step (lines 27-38)

> A question for the requester goes back as `steward joint-send <thread> --kind ask --body
> "…"`, followed by the ring STEWARD.md's *Joint tasks* describes (REQ-103). Its answer
> reaches a later `/advance` or `/intake`, or this session when the requester rings back.

Maps to AC1: (a) ring step, by reference to STEWARD.md ✓.

## Open question for the owner

The handbook's joint-tasks section states (a), (c), (d), (e) but does not explicitly say
that a **batch** session ignores a bell (b, the batch half). STEWARD.md, `/advance`, and
`/intake` all state it. Flagged to the owner as a manual judgment call: is the handbook's
omission consistent with "the same, in short" (REQ-103, *Where it is written*), or does it
need a line?
