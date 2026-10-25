# Surface under test — the §2b environment-binding screen (live in the repo `/intake` skill)

Captured from `.claude/skills/intake/SKILL.md` (the authoring surface AC3 exercises),
§2b "Classify every criterion: `check:`", lines 79–97. This is the screen that must
**fire** when the reviewer runs `/intake` on `seed-idea.md`.

> **Environment-bound `regression` — the silent-skip trap (REQ-064):** screen **every**
> `check: regression` criterion with one question — *does its oracle need a service, secret,
> or network that is **not** present in a clean repo checkout?* (a database, a `.env`, a
> running service). If yes, its "green" silently rides hidden environment: the same test that
> passes with that environment present **skips** without it, so the green is *environment-bound*,
> not self-contained — the exact shape that discarded a whole session in the FlowSteward
> REQ-043 postmortem (an all-`pg_required` AC, filed `regression`, whose green rode a gitignored
> `.env`). Do **not** leave it a silent `regression`; route by **oracle coupling** (§2a):
>
> - the oracle is **decoupled** (a live service / golden output the test compares against) → it
>   is really an `artifact`: reclassify it `check: artifact` and name the REQ that owns the lab
>   asset in `process.lab`.
> - the oracle is **coupled** to the code and only needs a **runtime** present → keep it
>   `regression`, but **record the required environment** in the REQ prose (Context/Notes —
>   "required environment: …") so the batch lane / operator wires it up.
>
> This does not *forbid* an environment-bound `regression` — the engine tolerates such a skip at
> land (REQ-063) — it makes the author's choice **deliberate**, never a silent default that only
> surfaces when a paid-for session is lost.

Presence of this section is the AC1 (`regression`, engine-run) proof; AC3 (`manual`) is the
**behavioural** proof that the section, when applied by a human running `/intake` on the seed,
actually changes how the AC is classified.


## Verbatim Screen copy from manual validation testing:

 ☐ Oracle route

The §2b screen fired on this AC: its `regression` oracle needs an absent service (lab Postgres) + secret (`.env`), so its green is
environment-bound. To route it honestly I need the oracle coupling. What decides pass/fail — i.e. where do the 'expected values' the test
asserts against come from?

 1. Decoupled golden →            ┌──────────────────────────────────────────────────────────────┐
   artifact                       │ check: regression                                            │
❯ 2. Coupled, runtime-only →      │ Notes                                                        │
    regression + record env       │                                                              │
                                  │ required environment: lab Postgres + .env                    │
                                  │ (DATABASE_URL); seed fixture loaded. Without it              │
                                  │ this AC skips — green is environment-bound.                  │
                                  └──────────────────────────────────────────────────────────────┘

                                  Notes: press n to add notes
