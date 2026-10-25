# REQ-047 migration cleanup review — code + skills

**REQ:** REQ-052 · **Date:** 2026-06-19 · **Scope:** code review + skill/template review for
residue left by the trunk-based pivot (REQ-047, landed across REQ-048…051, which deleted the
feature-branch / worktree / branch-switch machinery). Process-resilience (forward-path
completeness, the rework/repeat verbs) is explicitly **out of scope** — that is REQ-053.

This report is the validation surface for REQ-052's `manual` AC1: it states every finding,
its residue, and its disposition (**fixed inline** · **recommendation** · **spun-out REQ**).
The human verdict is recorded at `steward validate REQ-052`.

## Method

Grepped the engine and the shipped scaffolding for the removed topology's vocabulary
(`worktree`, `feature.?branch`, branch `switch`, `--no-ff`, `merge.?back`, `slug`) and judged
each hit against three buckets: **live current-state** code/prose (keep), **bent** prose that
references gone machinery (reword/subtract), or **dead data/config** (subtract). Two passes:
code (`devsteward/**/*.py`) and skills + templates + handbook.

## Headline

The worst residue was **not** in the engine — it was in what ships to **new consumer
projects**. `CLAUDE.md.tmpl` and `config.yaml.tmpl` still described (and configured) the
engine "managing a feature branch end-to-end: creates+switches … merges back `--no-ff`",
and `bootstrap` still told a fresh project to "branch off `dev` and merge back". A project
stamped today would have been instructed to use machinery the engine deleted in REQ-048. All
of that is fixed inline. The engine's own runtime code was clean of behavioural residue; its
only residue was stale docstrings/comments and one dead field (`Step.slug`).

---

## Code review

| # | Residue | Location | Disposition |
|---|---------|----------|-------------|
| C1 | `Step.slug` docstring: "feeds the feature-branch name when the executor manages topology" — the only consumer (feature-branch naming) is gone. | `core/model.py:53` | **Fixed inline** — docstring reworded; field removed (C3). |
| C2 | `Step.lands` docstring: "(terminal flip, land gate, `--no-ff` merge)" and "committed on the feature branch". `--no-ff` merges are gone; work commits on `dev`. | `core/model.py:71` | **Fixed inline** — reworded to "(terminal flip, land gate)" / "committed on `dev`". |
| C3 | **Dead data:** `slug` / `_slugify` / `_SLUG_MAX_WORDS` exist only to feed the dropped `feature_branch` name template. Nothing reads `Step.slug` (no engine code, no tests). | `core/model.py:64`, `profiles/req/source.py` | **Fixed inline** — removed the field, the helper, the two `slug=` args, and the now-unused `import re`. Pure subtraction; full suite stays green. |
| C4 | Three live-ledger read-binding comments justify the bind via "from a feature branch". The bind (REQ-040) is still **live** — a human can be on `main` — but the engine no longer *creates* feature branches, so the framing is bent. | `cli.py:254, 486, 608` | **Fixed inline** — "feature branch" → "another branch (e.g. `main`)"; the code is unchanged and correct. |
| C5 | Post-migration comments noting "lands inline on `dev` — no feature branch to merge / no worktree, no branch". | `core/git.py:3`, `core/seams.py:57`, `core/executor.py:424,650`, `profiles/req/validate.py:153,334` | **Reviewed — no change.** These explain the *absence* of a step a reader of the old model would expect; they state current behaviour, they do not re-argue a gone alternative. Acceptable. |
| C6 | The `invariants.py` guard that refuses a stray linked worktree / a commit on `main`, citing "trunk-based DevSteward keeps a single ledger". | `core/invariants.py:50–74` | **Reviewed — no change.** This is **live enforcement** of the trunk-based model (REQ-049), not residue. |
| C7 | `git.feature_branch` config key — the engine dropped it in REQ-048 (`config.py` has only `production_branch`/`integration_branch`); no Python reads it. | `config.py` (clean) | **Verified clean** in code; its surviving *template/handbook* copies are S5/F1 below. |

## Skill + template review

| # | Residue | Location | Disposition |
|---|---------|----------|-------------|
| S1 | "REQ-sized work then branches off `dev` and merges back with a plain local merge." Factually wrong under trunk-based — actively misinstructs a fresh project. | `bootstrap/SKILL.md` | **Fixed inline** — "All work … lands on `dev`; the engine never branches." |
| S2 | The canonical case Peter flagged: intake re-justifies committing on `dev` ("keeps the shared index/roadmap from **forking** … (Trunk-based — REQ-048 … there is **no feature branch**.)"). The "forking" rationale only made sense when other branches existed; the parenthetical re-argues the gone alternative. | `intake/SKILL.md` §3 | **Fixed inline** — trimmed to state the current single-branch fact once: "committing it serializes id allocation and keeps the index/roadmap consistent." |
| S3 | `advance` re-tags "trunk-based" / "no branch/merge" / "no branch to create" at three turns. | `advance/SKILL.md:11, 39, 92` | **Fixed inline** — asides stripped; the substantive current-state facts (where commits land, single ledger) kept. |
| S4 | `system-test` references "the divergence the trunk-based model forbids" as the rationale for the fixture rule. | `system-test/SKILL.md:64` | **Reviewed — no change.** Names the *current* model as the rationale for a **live** rule (REQ-051); not re-justification of a gone alternative. |
| F1 | **Ships to consumers:** `CLAUDE.md.tmpl` branching-model bullet describes implementation "goes on a feature branch and merges into `dev`", the engine "creates+switches to `git.feature_branch` … merges it back `--no-ff`"; the `steward checkpoint` line says "verify, land, **merge**". | `templates/CLAUDE.md.tmpl:28–39, 48` | **Fixed inline** — rewritten trunk-based, mirroring the engine's own `CLAUDE.md`. |
| F2 | **Ships to consumers:** `config.yaml.tmpl` `git:` comment describes the engine "manages the feature branch end-to-end" and ships a live-looking dead key `feature_branch: req-{num}-{slug}`. | `templates/.devsteward/config.yaml.tmpl:38–50` | **Fixed inline** — comment rewritten trunk-based; dead `feature_branch` key dropped. |

