# THermo onboarding report — REQ-085, 2026-08-02

The second live onboarding (memzy was the first, [REQ-062](2026-08-01-req062-memzy-onboarding-report.md)),
and the first prose-corpus one. This is the observation surface for REQ-085 AC9 and the
decoupled proof for [REQ-086](../requirements/REQ-086.md) AC1.

| | |
|---|---|
| Target | `/home/peter/projects/THermo`, branch `dev` |
| Source SHA (fixtures captured here) | **`e45f4ac`** |
| Onboarding commits | `58f4947` (convert), `1ffdf46` (seed + stamp + CLAUDE.md) |
| Corpus | 28 REQs, all terminal (`done` / `superseded`) |
| Doc layout | singular `doc/` — `doc/requirements`, `doc/plans`, `doc/concepts` (REQ-084 seams) |
| Pushed | **no** — both commits are local on `dev` |

## Every gate, in sequence — none waved through

This is REQ-086 Finding 1's cure observed live, and it is the whole reason that REQ landed first.

| step | gate | result |
|---|---|---|
| 1. convert 28 REQs in place | `steward lint` | **OK** |
| 2. **commit the conversion** (`58f4947`) | working tree clean | clean |
| 3. `steward init` + `steward seed-ledger` (28 terminal) | `steward status` | *all requirements done — nothing to do* |
| 3. (same step) | `steward lint` | **OK** |
| 4. `steward sync` | drift signal | 6 artifacts seeded, then quiet |
| 5. CLAUDE.md reconcile | `steward lint` / `steward status` | **OK** / empty queue |

The gate at step 3 is the one that went red during the memzy run, on a corpus that was
correct. With the conversion committed first it is green, and the operator was never asked to
judge whether a red gate was benign. REQ-086's skill-text assertion is the coupled oracle;
**this row is the decoupled one.**

`steward sync` also seeded `doc/requirements/_templates/req.md` — REQ-086 Finding 2. Under the
old machinery THermo would have received an `/intake` skill referencing a file it did not
have, and its next intake would have broken. It landed at the **configured** `doc/` path, not
under an assumed `docs/`.

## What the converter reported

### Title conflicts — all 11, header wins (REQ-017 Decision 5)

The index rows were systematically the shorter, more editorial wording. Every rewrite below
was reviewed and accepted: in each case the REQ file's header is the more precise statement,
and none changes what the requirement means.

| REQ | index row (replaced) | REQ header (kept) |
|-----|----------------------|-------------------|
| REQ-002 | Message & MessageQueue (thread-safe) | Message and MessageQueue (thread-safe) |
| REQ-011 | Python CLI tool (thermoctl) | Python CLI tool for device deployment and maintenance |
| REQ-014 | Fix lock-order deadlock MqttRouter ↔ esp-mqtt API lock | Fix lock-order deadlock between MqttRouter and esp-mqtt API lock |
| REQ-017 | Actuator cycle planner: underflow fix + saturation semantics | Actuator cycle planner — fix unsigned underflow and define saturation semantics |
| REQ-018 | Move status reporting out of timer daemon task | Move status reporting out of the FreeRTOS timer daemon task |
| REQ-020 | Handle MQTT messages larger than RX buffer (fragmentation) | Handle MQTT messages larger than the RX buffer (fragmented events) |
| REQ-021 | Enable OTA rollback (pending-verify actually active) | Enable OTA rollback (app rollback + pending-verify actually active) |
| REQ-022 | Input validation & multi-room UI fixes (iTime NaN, encoder fan-out) | Input validation and multi-room UI fixes (iTime=0 NaN, encoder target fan-out) |
| REQ-026 | Fleet management CLI (thermoctl v2): async core, survey & inventory, OTA flash | Fleet management CLI (thermoctl v2) — async core, survey & inventory, OTA flash |
| REQ-027 | Firmware regression suite as `thermoctl test` | Firmware regression suite as `thermoctl test` (supersedes REQ-012) |
| REQ-028 | Rooms-set merge semantics + device routes survive rebuild | Device-level rooms-set must merge, not clobber; device routes must survive a rooms rebuild |

The only one worth a second look is **REQ-028**, where the index wording is genuinely tighter
prose. It was still let stand: Decision 5 exists so the file is primary, and a one-off manual
override during a migration is how the two sources drift apart again.

### `supersedes:` extractions

| edge | encoding |
|------|----------|
| REQ-026 supersedes REQ-011 | banner **and** `(supersedes it)` qualifier — the two agreed |
| REQ-027 supersedes REQ-012 | banner |

This rescues a fact the conversion would otherwise have destroyed: `build_index` regenerates
every row, so the index's `SUPERSEDED (by REQ-026)` annotation is gone. It now lives in
frontmatter, where the linter resolves it.

### Merges, carries, relocations

