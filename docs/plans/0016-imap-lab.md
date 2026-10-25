# Plan 0016 — the first lab, consumed (REQ-031)

The first real lab put to work through the REQ-030 System-Test phase, plus the
FlowSteward re-drive. Implements REQ-031. The lab *asset* itself lives in its home repo —
FlowSteward REQ-008, plan `flowsteward/docs/plans/0009-req008-imap-lab.md` — this plan
covers DevSteward's half: the pattern and the consumption.

## The two pivotal scope decisions (Peter, 2026-06-11)

1. **No owned test server.** The lab targets the *real* internet mail server — the
   dedicated external IMAP test account FlowSteward's REQ-003a established (Dovecot,
   IMAPS; never the production THD inbox) — with credentials from FlowSteward's `.env`.
   Provenance does not get more real than production mail infrastructure itself.
2. **FlowSteward owns the lab.** The consumer owns the mail domain, the account, and the
   credentials; the engine's `process.lab` references are registry-local, so only a lab
   REQ in FlowSteward's registry can gate its future validations; and consumer fixtures
   inside the generic engine package would make `devsteward` a fixture zoo. (An earlier
   cut of this REQ built the lab under `devsteward/labs/imap/` — reworked the same day.)

## Shape

**FlowSteward side (REQ-008, landed 2026-06-11 via its own engine checkpoint).**
`labs/imap/lab.py` — single-file, stdlib-only, no `flowsteward` import (the decoupled
oracle shares no code with the package it validates; any interpreter runs it by path):
literal dotenv loader with matched-quote unwrap (the REQ-006/007 lessons), idempotent
`seed` into the lab-owned `DEVSTEWARD-LAB` mailbox, read-only `fetch`, and offline
`verify --against FILE` whose exit code is the whole external contract. Corpus
`seed-001.eml` derived from a real Nextcloud invitation captured read-only from the live
inbox (sanitized; provenance in the lab README), `manifest.json` holding the golden
fingerprint (sha256 per LF-normalized decoded MIME leaf — IMAP APPEND normalizes bare LF
to CRLF). Hard failures everywhere; a lab skip is the false-green hole this closes.

**DevSteward side (this REQ).**

- Handbook 03 · workflow gains the **consumer-owned-lab pattern** section (AC1 pins it):
  consumer repo, registry-local gating, real-system-first, self-contained tooling,
  hard-failing config, reality-derived versioned corpus.
- `tests/test_imap_lab.py::test_evidence_artifact_matches_golden` (AC2, engine-run at
  validate): locates the newest `.devsteward/evidence/REQ-031/<ts>/fetched-seed.eml` and
  grades it through the **lab's own** `verify` — DevSteward holds no manifest copy (one
  owner for the golden expectation). Seam: `DEVSTEWARD_LAB_IMAP_ENV` → FlowSteward's
  `.env`; the lab tool sits next to it. No evidence at all → skip (clean checkouts stay
  green; the validate gate counts skip as red); evidence present but seam/lab missing →
  failure, per the lab-skip-is-hard-red rule.
- AC3 (`manual`): the human reviews the re-drive evidence — FlowSteward's own live e2e
  surface (`tests/test_req003a_e2e.py`) run for real, output captured verbatim — and
  signs off via `steward validate REQ-031`.

## Out of scope

A containerized IMAP double (rejected), FlowSteward-side artifact ACs / evidence events
for its own surface (consumer follow-up intake there), multi-lab discovery mechanics.
