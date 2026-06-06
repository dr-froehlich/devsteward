# Plan 0001 — A controlled baseline for starting Claude Code projects (+ the DevSteward engine)

> Bootstrap plan, authored 2026-06-06. Predates REQ-001 (it proposes the repos in which REQ-001
> will live). Once the baseline exists, this plan's scope is tracked as the framework's own
> REQ-001…N and this file becomes the historical record of how the baseline was conceived.

## Context

Peter starts each new project by copying the most recent one as a reference, so the method drifts
and good ideas don't propagate (e.g. `examengineer/convert/run_batch_conversion.py` and
`Theresa/run_batch.py` are near-duplicate copies that have already diverged). He wants a **single
controlled baseline** that captures his proven, evolved house style and makes it reproducible —
covering the dev process, tech-agnostic scaffolding, and a bootstrap that brings a new project to
life.

His house style, reverse-engineered from memzy (newest) + examengineer (the `/scaleup` reference):
REQ-per-file with YAML frontmatter + structured prose (Context · Decisions table · Acceptance
criteria as test-named checkboxes · Notes); a frozen `REQ-001` north star; `REQUIREMENTS_INDEX.md`
+ `ROADMAP.md` (dependency DAG) + `SCN-NNN` scenarios; `docs/plans/`; `/scaleup` as an **attended**
one-checkpoint-per-run ledger walker; and `run_batch*.py` as an **unattended** quota-aware
(claude-swap two-account, pinning, adaptive gate) skill-runner over a marker file.

### Decisions locked with the user (three interview rounds)

1. **Deliverable:** all three, integrated — a copy-me template repo that contains the reference
   guide (as docs) and a `/bootstrap` skill.
2. **Automation:** build the full unified "dev manager / automation ledger" framework now.
3. **Format:** redesign for machine-readability, **hybrid** — strict schema + parseable blocks for
   what tools need; Context/Decisions/Notes stay rich prose.
4. **Intake:** a dedicated `/intake` (interview-to-REQ) skill — institutionalize the interrogation
   Peter values most.
5. **Work model:** layered — a generic executor core + a REQ-workflow profile on top.
6. **Forks while unattended:** park-and-surface — stop, record the question in the ledger, notify,
   advance to the next independent step; resume when answered. The interview stays sacred.
7. **Verification:** acceptance criteria name runnable tests; the manager runs them and only marks
   done when green.
8. **Packaging:** a shared, pipx-installable engine that operates on any project's control doc;
   per-project config lives in the repo.
9. **Build sequence:** scaffold + design-REQs + **one working vertical slice**, then iterate
   REQ-by-REQ (dogfooding).
10. **Ledger store:** git-friendly text — YAML cursor + append-only JSONL event log.

Cross-cutting constraints to encode as first-class conventions: **all code and technical
descriptions in English** (German UI strings allowed but isolated/translatable); **same-commit
discipline** (REQ frontmatter + index move with the code); co-author trailer; branch-before-main.
`/home/peter/material/` is a Quarto *manuals* repo (a consumer), not a method reference.

## Architecture — one public repo (the material-core pattern)

**Decision (user, 2026-06-06):** one public, pipx-installable package + **private consumer projects**.
This mirrors Peter's proven `material-core` (PUBLIC, `pipx install git+…/material-core@v0.1.0`, a
package whose `[project.scripts]` is `matctl`, bundling templates + shared assets as package-data,
dogfooded in-place) ↔ `material` (PRIVATE consumer, pins a tag, `matctl link`). The earlier
engine-vs-template split is dropped: everything that ships rides in one package.

**`devsteward`** (brand **DevSteward**) — PUBLIC, pipx-installable, pinned by git tag (this
`/home/peter/projects/template` repo, **renamed** `devsteward`). One Python 3.11+ package holding the
engine **and** the bundled scaffolding. The quota/account/stream machinery is **lifted and
generalized from `examengineer/convert/run_batch_conversion.py` + `Theresa/run_batch.py`** (proven
code), not rewritten.

