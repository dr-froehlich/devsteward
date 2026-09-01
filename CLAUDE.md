# CLAUDE.md — DevSteward (developing the engine itself)

This is the **public** DevSteward package. It bundles the engine (`steward` CLI) and the
scaffolding `steward new` stamps into consumer projects. This file is for developing
*DevSteward itself* — it is **not** the `CLAUDE.md.tmpl` that ships to consumers (that
lives at `devsteward/templates/CLAUDE.md.tmpl` and uses placeholders only).

## Design principles (read before proposing structure)

These exist because the engine accreted team-scale git topology (feature branches +
worktrees + switching) that the owner never asked for and could not audit — six
firefighting REQs traced to that one un-chosen default (see REQ-047, `[[trunk-based-pivot-req047]]`).
When you design or change anything here, hold to these:

- **Trunk-based, linear history by default.** Work on one branch (`dev`); do not introduce
  feature branches, worktrees, or engine-initiated branch switching. The reference projects
  are ExamEngineer, Memzy, and scaleup — single linear trace, no switching back and forth.
  If you think branching is warranted, *say so and ask first* — never assume it.
- **Minimal topology / prefer subtraction.** Add machinery only when a concrete, present
  need demands it. A string of fixes that each *add* structure is a smell that the premise
  is wrong — stop and question the premise, don't patch it.
- **Don't solve information-flow constraints with git topology.** "A session must not read
  the diff" (the System-Test decoupling) is enforced by the session not reading it — not by
  a separate branch. Keep isolation in the layer that actually owns it.
- **Surface unnecessary complexity, especially in the owner's blind spots.** The owner's git
  competence is limited and trusts the AI here; that is exactly where over-engineering hides.
  Volunteer the simplest alternative in terms the owner can judge, and justify any complexity
  before building it.
- **Match the owner's stated references; fill silence with the *simplest* option, not the
  most conventional one.** Unspecified ≠ "do it the impressive way."

## House conventions (first-class, enforced)

- **English everywhere** in code and technical docs. German UI strings are allowed but
  must be isolated/translatable — never inline in logic.
- **Same-commit discipline:** a REQ's frontmatter, its row in `REQUIREMENTS_INDEX.md`,
  and the code that satisfies it move in the *same* commit.
- **Status has one source — the index ↔ frontmatter pair** (kept in lockstep by `steward
  lint`; `steward status` reads it live).
- **Branching model — trunk-based (REQ-047 → REQ-048, landed).** All work lands on **`dev`**:
  intake (REQ frontmatter, index row), plans, the ledger, **and** implementation
  (code + acceptance tests + the status-flip to `done` + index `DONE`-sync) are all committed
  directly on `dev`. **No feature branches, no worktrees, no engine-initiated branch
  switching** — the engine never creates, switches, or merges a branch; there is one
  co-located ledger that cannot diverge from itself. `main` = production / released (release
  tags like `v0.1.0` cut here; consumers pin them); `dev` = integration / beta, the default
  working branch. Never commit to `main`; the **only** branch operation is the human-gated
  `dev → main` release PR. Beta tags (`vX.Y.Z-beta.N`, PEP 440 pre-release) may be cut on
  `dev`; stable tags on `main`. If `main` is ever hotfixed directly, merge it back into `dev`.
- **Attribution trailer** on commits is a *disclosure*, not an authorship claim:
  `Assisted-by: Claude:<model-id>` naming the model actually driving the session — never a
  hardcoded model string, and **no email address**. A model holds no copyright, signs no CLA
  and cannot certify a DCO, so an *authorship* trailer would be false whatever name it
  carried; disclosure is the claim that is true. The human stays the sole `Author:`.
  Engine-made commits (`steward checkpoint`) name the model
  the engine resolved for that spawn, or `Claude:unknown` when the identity genuinely did not
  reach it — an absent version is stated, never blanked into a bare agent name. An attended
  session exports `DEVSTEWARD_ASSISTED_BY` so a `steward` subprocess can name its driver.
  Neither the engine nor a session adds `Signed-off-by:` — the DCO is a certification only a
  human can make.
- **The shipped manual tracks the engine (REQ-094).** A REQ that changes anything a *consumer
  agent* observes — a CLI verb, a flag, a behaviour, a frontmatter field — updates
  `devsteward/templates/STEWARD.md` in the **same commit**. That file is the black-box manual
  `CLAUDE.md.tmpl` calls "the authoritative `steward` reference", and it is the only interface a
  consumer has: a feature the manual does not describe does not exist for them, however green its
  tests are. `tests/test_steward_manual.py` derives verb coverage from the click registry and will
  go red on a new verb by itself, but it cannot see a behaviour change that adds no verb — that
  half is yours. This obligation is **DevSteward's own** and must never be pushed into a shipped
  artifact: the bundled skills are inode-shared with their templates, so a rule added to
  `/advance` ships to every consumer, and telling a consumer to edit `STEWARD.md` would mark their
  copy `customized` and make `steward sync` refuse it forever. Dogfooding does not license using
  the engine's reach for what only this project needs.
- **Sanitized public repo:** no real local paths (`/mnt/c/Users/...`), no emails, no
  account creds in committed files. Templates use placeholders.

## Layout

- `devsteward/core/` — the generic executor core. Knows nothing about REQs: it resolves
  the next eligible step from the ledger, invokes `claude -p`, verifies, commits,
  advances. Pluggable seams: step source, verifier, decision gate, account provider.
- `devsteward/profiles/req/` — the REQ-workflow profile (Design → Build → Land) layered
  on the core. The only content-aware part.
- `devsteward/cli.py` — `steward` (click): `new`, `advance`, `run`, `checkpoint`,
  `lint`, `status`, `decision`.
- `devsteward/templates/` — the scaffolding `steward new` stamps (package-data).
- `devsteward/handbook/` — the reference guide (00-method … 04-skills).
- `docs/requirements/` — DevSteward's **own** REQs (dogfooded). `.devsteward/` holds its
  own ledger.

## Build / test

```sh
python -m pytest            # run the package's own tests
steward lint                # validate the dogfooded REQs (run from repo root)
pipx install --editable .   # prove the install path — pipx ONLY (see below)
```

**Install path: pipx editable, and nothing else.** The `steward` command is the **pipx**
editable install (`~/.local/bin/steward` → the pipx venv), which tracks the repo live and is
what consumers (e.g. FlowSteward) also use. Do **not** `pip install -e .` (or
`pip install -e`) into a project `.venv`: it is redundant (the pipx command already exists,
and `python -m pytest` resolves `devsteward` via `sys.path` without any install), it creates a
*second* console script that shadows pipx on PATH when the venv is active, and it is a known
footgun. A `.venv` is fine **only** for isolated dev tooling (pytest/click); never install the
package itself into it.

**Never run `pip install -e .` from inside the engine's managed worktree**
(`<repo>.parent/.devsteward.<integration>-wt`, the transient linked worktree REQ-037 spins up
to write the ledger). pip binds the editable mapping to that ephemeral path; when the engine
prunes the worktree, every `steward` from that install breaks with `ModuleNotFoundError`.
Always install from the canonical repo root (`git rev-parse --show-toplevel`). To repair a
poisoned editable: `pip uninstall -y devsteward` then reinstall from the repo root.

## The ledger contract

REQ = spec, ledger = cursor. Checkpoint state lives in `.devsteward/state.yaml` (cursor)
and `.devsteward/events.jsonl` (append-only event log) — **never** in the REQ files.
Verification (running named acceptance tests) and park-and-surface (recording a parked
decision when `DEVSTEWARD_UNATTENDED=1`) are owned by the engine, not by skills.
