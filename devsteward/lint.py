"""``steward lint`` — make the REQ format a contract, not a convention.

Checks, per the plan:

1. every REQ's frontmatter is **schema-valid** (``req.schema.json``);
2. every ``depends_on`` / ``supersedes`` reference **resolves** to a real REQ;
3. the dependency graph is **acyclic**;
4. **index ↔ REQ in sync** — every REQ has a row in ``REQUIREMENTS_INDEX.md`` and vice
   versa, with matching status;
5. every acceptance criterion has a non-empty **test id** and (REQ-027) a valid
   ``check:`` classification (``regression | artifact | manual``) — presence and enum
   only, never test quality (that is intake's job, not a static linter's);
6. the frozen north star ``REQ-001`` is not silently mutated away from its declared kind;
7. **marker ↔ ledger** (both directions) — the ledger is the cursor of record and the
   committed marker must agree with it. (a) *marker-ahead* (REQ-028 AC5): a ledger-tracked
   REQ marked ``done`` in frontmatter has a green delivering step in the ledger — a
   hand-edited ``done`` over a ``failed``/absent land must not pass unseen. (b) *ledger-ahead*
   (REQ-077): a REQ the ledger has **delivered** (its final step DONE) whose committed HEAD
   frontmatter/index still read a pre-``done`` active status — the flip was written to the
   worktree but never committed (the FlowSteward REQ-098/099 drift). Read committed HEAD, not
   the working tree, or a written-but-uncommitted flip masks it.

References in the optional ``process:`` block's ``lab:`` list (REQ-027) resolve like
``depends_on`` (check 2).

Returns a list of human-readable problems; empty ⇒ green.
"""

from __future__ import annotations

import json
import os
from importlib.resources import files

import jsonschema

from .config import Config
from .core.ledger import Ledger
from .core.model import StepStatus
from .profiles.req.index import read_statuses
from .profiles.req.reqfile import ReqFile, load_reqs


# REQ-027 + REQ-068: the acceptance `check:` routing key — maps a criterion onto the V-model
# (regression → Build/verification; artifact, manual → System-Test/validation) and selects
# its execution lane. `live` (REQ-068) is a system-scope, decoupled-oracle test that runs as
# a **standing** develop-gate member (a continuous integration proof), unlike one-time
# `artifact`/`manual` validations.
CHECK_VALUES = ("regression", "live", "artifact", "manual")


def _schema() -> dict:
    text = (files("devsteward") / "schema" / "req.schema.json").read_text(encoding="utf-8")
    return json.loads(text)


def _detect_cycle(reqs: list[ReqFile]) -> list[str]:
    graph = {r.id: [d for d in r.depends_on] for r in reqs}
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}
    problems: list[str] = []

    def visit(node: str, stack: list[str]) -> None:
        color[node] = GREY
        for nxt in graph.get(node, []):
            if nxt not in color:
                continue  # missing dep reported elsewhere
            if color[nxt] == GREY:
                cycle = " → ".join(stack + [node, nxt])
                problems.append(f"dependency cycle: {cycle}")
            elif color[nxt] == WHITE:
                visit(nxt, stack + [node])
        color[node] = BLACK

    for n in graph:
        if color[n] == WHITE:
            visit(n, [])
    return problems