- **Executor core** (`devsteward/core/`): resolve the next eligible step from the ledger in
  dependency order → invoke `claude -p "<command>"` headless (stream-json, watchdog, limit detection,
  graceful stop) → classify → **verify** → commit → advance the ledger. Pluggable seams:
  - *Step source*: generic profile = explicit list; REQ profile = derived.
  - *Verifier*: run named acceptance tests; green ⇒ done. Fallback: marker trust.
  - *Decision gate*: park-and-surface (below).
  - *Account provider*: claude-swap (`cswap`) two-account + `--use N` pinning + adaptive gate;
    degrades to single-account when `cswap` is absent.
- **REQ-workflow profile** (`devsteward/profiles/req/`): the **A·Design → B·Build → C·Land**
  checkpoint cycle over REQ/ROADMAP files (generalized `/scaleup`).
- **CLI** (`devsteward/cli.py`, exposed as `steward` via `[project.scripts]`):
  - `steward new` — stamp the bundled templates+skills into a (new, private) consumer project — the
    `matctl new`/`matctl link` move. (The `/bootstrap` skill wraps this with an interview.)
  - `steward advance` — attended: one checkpoint, interactive (AskUserQuestion), update ledger, print
    the fixed report (Did/Cursor/Review/Decisions/Next).
  - `steward run` — unattended: march eligible steps headless; park on forks.
  - `steward lint` — schema-validate every REQ; deps resolve; index↔REQ sync; every AC has a test id.
  - `steward status` / `steward decision list|answer` — inspect cursor; resolve parked decisions.
- **Park-and-surface:** the engine sets `DEVSTEWARD_UNATTENDED=1` when shelling headless. Skills *ask
  via AskUserQuestion when interactive, but when that env is set, write a decision request to the
  ledger and stop*. The engine records it in `state.yaml`/`events.jsonl`, notifies, advances to the
  next independent step.

```
devsteward/                 PUBLIC · pipx-installable · pinned by tag (was template/)
  pyproject.toml            # [project.scripts] steward = "devsteward.cli:main"
                            # package-data: templates/**, handbook/**, schema/**
  README.md  CLAUDE.md      # for developing devsteward itself (dogfood)
  .gitignore                # *.log, settings.local.json, runtime ledger scratch
  devsteward/               # the engine + bundled assets (all package-data)
    cli.py  core/  profiles/req/
    templates/              # what `steward new` stamps into a consumer (the scaffolding)
      CLAUDE.md.tmpl
      .claude/{settings.json, skills/{intake,advance,bootstrap}/SKILL.md}
      docs/requirements/{REQ-001.tmpl, REQUIREMENTS_INDEX.md, ROADMAP.md,
                         scenarios/, _templates/{req,scn,plan}.md, schema/req.schema.json}
      .devsteward/config.yaml.tmpl
    handbook/               # the reference guide (00-method … 04-skills)
  docs/                     # devsteward's OWN requirements — public showcase, dogfooded
    requirements/REQ-001.md …    plans/0001-…-plan.md (this file)
  tests/
```

**Consumer projects** (PRIVATE, e.g. memzy / examengineer / the next one) — the `material` role.
Each pins a `devsteward` version, runs `steward` + the bundled skills, and holds the real/private
data. Created by `steward new` / `/bootstrap`. Their `.devsteward/{config.yaml, state.yaml, events.jsonl}`
live in the consumer repo. **Committed files in the public repo are sanitized** — `settings.json` and
`CLAUDE.md.tmpl` use placeholders only (no `/mnt/c/Users/pfroehlich/…` paths, no email); account creds
stay in `~/.claude-swap-backup`, outside any repo.

## The hybrid machine-readable REQ format

Markdown + schema-validated YAML frontmatter (unchanged keys: `id, title, status, kind, added,
completed, verified_by, depends_on, concept_refs, scenario_refs, supersedes, tags`) — **plus** a
single parseable fenced block for acceptance criteria so the verifier can run and track them. Prose
sections (Context · Decisions table · Requirement · Notes) are untouched, preserving the reasoning
density that makes REQ-025 valuable.

````
```yaml acceptance
- id: AC1
  text: The matcher takes (lemma, translation) pairs; apkg and paste yield the same buckets.
  test: "pytest learning/tests/test_wordlist.py::test_paste_and_apkg_yield_same_buckets"
  status: pending            # pending | pass | fail  (engine-owned)
- id: AC2
  text: A bare-lemma list reproduces REQ-023 buckets.
  test: "pytest -k test_bare_lemma_input_matches_req023_behaviour"
  status: pending
```
````