- **REQ-017** — two `- **Notes:**` bullets merged in source order, both intact.
- **`Depends on:` carrying prose** (ids extracted, raw line preserved verbatim in the body):
  REQ-012 `REQ-026 (was REQ-011, superseded 2026-07-04)`; REQ-026 `REQ-011 (supersedes it)`;
  REQ-027 `REQ-026; exercises REQ-016, REQ-019, …`; REQ-028
  `REQ-003, REQ-008, REQ-009; found by REQ-027's suite on bench device GIMYB`.
  Note the consequence, which the operator should check rather than assume: **every**
  `REQ-NNN` token in such a line becomes a dependency, so REQ-027's `exercises` list and
  REQ-028's `found by` reference are now `depends_on` edges. They are real relations and they
  lint clean; the converter is an archivist and may not adjudicate which kind of relation a
  human meant. The raw line is right there in the body to check against.
- **REQ-025** — an `- **Implementation (2026-08-02):**` block sat *after* the checkbox list,
  where the acceptance transcode would have destroyed it. Moved into `## Notes`. See below.

## A fifth construct, found during the run

REQ-085's intake enumerated four new grammar constructs. The live conversion found a
**fifth**, and it was a silent one: prose following the checkbox list inside an
`Acceptance criteria:` field is destroyed by the transcode, because the core replaces
everything from the heading to the next heading with the generated `yaml acceptance` block.
THermo's REQ-025 — closed the day before, during REQ-085's own intake — had exactly that.

This was a genuine non-destructive-guarantee violation in REQ-017's design, invisible in the
12-REQ census and real in the live corpus. Per REQ-085 Decision 2 a converter defect found
during the run is fixed **in session**, so it was: `split_acceptance_tail` splits the tail off
and `build_body` rehomes it under `## Notes` — the dialect's own home for post-hoc commentary,
so nothing is invented and nothing is lost — and the relocation is reported. The fidelity
sweep in `tests/test_convert_reqs_prose.py` is what caught it and is what pins it.

It is also the clearest possible restatement of REQ-085's own lesson: the corpus moves, and
the answer is a tool that fails legibly rather than a better snapshot.

## Judgement calls made without the operator

The operator was away and authorised deciding-and-logging. These are the calls:

1. **All 11 title rewrites accepted** (see the note on REQ-028 above).
2. **CLAUDE.md merge depth.** The Phase-5 REQ status table (10 rows against a 28-REQ corpus —
   already drifted) was replaced by a pointer to the index ↔ frontmatter pair. The
   "Requirements Management" section's hand-edit workflow (*"set Status to DONE, check the
   boxes, update the index"*) was rewritten to the engine's workflow, because following it
   verbatim is now the false-done hole. The "Migration Status" heading's *"Status is tracked
   here"* was narrowed to the migration **phases**, which it does legitimately track. Kept
   byte-for-byte: every ESP-IDF build/flash/monitor procedure, the hardware-variant table, the
   Kconfig/configuration notes, the architecture and namespace sections, the FreeRTOS task
   model, the fleet tooling section, the Deferred Work checklist, and all Key Technical
   Decisions.
3. **THermo's REQ-001 keeps `kind: spec`.** `infer_kind` types it that way purely because of
   its id; it is an ArduinoJson component REQ, not a north star. Schema-valid, lint-clean,
   functionally inert (lint's north-star rule keys on the **id**, not the kind), and
   correcting it by hand would be authoring, not migrating (Decision 9). THermo has no north
   star; that is THermo's own later act, not this migration's.
4. **`doc/concepts/` was not created.** Nothing needs it until a REQ declares a concept phase,
   and the config seam names it for when one does. Creating an empty directory to look
   complete is the machinery-for-nothing this project subtracts.
5. **Not pushed.** Both commits are local on `dev`, per the operator's instruction.
6. **REQ-017's two corpus-wide test node ids were renamed** (`test_thermo_corpus_*` →
   `test_thermo28_*`) so REQ-085 AC6/AC7 and REQ-017 AC7/AC8 share one oracle each rather than
   duplicating the golden comparison. REQ-017's `test:` strings were updated in the same
   commit; no node id dangles.

## Known and deliberate, carried forward

- **REQ-017 Decision 10 is dormant.** With all 28 REQs terminal, the
  active-REQ-without-test-ids demotion had nothing to fire on. The rule stays in the tool for
  the next prose corpus.
- **Onboarding parameter #2 is retired.** It assumed REQ-011/REQ-012 stayed active; both are
  now `superseded`, so the ordinary empty-queue gate applied.
- The preserved `### REQ-NNN:` header leaves a level-3 heading above the generated level-2
  sections (REQ-017 Decision 4, deliberate).
- No verdict was re-adjudicated, including REQ-025's deferred bench validation and the two
  superseded REQs.

## THermo's next act

`/intake` — the queue is empty and the engine is caught up. THermo's own open items (the
Deferred Work checklist in its CLAUDE.md: Special V1 pin map, BH1750 field test, legacy-tree
removal, hardware verification of the 2026-07-04 refactor chunks, REQ-025's firmware build +
bench) are candidates, but converting them into REQs is THermo's call, not this migration's.