def lint(cfg: Config) -> list[str]:
    problems: list[str] = []
    schema = _schema()
    validator = jsonschema.Draft202012Validator(schema)

    if not cfg.req_dir.exists():
        return [f"requirements dir not found: {cfg.req_dir}"]

    try:
        reqs = load_reqs(cfg.req_dir)
    except ValueError as exc:
        return [str(exc)]

    ids = {r.id for r in reqs}

    # 1. schema validation
    for r in reqs:
        for err in sorted(validator.iter_errors(r.frontmatter), key=str):
            loc = ".".join(str(p) for p in err.path) or "<root>"
            problems.append(f"{r.path.name}: schema: {loc}: {err.message}")
        if r.id and r.id != r.path.stem:
            problems.append(f"{r.path.name}: id '{r.id}' does not match filename")

    # 2 + 3. dependency references resolve; graph acyclic
    for r in reqs:
        for dep in r.depends_on:
            if dep not in ids:
                problems.append(f"{r.id}: depends_on '{dep}' does not resolve to a REQ")
        sup = r.frontmatter.get("supersedes")
        sups = [sup] if isinstance(sup, str) else (sup or [])
        for s in sups:
            if s not in ids:
                problems.append(f"{r.id}: supersedes '{s}' does not resolve to a REQ")
        proc = r.frontmatter.get("process")
        if isinstance(proc, dict):
            for lab in proc.get("lab") or []:
                if lab not in ids:
                    problems.append(
                        f"{r.id}: process.lab '{lab}' does not resolve to a REQ"
                    )
    problems.extend(_detect_cycle(reqs))

    # 4. index ↔ REQ sync
    index = read_statuses(cfg.index_path)
    for r in reqs:
        if r.id not in index:
            problems.append(f"{r.id}: missing a row in {cfg.index_file}")
        elif index[r.id] != r.status.lower():
            problems.append(
                f"{r.id}: status '{r.status}' != index status '{index[r.id]}'"
            )
    for rid in index:
        if rid not in ids:
            problems.append(f"{rid}: in index but no REQ file found")

    # 5. every acceptance criterion has a test id and a valid `check:` — but only on
    #    **active** REQs (open/in-progress/blocked), the ones the engine is on the hook to
    #    land. Drafts may be incomplete by definition, and terminal REQs
    #    (done/dropped/superseded) have nothing left to land — including records imported
    #    from another project's own governance (REQ-010), where demanding a
    #    DevSteward-shaped test id is meaningless. Reopen such a REQ and it becomes
    #    active, and the rule fires again — exactly when a runnable test is needed.
    #    The same scoping covers REQ-027's `check:` routing key (Decision 9): no backfill
    #    of history, the rule fires when a REQ becomes the engine's problem.
    for r in reqs:
        if not r.is_active:
            continue
        if not r.acceptance:
            problems.append(f"{r.id}: no acceptance criteria block")
        for ac in r.acceptance:
            if not ac.test.strip():
                problems.append(f"{r.id}: acceptance {ac.id or '?'} has no test id")
            if not ac.id.strip():
                problems.append(f"{r.id}: an acceptance criterion has no id")
            if not ac.check.strip():
                problems.append(
                    f"{r.id}: acceptance {ac.id or '?'} has no check: classification "
                    f"(regression | live | artifact | manual)"
                )
            elif ac.check not in CHECK_VALUES:
                problems.append(
                    f"{r.id}: acceptance {ac.id or '?'} check '{ac.check}' is not one of "
                    f"regression | live | artifact | manual"
                )

    # 6. north star
    north = next((r for r in reqs if r.id == "REQ-001"), None)
    if north is not None and north.status in ("dropped", "superseded"):
        problems.append("REQ-001 (north star) must not be dropped or superseded")

    # 7. marker ↔ ledger reconciliation (REQ-028 AC5). A REQ is *ledger-tracked* if any of
    #    its steps appears in state.yaml; for such a REQ marked `done`, its delivering step
    #    must be DONE in the ledger. A `done` over a failed/absent land is the FlowSteward
    #    false-done shape. The delivering step is `develop` (REQ-029); a `land` step DONE is
    #    accepted too, since a REQ landed under the pre-REQ-029 model keeps its old ledger
    #    row (reinterpret, never rewrite — REQ-029 Decision 7). Mirror lint rule 5: REQs the
    #    engine never drove (pre-ledger or imported `done`s with no footprint) are outside the
    #    ledger's purview and untouched.
    ledger = Ledger(cfg.root)
    if ledger.exists():
        statuses = ledger.all_statuses()
        for r in reqs:
            if r.status.lower() != "done":
                continue
            tracked = any(sid.startswith(f"{r.id}:") for sid in statuses)
            if not tracked:
                continue
            develop = statuses.get(f"{r.id}:develop")
            land = statuses.get(f"{r.id}:land")  # legacy (pre-REQ-029) ledger shape
            if StepStatus.DONE not in (develop, land):
                shown = (develop or land).value if (develop or land) is not None else "absent"
                problems.append(
                    f"{r.id}: frontmatter status 'done' but ledger develop step is "
                    f"'{shown}' — the ledger contradicts the marker"
                )

        # 7b. The symmetric direction (REQ-077): the ledger has LANDED a REQ (its delivering
        #     step is DONE) but the **committed** marker still reads not-`done`. This is the
        #     FlowSteward REQ-098/099 drift — the checkpoint's `done` flip was written to the
        #     worktree but never committed, so `git HEAD` disagrees with the ledger. Read
        #     committed HEAD, not the working tree: the uncommitted flip on disk looks
        #     consistent and would mask the drift. The delivering step is `validate` when the
        #     REQ has one (its develop legitimately lands `done` before the flip — REQ-030 D6),
        #     else `develop`/legacy `land`; so a develop-done/validate-pending REQ is not
        #     flagged. Gated on a real git repo + the file present at HEAD — a state that cannot
        #     be assessed (no git, no committed file) is never false-flagged.
        problems.extend(_committed_marker_lags_ledger(cfg, reqs, statuses))

    return problems