Checkpoint/ledger state lives in `.devsteward/`, **not** in the REQ (REQ = spec, ledger = cursor). A
small renderer in `steward lint`/`status` prints the acceptance block as a human checklist. The schema
+ linter make the format a contract, not a convention.

## The three skills

- **`/intake`** — the interview skill. Take a raw idea; interrogate it (risks, weaknesses,
  alternatives, scope boundaries, dependencies, the English-code/German-UI split); emit a
  **schema-valid draft REQ** (`status: draft`) + its `REQUIREMENTS_INDEX.md` row + any `SCN` refs.
  Honors park-and-surface when run unattended.
- **`/advance`** — generalized `/scaleup`: orient from the ledger, do exactly one checkpoint
  (Design/Build/Land), stop at forks, run acceptance tests at Land, update the ledger, end with the
  fixed report. Attended counterpart to `steward run`.
- **`/bootstrap`** — bring a *new* project to life from the template: interview for stack +
  build/test commands, co-author `REQ-001` (north star), fill `CLAUDE.md` placeholders, write
  `.devsteward/config.yaml`, `git init`, initialize the ledger.

## Build phases

**Phase 0 · Scaffold + design (dogfood the format on itself)**
- Rename this dir `template` → `devsteward`; `git init`; `pyproject.toml` (package + `[project.
  scripts] steward`); baseline `.gitignore`; sanitized `templates/.claude/settings.json`.
- Write the format spec + `req.schema.json` + `templates/.../_templates/`.
- Write `CLAUDE.md.tmpl` (bootstrap-ready) + the five `devsteward/handbook/` chapters.
- Write devsteward's **own** REQ-001…N in the new format (the engine, the REQ profile, the
  format, the three skills, park-and-surface, verification, `steward new`) + `docs/requirements/
  ROADMAP.md` sequencing them + the initial dogfood ledger.
- Stub the three bundled `SKILL.md` files.

**Phase 1 · One end-to-end vertical slice (proof it runs)**
- Minimal `devsteward` package: read ledger + one REQ → run one declared step via `claude -p` →
  run that REQ's named acceptance test → commit + advance ledger → park-and-surface on a fork. Port
  the account/quota scaffolding from `run_batch*.py` (present; slice can run single-account).
- `steward new` stamps the bundled templates into a throwaway consumer dir (proves the material-core
  `matctl new` move); `pipx install --editable .` proves the install path.
- `/intake` working: interview → emit a schema-valid draft REQ.
- Demonstrate the loop: `/intake` authors a REQ; `steward advance`/`run` advances and **verifies** one
  step against its named test.

Then iterate the remaining framework REQs REQ-by-REQ using the system itself.

## Smaller defaults (easy to veto in review)
- One public package `devsteward` (this dir, renamed); CLI `steward`; Python 3.11+, stdlib-first,
  `jsonschema` for validation, `pytest` for the package's own tests; deps kept lean (mirror
  material-core: `click` for the CLI, `ruamel.yaml` for round-trip-stable YAML). Consumed by pinned
  git tag, no PyPI — same as material-core.
- Skill names `/intake`, `/advance`, `/bootstrap` (rename freely).
- Ledger = `.devsteward/state.yaml` (cursor) + `.devsteward/events.jsonl` (append-only) in the *consumer* repo.
- Method/package name `devsteward` (brand: DevSteward); CLI `steward`.
- Format back-porting of memzy/examengineer is **out of scope** now; a converter can be a later REQ.

## Verification (how we'll know the slice works)
1. `steward lint` passes on the dogfooded framework REQs (schema valid, deps resolve, every AC has a
   test id, index↔REQ in sync).
2. `/intake "<toy idea>"` produces a schema-valid draft REQ + index row; `steward lint` stays green.
3. A REQ with one trivially-passing acceptance test: `steward run` invokes `claude -p`, runs the named
   test, commits, and flips the ledger to done; `events.jsonl` shows the checkpoint + commit sha.
4. Park-and-surface: a REQ step that raises a fork, run unattended, lands as `blocked-on-decision`
   in `state.yaml` (no commit); `steward decision answer` unblocks it and the next `run` resumes.
5. `steward run --use 1` honors single-account pinning; with `cswap` absent it logs "proceeding
   without quota check" and still runs (ported `run_batch` degradation path).
