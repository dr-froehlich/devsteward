# AC3 seed — a deliberately environment-bound idea to run `/intake` on

This is the test input for REQ-064 AC3. The reviewer runs `/intake` on the idea
below and confirms the §2b environment-binding screen fires and routes the AC
honestly. The idea is constructed to be the FlowSteward REQ-043 specimen shape:
an all-DB-dependent acceptance criterion an author would *naively* file
`check: regression` because "it's just a headless pytest."

## The idea to paste into `/intake`

> I want an acceptance criterion that verifies our user-stats endpoint returns
> correct aggregates. The test is a pytest (`tests/test_user_stats.py`) that opens
> a connection to the lab Postgres — the DB URL is read from a **gitignored `.env`**
> and the test is marked `pg_required` (it `skipif`s when no DB is reachable). It
> runs the stats query and asserts the returned totals equal the expected values.
> I'd file it `check: regression`, since it runs headless in the Build phase.

## Why this is the specimen

- Its oracle needs a **service (Postgres) + a secret (`.env`)** absent from a clean
  repo checkout — so its "green" is environment-bound: present env → pass, absent
  env → silent skip. Exactly the property that discarded a paid-for session in the
  REQ-043 postmortem.
- It is filed `regression` while behaving like a lab/environment-bound oracle —
  the precise mis-classification REQ-064's §2b screen exists to catch.

## What an honest `/intake` must do with it (the pass condition — reviewer's call)

The screen must **fire** (intake must surface that this `regression`'s oracle needs
an absent service/secret/network), and the AC must land in **one** of the two honest
routes — never left a silent environment-bound `regression`:

1. **Decoupled oracle → reclassify `artifact`.** The totals are compared against an
   expected/golden value produced by the live lab DB → it is really `artifact`:
   `check: artifact`, and the REQ owning the Postgres lab asset is named in
   `process.lab`.
2. **Coupled oracle, needs only a runtime → keep `regression` + record env.** If the
   assertion is coupled to the code and merely needs a Postgres runtime, it stays
   `regression` **and** the required environment is written into the REQ prose
   ("required environment: lab Postgres + `.env`").

Either route is acceptable; a silent `check: regression` with no recorded environment
is the **fail**.
