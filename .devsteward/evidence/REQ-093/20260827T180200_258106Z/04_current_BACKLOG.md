# Backlog

Seeded by [REQ-016](requirements/REQ-016.md)'s concept paper
([`concepts/REQ-016.md`](concepts/REQ-016.md)) and **living** — the paper stays what it was
on the day it was approved, this list stays current.

**What an item is.** A user need, in the operator's words. Not a solution: how the need is
met is decided at intake or in a concept phase, never here (REQ-016 Decision 3). An item
that names a mechanism has already made a decision nobody asked it to make.

**Why the handle is not a REQ id.** An id in a table reads as a commitment to build that
thing, in that order. Items carry a short handle instead; an id is allocated when the item
is taken up at intake. This list commits to no order and schedules nothing.

**Where status lives: nowhere.** There is no status column and no *Taken up by* column any
more (DevSteward REQ-093). Take-up is recorded once, in the taking-up REQ's `backlog_refs:`,
and the operator's verdict once, in the append-only `.devsteward/backlog.jsonl` — so
`steward backlog-list` derives the truth and no second copy can drift. **Origin** is
`operator` (the operator's own words) or `proposed` (a session proposed it and the operator
chose it from alternatives).

**How an item leaves.** `steward backlog-accept <handle>` when the delivered result satisfies
the need, `steward backlog-retire <handle> --reason "…"` when it is no longer wanted, and
`steward backlog-hold <handle> --reason "…"` when it stands but is deliberately not being
worked. `steward backlog-deny <handle> --reason "…"` records that a REQ attempted the need
and did not satisfy it: the REQ is unaffected and the item stays open. Nothing is ever
deleted — the reasons stay readable.

| Handle | Need | Origin |
|---|---|---|
| boot-to-menu | The tool autostarts when booted from a stick into a user menu; the user can choose options. | operator |
| graphical-first | The tool starts into a graphical environment, with fallbacks to terminal graphics, and then to CLI. | operator |
| hidpi-readable | On high resolution screens text is readable. | operator |
| auto-smart-refresh | The default operation is a fully automatic smart refresh, which improves the drive's read performance based on measurements before and after, with a target to achieve the best possible read performance for that particular drive across the mapped part of the drive and within safe operating parameters. | operator |
| full-rewrite-option | There shall be a full rewrite option as manual user choice. | operator |
| performance-dashboard | There is a graphic (fallback text graphic, fallback prompt) performance visualization for the drive's status, illustrating the drive's read performance across its space, KPIs and health data. The information on the dashboard allows absolute performance comparison between before and after, between multiple drives, or between current and historic drive scans. | operator |
| capture-compare | Two drive state captures can be compared relative to each other. | operator |
| live-dashboard | The dashboard is live during the refresh operation → fallback before and after → fallback visualization prepared on the stick (likely as a web page) for review on another PC → fallback the data on the stick is fed to an external tool for creating the visualization. | operator |
| session-record-on-stick | The stick contains a complete and machine readable record of every session run (if not erased by the user); the user can copy the content to a folder on a PC for persistence, for feeding into a management tool. | operator |
| history-manager | There is a management tool or view which allows browsing historic sessions on multiple devices, bringing up their respective dashboards, and a relative comparison between two captures. | operator |
| drive-recognised | A drive is recognised as the same drive when it comes back, across runs and across machines, without the operator managing it. | operator |
| rewrite-response-health | Part of the drive's health assessment is its response to rewriting: a healthy drive is expected to achieve "crisp" read performance. If read times don't go back to that level, or not for all cells, or only after several attempts, that could be an indication of true cell wear or overutilization. The exact model has to be worked out during application of the tool. | operator |
| drive-true-parameters | A drive's true parameters are determined during probing and/or the refresh process itself. Parameters could be: cache-miss optimal read times, cache-hit typical read times, flash page size. | operator |
| rapid-verdict | In a few minutes, before committing to a long run, the operator can see whether this drive has a read-performance problem worth repairing. | proposed |
| measured-as-used | The performance the tool reports is measured the way the drive is really used, not as a synthetic best case. | proposed |

## Notes on the seed

- The first thirteen items above are the operator's, given in the REQ-016 concept session on
  2026-08-22. `auto-smart-refresh` reads "the mapped part of the drive" where the operator
  first wrote "the entire drive's used space", at their own suggestion and for the reason
  REQ-002's hazard register already records: a deallocated LBA is not backed by flash, reads
  fast without being flagged, and rewriting it would *map* it — consuming NAND and shrinking
  the free pool. "The mapped part" is what the drive can tell us; "used space" would need a
  filesystem read, which REQ-002's LBA-only invariant forbids.
- `drive-recognised` was added at the operator's direction after being surfaced as an
  unstated prerequisite of `session-record-on-stick` and `history-manager`.
- `rapid-verdict` and `measured-as-used` were added on 2026-08-27 at the operator's direction,
  in the session that assessed the read-retry literature
  ([`evidence/REQ-020/FINDINGS-read-retry.md`](evidence/REQ-020/FINDINGS-read-retry.md)). Both
  were proposed by the session and **chosen by the operator from alternatives**, which is the
  only way an item that did not start in their words gets in. `measured-as-used` replaced a
  proposed item about the measurement being *independent* of the stage that chose the work:
  the operator's ruling was that independence is not a need they have, and that what the
  number must be is relevant to a person — *"something that relates to normal use of the
  drive, but we won't get bogged down on benchmarking theory."* A random-access sample over a
  fixed block-size distribution was ruled to satisfy it.
- **`measured-as-used` is `held` as of 2026-08-27**, on the operator's ruling after the night
  run. It is a claim about *workload realism*, and nothing measured so far needs it: the rung
  histogram is a property of the media, and the settled median is flat to two parts in a
  thousand across all ten deciles of the Toshiba, so the drive has no positional structure for
  a realistic access pattern to expose
  ([`evidence/REQ-020/FINDINGS-night-run.md`](evidence/REQ-020/FINDINGS-night-run.md) §7).
  `rapid-verdict` stays open and its instrument is now measured for: a 20 000-unit random
  sample reproduced the whole 118 M-unit pass's rung shares to about a point per rung. `held`
  means *not withdrawn and not being worked* — the need stands, and it is waiting on a reason
  to be believed rather than on a session.
- Nothing else has been added. Items derived by a session rather than stated by the operator
  do not belong here — that is the pattern REQ-016 Decision 3 exists to stop.