## Spun out as a named follow-on

- **Handbook workflow chapter — propose `REQ-054`.** `handbook/_03-workflow.qmd` describes the
  old model **pervasively** (lines ~21, 51, 87–90, 165, 178, 184–191, 211): merge gates, the
  `--no-ff` merge, "the executor manages the implementation feature branch … lazily creates
  and switches", reconciling an **unmerged** feature branch for deferred validation, and the
  `feature_branch` config. This is a **coherent chapter rewrite around a changed mental
  model**, not surgical line edits — a partial fix would leave the chapter internally
  contradictory (some paragraphs trunk-based, others gating on a merge). Per REQ-052
  Decision 2 ("never an unreviewed inline rewrite"), it is **out of this low-risk sweep**.
  Recommend intaking `REQ-054` to rewrite the workflow chapter (and sweep the rest of the
  handbook for the same vocabulary) to the trunk-based model.

## Misclassified tests removed (owner-directed)

Surfaced while closing: the suite carried **two tests that could only ever skip** — a
regression test that never runs is not a regression test. The owner directed removing both
(no substitute):

| # | Residue | Location | Disposition |
|---|---------|----------|-------------|
| T1 | `test_evidence_artifact_matches_golden` (REQ-031 AC2) graded captured evidence through **FlowSteward's** IMAP lab — another project's *validation* lab wired as a regression test. It only ever skipped here (needs that project's lab + credentials); FlowSteward has moved on. | `tests/test_imap_lab.py` | **Removed** (test + `_latest_evidence_fetch`/`_lab_tool` helpers + dead imports). The executable AC1 handbook-pattern test stays. No substitute. |
| T2 | `test_real_claude_end_to_end` (REQ-013) spun up a **real `claude -p`** end-to-end — a once-observed validation, opt-in, skipped unless `DEVSTEWARD_REALITY=1`. Claude should not be the object of a regression test, and a perpetually-skipped test is not a regression test. | `tests/test_reality_harness.py` | **Removed** (test + its orphaned `init_git` helper + dead imports). REQ-013's *actual* acceptance — the 3 hermetic meta-tests (it explicitly marked the real-run gate "not an acceptance test") — is executable and stays. |

Effect: the suite is now **skip-free** (181 passed, 0 skipped), which is the right shape for
a regression suite and lets AC2 (`python -m pytest`) pass the REQ-028 land gate **as
authored** — no gate change, no `--ignore` workaround.

**Note on the `done` REQs:** REQ-013 keeps its acceptance (the meta-tests survive);
REQ-031's AC2 now names a removed test. Both REQs are `done`/historical and left unedited
(rewriting a landed REQ's acceptance is out of this sweep); `steward lint` stays green.
Flagged here for the record.

## Incidental (out of scope — not REQ-047 residue)

- **`steward activate` cannot promote a freshly-intaken REQ.** `_STATUS_LINE_RE`
  (`profiles/req/reqfile.py:165`) anchors the status value to end-of-line (`[ \t]*$`) and so
  rejects the inline `# draft | open | …` comment the REQ template puts on the `status:`
  line — `steward activate REQ-052` failed with "no 'status:' line in frontmatter". This is a
  **pre-existing latent bug**, unrelated to the topology pivot; flagged here only because the
  review hit it (worked around by promoting REQ-052's status by hand). It also hit the land
  step of `steward validate REQ-052` (same writer, flipping to `done`), which is what forced
  the fix. **Fixed** in commit `671fdda` (its own commit, outside this sweep, to avoid
  smuggling an unrelated change): `_STATUS_LINE_RE` now tolerates and preserves a trailing
  comment, with a regression test covering the comment-bearing status line. All callers
  benefit — `activate` (draft→open), `validate`/land (→done) — since they share
  `set_frontmatter_status`.
- **`build/lib/` stale copies.** `build/lib/devsteward/templates/.claude/skills/` holds an
  old snapshot of three skills (pre-migration). Build output, not source; housekeeping only.

## Verification

- **AC2 (`regression`):** `python -m pytest` → **181 passed, 0 skipped** (after removing the
  two misclassified always-skip tests above). Subtraction broke nothing.
- `steward lint` → **OK**.
- **No production skill** still re-justifies the gone feature-branch/worktree topology
  (re-grep after edits: the only surviving mention is S4, which names the *current* model as
  a live rule's rationale).

## Sign-off

_Awaiting the human reviewer's verdict at `steward validate REQ-052`._ The report is intended
to be **complete** (every grep hit dispositioned: fixed-inline · reviewed-no-change ·
spun-out · incidental) and **actionable** (each open item carries a concrete next step —
either an applied fix named above, or a named recommended follow-on REQ).