def _committed_marker_lags_ledger(
    cfg: Config, reqs: list[ReqFile], statuses: dict[str, StepStatus]
) -> list[str]:
    """REQ-077 rule 7b — hard-error when the ledger has **delivered** a REQ (its final step is
    DONE) but the committed HEAD frontmatter/index still read a pre-`done` active status: the
    ``done`` flip was written to the worktree but never committed (the FlowSteward REQ-098/099
    drift). Returns the problems (empty when there is no git HEAD to read, so a no-git lint stays
    green).

    Reads the **committed** marker, not the working tree — a flip written-but-uncommitted looks
    consistent on disk and would mask the drift. Legitimate non-`done` end states are excluded:
    a REQ delivered then retired reads ``superseded``/``dropped`` at HEAD, and a REQ whose
    develop is done but whose **validate** phase (:func:`has_validate_step`) is not yet done has
    not been delivered, so its committed ``open`` is correct."""
    from .core.git import GitCli
    from .profiles.req import index as index_mod
    from .profiles.req.reqfile import TERMINAL_STATUSES, status_from_text
    from .profiles.req.source import has_validate_step

    git = GitCli(cfg.root)
    head_index_text = git.file_at_head(os.path.relpath(cfg.index_path, cfg.root))
    if head_index_text is None:
        return []  # no committed index at HEAD (no git / fresh repo) — nothing to reconcile
    head_index = index_mod.statuses_from_text(head_index_text)

    out: list[str] = []
    for r in reqs:
        # The delivering step is `validate` when the REQ declares an artifact/manual AC (its
        # develop lands `done` before the terminal flip — REQ-030 D6), else `develop`/legacy
        # `land`. Only a delivered REQ is expected to carry a committed `done`.
        if has_validate_step(r):
            delivered = statuses.get(f"{r.id}:validate") is StepStatus.DONE
            delivering = "validate"
        else:
            develop = statuses.get(f"{r.id}:develop")
            land = statuses.get(f"{r.id}:land")
            delivered = StepStatus.DONE in (develop, land)
            delivering = "develop"
        if not delivered:
            continue

        head_req_text = git.file_at_head(os.path.relpath(r.path, cfg.root))
        if head_req_text is None:
            continue  # not committed at HEAD — cannot assess the committed marker
        committed_status = status_from_text(head_req_text)
        committed_index = head_index.get(r.id)

        # A committed terminal marker is a legitimate end state (`done`, or `superseded`/
        # `dropped` for a delivered-then-retired REQ) — as long as frontmatter and index agree.
        if committed_status in TERMINAL_STATUSES and committed_index == committed_status:
            continue
        out.append(
            f"{r.id}: ledger {delivering} step is 'done' but the committed marker lags — HEAD "
            f"frontmatter is '{committed_status or 'absent'}', index row is "
            f"'{(committed_index or 'absent').upper()}' (the status flip was not committed; "
            f"same-commit discipline). Re-run `steward checkpoint {r.id} develop` or commit "
            f"the flip."
        )
    return out
