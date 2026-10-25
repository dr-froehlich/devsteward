# Plan 0027 — REQ-052: post-REQ-047 migration cleanup review (code + skills)

**REQ:** REQ-052 — Post-REQ-047 cleanup: code + skill review for stale/bent legacy, with a
sign-off report. Deliverable = a written review report in `docs/reports/` + clearly-safe
fixes applied inline; everything else raised as a recommendation or named follow-on REQ.

## Approach

A disciplined sweep for residue left by the trunk-based pivot (REQ-047 → 048–051), which
deleted the feature-branch / worktree / switch machinery. Two passes:

- **Code review** — grep the engine for the removed topology's vocabulary
  (`worktree`, `feature.?branch`, `switch`, `--no-ff`, `merge`) and judge each hit:
  *live current-state code/comment* (keep), *bent comment referencing gone machinery*
  (reword), or *dead data* (subtract).
- **Skill + shipped-template review** — the production skills (hardlinked to
  `devsteward/templates/.claude/skills/`), `CLAUDE.md.tmpl`, `config.yaml.tmpl`, and the
  handbook. Target: re-justification language that argues against the now-gone alternative,
  and template text that still ships the removed machinery to new consumers.

## Findings → disposition (the report carries the full table)

### Fixed inline (feasible, low-risk)

1. **`CLAUDE.md.tmpl`** branching-model bullet + the `steward checkpoint` comment — still
   describes "implementation goes on a feature branch and merges into `dev`", the engine
   "creates+switches to `git.feature_branch` … merges it back `--no-ff`". Ships the removed
   topology to every new project. Rewrite trunk-based (mirror the engine's own CLAUDE.md).
2. **`config.yaml.tmpl`** — the `git:` comment block describes the engine "manages the
   feature branch end-to-end", and carries a live-looking `feature_branch: req-{num}-{slug}`
   key. `config.py` dropped that key in REQ-048; the template still ships it. Rewrite the
   comment, drop the dead key.
3. **`bootstrap/SKILL.md`** — "REQ-sized work then branches off `dev` and merges back with a
   plain local merge." Factually wrong now. Rewrite: all work lands on `dev`.
4. **`intake/SKILL.md`** §3 — re-justifies committing on `dev` ("keeps the shared
   index/roadmap from forking … there is no feature branch"). The canonical residue Peter
   flagged. Trim to state the current single-branch fact once.
5. **`advance/SKILL.md`** — strip the "(trunk-based)" / "no branch/merge" / "no branch to
   create" justification asides; keep the substantive current-state facts (where commits
   land, single ledger).
6. **`core/model.py`** — `Step.slug` docstring ("feeds the feature-branch name") and the
   `lands` docstring ("`--no-ff` merge" / "committed on the feature branch") reference gone
   machinery. Reword; **remove the dead `slug` field** (see 7).
7. **`profiles/req/source.py`** — `slug`/`_slugify`/`_SLUG_MAX_WORDS` exist only to feed the
   dropped `feature_branch` name template; nothing reads `Step.slug` (no code, no tests).
   Pure dead-data subtraction (incl. the now-unused `re` import).
8. **`cli.py`** (3 read-binding comments) — justify the live-ledger read via "from a feature
   branch". The read-binding (REQ-040) is still live (a human can be on `main`), but the
   engine no longer creates feature branches; reword "feature branch" → "another branch".

### Spun out as a named follow-on

- **REQ-054 — rewrite the handbook workflow chapter to trunk-based.**
  `handbook/_03-workflow.qmd` describes the old model pervasively (merge gates, `--no-ff`,
  reconciling an unmerged feature branch for deferred validation, the `feature_branch`
  config). This is a coherent chapter rewrite, not surgical edits — a partial fix would
  leave the chapter internally contradictory. Out of this low-risk sweep by Decision 2
  ("never an unreviewed inline rewrite").

### Reviewed — acceptable, no change

- `core/invariants.py` worktree/branch guard — **live** enforcement of trunk-based
  (REQ-049), not residue.
- `core/git.py`, `core/seams.py`, `core/executor.py`, `profiles/req/validate.py` "no
  feature branch to merge / no worktree" comments — current-state explanations of an
  *absence* a reader might expect; not re-justification of a gone alternative.

## Tests

- AC2 (`regression`): `python -m pytest` green after the edits (subtraction broke nothing).
- `steward lint` green.
- AC1 (`manual`): the report at `docs/reports/2026-06-19-req047-migration-review.md` is the
  human-signed validation surface — verified at `steward validate REQ-052`.
