"""steward — the DevSteward command-line interface."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from importlib.resources import files
from pathlib import Path

import click

from . import __version__, skillsync
from .build import build_executor
from .config import Config, ProjectNotFound, load_config
from .core import claude as claude_mod
from .core.errors import StewardError
from .core.executor import RunOutcome, StepResult
from .core.invariants import check_invariants
from .core.ledger import Ledger
from .core.stop import StopController
from .core.model import DecisionStatus, StepStatus
from .core.transaction import transaction
from .lifecycle import (
    LifecycleError,
    activate as lifecycle_activate,
    repeat as lifecycle_repeat,
    revalidate as lifecycle_revalidate,
    rework as lifecycle_rework,
)
from .lint import lint as run_lint


def _package_templates() -> Path:
    return Path(str(files("devsteward"))) / "templates"


def _load_or_die() -> Config:
    try:
        return load_config()
    except ProjectNotFound as exc:
        raise click.ClickException(str(exc)) from exc


class _StewardCLI(click.Group):
    """The single top-level transaction-error handler (REQ-049).

    Every mutating command runs inside the universal boundary; a :class:`PreconditionError`
    (the command refused to start) or :class:`RecoverableError` (a mutation failed and was
    rolled back) is caught *here*, once, and printed as a one-line failure plus its operator
    ``recovery`` — never a raw traceback. A bare ``CalledProcessError` reaching this layer is
    itself a bug — a mutation that escaped the boundary — so it is surfaced loudly.
    """

    def invoke(self, ctx):
        try:
            return super().invoke(ctx)
        except StewardError as exc:
            click.echo(click.style(f"✗ {exc}", fg="red"), err=True)
            click.echo(click.style(f"  recovery: {exc.recovery}", fg="yellow"), err=True)
            raise SystemExit(1) from exc
        except subprocess.CalledProcessError as exc:
            click.echo(
                click.style(
                    f"✗ a git command failed and escaped the transaction boundary (a bug — "
                    f"please report): {exc}",
                    fg="red",
                ),
                err=True,
            )
            raise SystemExit(1) from exc


@click.group(cls=_StewardCLI)
@click.version_option(__version__, prog_name="steward")
def main() -> None:
    """DevSteward — drive a Claude Code project from its requirements ledger."""


# -- new ----------------------------------------------------------------------


@main.command()
@click.argument("target", type=click.Path(path_type=Path))
@click.option("--profile", default="req", show_default=True, help="Ledger profile.")
@click.option("--force", is_flag=True, help="Stamp into a non-empty directory.")
def new(target: Path, profile: str, force: bool) -> None:
    """Stamp the bundled scaffolding into a new (private) consumer project at TARGET."""
    target = target.resolve()
    if target.exists() and any(target.iterdir()) and not force:
        raise click.ClickException(f"{target} is not empty (use --force to stamp anyway)")
    src = _package_templates()
    if not src.is_dir():
        raise click.ClickException(f"bundled templates not found at {src}")

    stamped = _stamp(src, target)
    Ledger.init(target, profile=profile)
    # REQ-036 Decision 5: seed the provenance manifest so drift is measured from the
    # honest baseline — the template hash each bundled skill was actually stamped from.
    skillsync.seed_lock(target, src)
    click.echo(f"Stamped {stamped} files into {target}")
    click.echo("Next: cd in, run `/bootstrap` (interview) or edit REQ-001 and `steward lint`.")


# Placeholders `steward new` resolves itself (not interview-dependent). Everything else
# (`{{PROJECT_NAME}}`, `{{STACK}}`, …) is left for `/bootstrap` to fill.
_STAMP_SUBSTITUTIONS = {"{{TODAY}}": date.today().isoformat()}


def _stamp(src: Path, dst: Path) -> int:
    """Copy the template tree, stripping a trailing ``.tmpl`` and resolving stamp-time
    placeholders (e.g. ``{{TODAY}}``)."""
    count = 0
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        out = dst / rel
        if path.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            continue
        if out.name.endswith(".tmpl"):
            out = out.with_name(out.name[: -len(".tmpl")])
        out.parent.mkdir(parents=True, exist_ok=True)
        data = path.read_bytes()
        # REQ-036: bundled skills are pure engine *behavior* and must byte-match the
        # template they were stamped from (the drift model's whole premise) — copy them
        # verbatim, never substituting. A skill like bootstrap carries `{{TODAY}}` as
        # literal instruction text, so substituting there would both corrupt the
        # instruction and break every drift comparison.
        if rel.parts[: len(skillsync.SKILLS_RELDIR.parts)] == skillsync.SKILLS_RELDIR.parts:
            out.write_bytes(data)
            count += 1
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            out.write_bytes(data)  # binary asset, copy verbatim
        else:
            for token, value in _STAMP_SUBSTITUTIONS.items():
                text = text.replace(token, value)
            out.write_text(text, encoding="utf-8")
        count += 1
    return count


# -- lint ---------------------------------------------------------------------


@main.command()
def lint() -> None:
    """Schema-validate REQs; deps resolve; index↔REQ in sync; every AC has a test id."""
    cfg = _load_or_die()
    problems = run_lint(cfg)
    if not problems:
        click.echo(click.style("lint: OK", fg="green"))
        return
    for p in problems:
        click.echo(click.style(f"  ✗ {p}", fg="red"))
    raise click.ClickException(f"{len(problems)} problem(s)")


# -- lifecycle (activate / repeat) --------------------------------------------


@main.command()
@click.argument("req_id")
def activate(req_id: str) -> None:
    """Flip REQ_ID from draft (or dropped) to open, syncing its index row; uncommitted.

    One verb for one logical action — it edits the REQ frontmatter and the
    ``REQUIREMENTS_INDEX.md`` row in lockstep so ``steward lint`` stays green, leaving both
    files for you to commit deliberately. Refuses done/superseded REQs (supersede instead).
    """
    cfg = _load_or_die()
    ex = build_executor(cfg)
    # REQ-049: the frontmatter flip + index row move atomically (same-commit discipline — a
    # mid-edit crash must not leave them out of sync); regardless of HEAD (allow_any_head).
    check_invariants(ex, allow_any_head=True)
    try:
        with transaction(ex.git, label=f"activate {req_id}", pass_through=(LifecycleError,)):
            res = lifecycle_activate(cfg, req_id)
    except LifecycleError as exc:
        raise click.ClickException(str(exc)) from exc
    color = "green" if res.changed else "yellow"
    click.echo(click.style(res.message, fg=color))


@main.command()
@click.argument("req_id")
def repeat(req_id: str) -> None:
    """Re-arm REQ_ID's failed step so the next run runs it again (its partial work intact).

    The run-it-again recovery verb (REQ-026, renamed from `recover` by REQ-054): the common
    case is sound work failed by an external cause (claude crashed, an API timed out, an
    account swap), so the honest action is *repeat the step*. Flips the REQ's FAILED ledger
    step(s) to RECOVER and records an event; the working tree is left exactly as the failed
    attempt left it, for the resuming skill to assess. Fails (non-zero) when the REQ has no
    failed step — a *red validation* leaves no failed step, so return it to develop with
    `steward rework REQ_ID` instead.
    """
    cfg = _load_or_die()
    ex = build_executor(cfg)
    # REQ-049 AC3: a recovery verb succeeds regardless of HEAD — INV-1 (single ledger) only,
    # not the branch/tree gate — and is atomic. A LifecycleError is a graceful refusal raised
    # before any mutation, so it passes through the boundary untouched (no rollback).
    check_invariants(ex, allow_any_head=True)
    try:
        with transaction(ex.git, label=f"repeat {req_id}", pass_through=(LifecycleError,)):
            res = lifecycle_repeat(ex.ledger, req_id)
    except LifecycleError as exc:
        raise click.ClickException(str(exc)) from exc
    flipped = ", ".join(res.steps)
    click.echo(
        click.style(
            f"repeating {req_id}: {flipped} -> recover. Re-run `steward run` to re-attempt.",
            fg="green",
        )
    )


@main.command()
@click.argument("req_id")
def rework(req_id: str) -> None:
    """Return REQ_ID's red validation to develop for a fix-and-revalidate cycle.

    The human-authorized return edge of the V-model (REQ-033): on an in-flight REQ whose
    latest System-Test validation went red, this flips REQ_ID:develop to RECOVER and
    REQ_ID:validate back to PENDING, answers the parked decision, and records a `rework`
    event carrying the red evidence dir — the resuming `/advance` session reads it as its
    repair context. Touches no git and no REQ file. Refuses when there is no red validation
    to rework (a done REQ → supersede instead; nothing parked red → nothing to do).
    """
    cfg = _load_or_die()
    ex = build_executor(cfg)
    check_invariants(ex, allow_any_head=True)  # REQ-049 AC3: regardless of HEAD; single-ledger only
    try:
        with transaction(ex.git, label=f"rework {req_id}", pass_through=(LifecycleError,)):
            res = lifecycle_rework(cfg, ex.ledger, req_id)
    except LifecycleError as exc:
        raise click.ClickException(str(exc)) from exc
    where = f" (evidence: {res.evidence})" if res.evidence else ""
    click.echo(
        click.style(
            f"reworking {req_id}: {res.develop_step} -> recover, {res.validate_step} -> "
            f"pending{where}. Re-run `steward run` to fix and revalidate.",
            fg="green",
        )
    )


@main.command()
@click.argument("req_id")
def revalidate(req_id: str) -> None:
    """Re-run REQ_ID's red validation without redoing develop (the external-cause edge).

    The validate-layer mirror of `steward rework` (REQ-055): when a red validation was
    caused by something *external* to the work (a broken lab fixture, a missing credential,
    a downed host) that you have since fixed, the develop work stands. This flips
    REQ_ID:validate back to PENDING, **leaves REQ_ID:develop at DONE**, answers the parked
    decision, and records a `revalidate` event — then `steward run`/`steward validate`
    re-runs the validation only. Touches no git and no REQ file. Same refusals as `rework`
    (a done REQ → supersede; nothing parked red → nothing to do). Use `steward rework`
    instead when the develop was hollow.
    """
    cfg = _load_or_die()
    ex = build_executor(cfg)
    check_invariants(ex, allow_any_head=True)  # REQ-049 AC3: regardless of HEAD; single-ledger only
    try:
        with transaction(ex.git, label=f"revalidate {req_id}", pass_through=(LifecycleError,)):
            res = lifecycle_revalidate(cfg, ex.ledger, req_id)
    except LifecycleError as exc:
        raise click.ClickException(str(exc)) from exc
    where = f" (evidence: {res.evidence})" if res.evidence else ""
    click.echo(
        click.style(
            f"revalidating {req_id}: {res.validate_step} -> pending (develop stays "
            f"done){where}. Re-run `steward run` to re-validate.",
            fg="green",
        )
    )


# -- status -------------------------------------------------------------------


@main.command()
def status() -> None:
    """Show the ledger cursor, eligible/blocked steps, and parked decisions."""
    cfg = _load_or_die()
    ex = build_executor(cfg)
    # REQ-040 Decision 1: bind the read path too — from another checked-out branch (e.g.
    # `main`) an unbound read returns a stale snapshot, not the live integration-branch cursor.
    led = ex.live_ledger()
    steps = ex.steps()
    # REQ-060: the cursor orients toward pending work, so surface it only while it still
    # names a step the engine derives (an active REQ). A cursor pinned to a *done* step the
    # engine refuses to derive is strictly misleading — suppress it in favour of the honest
    # terminal line below rather than echo the last finished step.
    cursor = led.cursor_step
    if cursor and cursor in {s.id for s in steps}:
        click.echo(f"profile: {led.profile}    cursor: {cursor}")
    else:
        click.echo(f"profile: {led.profile}")

    if not steps:
        # REQ-060: a caught-up project names its forward path (the [[REQ-056]] principle
        # applied to the *done* terminal) — activation when drafts are waiting, else
        # `/intake` for the next REQ — instead of the bare "no active steps" dead-end.
        from .profiles.req.reqfile import load_reqs

        if any(r.status == "draft" for r in load_reqs(cfg.req_dir)):
            click.echo(
                "all active requirements done — activate a waiting draft with "
                "`steward activate REQ-NNN`."
            )
        else:
            click.echo("all requirements done — nothing to do; add the next with `/intake`.")
    else:
        eligible = {s.id for s in ex.eligible_steps()}
        click.echo("\nsteps:")
        for s in steps:
            st = led.status_of(s.id)
            mark = {
                StepStatus.DONE: click.style("✓", fg="green"),
                StepStatus.BLOCKED: click.style("⏸", fg="yellow"),
                StepStatus.FAILED: click.style("✗", fg="red"),
                StepStatus.RECOVER: click.style("↻", fg="magenta"),
                StepStatus.RUNNING: click.style("…", fg="cyan"),
            }.get(st, "•")
            tag = click.style(" (eligible)", fg="cyan") if s.id in eligible else ""
            # REQ-030 Decision 7: a validate step held by an undone lab REQ says so.
            note = ""
            if s.blocked_note and s.id not in eligible and st is not StepStatus.DONE:
                note = click.style(f"  ⏳ {s.blocked_note}", fg="yellow")
            elif st is StepStatus.FAILED:
                # REQ-056 Decision 4: a FAILED step names its own forward verb. D, H, and the
                # pre-existing FAILED states (A/B/G) now carry the next-action hint the parked
                # -decision line used to give — `steward repeat REQ` re-runs against the tree.
                note = click.style(f"  → steward repeat {s.req or s.id}", fg="red")
            click.echo(f"  {mark} {s.id:<22} {st.value}{tag}{note}")

    decisions = led.open_decisions()
    if decisions:
        click.echo(click.style("\nparked decisions:", fg="yellow"))
        for d in decisions:
            click.echo(f"  {d.id} [{d.step}] {d.question}")

    # REQ-036 Decision 3: stamped bundled skills drifting from the installed engine is an
    # informational warning — visible (the fix for "silent"), never a blocking gate.
    drifted = skillsync.drift(cfg.root, _package_templates())
    if drifted:
        click.echo(click.style("\nskills:", fg="yellow"))
        for d in drifted:
            click.echo(
                click.style(f"  ⚠ {d.name:<14} {d.bucket.value}", fg="yellow")
                + "  — run `steward sync-skills`"
            )


# -- sync-skills (bundled-skill drift) ----------------------------------------


@main.command("sync-skills")
@click.option(
    "--force", is_flag=True,
    help="Refresh a *customized* skill too, backing the local copy up (.orig) first.",
)
def sync_skills(force: bool) -> None:
    """Refresh stale bundled skills from the installed template; re-record the lock (REQ-036).

    A *stale* bundled skill (untouched since stamp, template advanced) is refreshed to
    byte-match the installed engine and the provenance lock updated. A *customized* skill
    (edited locally) is left untouched and reported unless ``--force`` is given, in which
    case its current bytes are backed up to ``SKILL.md.orig`` before the refresh.
    """
    cfg = _load_or_die()
    res = skillsync.sync(cfg.root, _package_templates(), force=force)
    for name in res.synced:
        click.echo(click.style(f"  ✓ {name}: refreshed (was stale)", fg="green"))
    for name in res.forced:
        click.echo(click.style(
            f"  ✓ {name}: refreshed (--force; backup {res.backups[name]})", fg="green"
        ))
    for name in res.refused:
        click.echo(click.style(
            f"  ⚠ {name}: customized — left untouched (use --force to overwrite)", fg="yellow"
        ))
    if not res.changed and not res.refused:
        click.echo(click.style("all bundled skills in-sync.", fg="green"))


# -- live progress ------------------------------------------------------------


def _tool_summary(name: str, tool_input: dict) -> str:
    """A short one-liner for a tool_use block, so progress lines stay scannable."""
    for key in ("command", "file_path", "path", "pattern", "query", "url"):
        val = tool_input.get(key)
        if isinstance(val, str) and val:
            val = " ".join(val.split())
            return f" {val[:80]}{'…' if len(val) > 80 else ''}"
    return ""


def _stderr_announcer(msg: str) -> None:
    """The account provider's visibility sink (REQ-025 D5): utilization, switches, and quota
    waits go to stderr — the same channel as live progress — so account activity is visible."""
    click.echo(click.style(f"⊟ {msg}", fg="magenta"), err=True)


def _stream_printer():
    """An ``on_event`` callback that renders live ``claude`` stream-json to stderr.

    stdout is reserved for the final report, so progress goes to stderr — the user sees
    Claude working in real time instead of a silent terminal.
    """

    def emit(ev: dict) -> None:
        etype = ev.get("type")
        if etype == "system" and ev.get("subtype") == "init":
            model = ev.get("model", "")
            click.echo(click.style(f"⟳ claude session started  {model}", fg="cyan"), err=True)
        elif etype == "assistant":
            for block in ev.get("message", {}).get("content", []):
                btype = block.get("type")
                if btype == "text":
                    text = (block.get("text") or "").strip()
                    if text:
                        click.echo(text, err=True)
                elif btype == "tool_use":
                    name = block.get("name", "tool")
                    summary = _tool_summary(name, block.get("input") or {})
                    click.echo(click.style(f"  ⚙ {name}", fg="blue") + summary, err=True)
        elif etype == "raw":
            click.echo(click.style(ev.get("text", ""), dim=True), err=True)
        elif etype == "result":
            cost = ev.get("total_cost_usd")
            dur = ev.get("duration_ms")
            bits = []
            if isinstance(dur, (int, float)):
                bits.append(f"{dur / 1000:.0f}s")
            if isinstance(cost, (int, float)):
                bits.append(f"${cost:.4f}")
            tail = f"  ({', '.join(bits)})" if bits else ""
            click.echo(click.style(f"✓ claude session ended{tail}", fg="cyan"), err=True)

    return emit


# -- advance (single step) ----------------------------------------------------


def _resolve_target(req_id: str | None, only: str | None) -> str | None:
    """The effective ``--only`` target from the positional REQ_ID and the ``--only`` flag.

    REQ-042 D2/AC3: the two spellings are mutually exclusive — supplying both is ambiguous,
    so fail loudly rather than silently prefer one. Otherwise the positional reuses the
    ``--only`` resolution verbatim (D1), so just fold it onto ``only``.
    """
    if req_id is not None and only is not None:
        raise click.ClickException(
            "name the target REQ either positionally (`advance REQ-NNN`) or with `--only`, "
            "not both."
        )
    return req_id or only


def _print_steer_hint(ex, command: str) -> None:
    """Surface the otherwise-silent lowest-id pick and teach the steer gesture (REQ-042
    D4/AC4): when no REQ was named and more than one is eligible, list the eligible ids,
    name the one being advanced, and show the ``steward <command> REQ-NNN`` steer syntax.
    A no-op at ≤1 eligible REQ — the unattended auto-drive stays unchanged."""
    req_ids = sorted({s.req for s in ex.eligible_steps()})
    if len(req_ids) <= 1:
        return
    chosen = ex.next_eligible()
    click.echo(
        f"{len(req_ids)} REQs eligible: {', '.join(req_ids)}. "
        f"Advancing {chosen.req} (lowest id) — "
        f"steer another with `steward {command} REQ-NNN`."
    )


@main.command()
@click.argument("req_id", required=False, default=None)
@click.option("--pin", type=int, default=None, help="Pin one clauder account (drain its 7d budget); forwards `clauder gate --pin N`.")
@click.option("--threshold", type=float, default=None, help="Quota gate (fraction or percent; default 70).")
@click.option("--model", default=None, help="Claude model (default claude-opus-4-8).")
@click.option("--effort", default=None, help="Reasoning effort (default high).")
@click.option("--only", default=None, help="Restrict to one REQ's steps (fails if none eligible).")
@click.option("--quiet", is_flag=True, help="Suppress live claude output; show only the report.")
def advance(
    req_id: str | None,
    pin: int | None, threshold: float | None, model: str | None, effort: str | None,
    only: str | None, quiet: bool,
) -> None:
    """Do exactly one checkpoint headless, then print the fixed report.

    Name a REQ positionally (``steward advance REQ-NNN``) to steer which eligible step runs;
    it maps onto ``--only`` and the two may not both be given (REQ-042).

    Like ``run`` this drives ``claude -p`` (no interactive client), so forks
    park-and-surface — there is no human channel for ``AskUserQuestion`` here.
    Resolve any parked fork with ``steward decision answer`` and re-run.
    """
    target = _resolve_target(req_id, only)
    cfg = _load_or_die()
    ctrl = StopController()
    ctrl.install()
    ex = build_executor(
        cfg, pin=pin, threshold=threshold, model=model, effort=effort,
        announce=_stderr_announcer, stop=ctrl,
    )
    if target is None:
        _print_steer_hint(ex, "advance")
    on_event = None if quiet else _stream_printer()
    res = ex.advance_once(only=target, unattended=True, on_event=on_event)
    if res is None:
        if target is not None:
            raise click.ClickException(ex.only_ineligibility_reason(target))
        click.echo("Nothing eligible — every step is done, blocked, or waiting on a dep.")
        return
    _print_report(ex, res)


# -- checkpoint (interactive land tail) ---------------------------------------


@main.command()
@click.argument("req_id", required=False, default=None)
@click.argument("phase", required=False, default=None)
def checkpoint(req_id: str | None, phase: str | None) -> None:
    """Verify, land, merge — close an interactively driven step as one transaction.

    The interactive ``/advance`` skill does the thinking and leaves the tree dirty; this
    runs the engine's land-grade gate and, on green, the same mechanical bookkeeping as a
    batch land (flip done, index sync, the one commit, ledger advance) plus the topology
    close-out (trailing ledger follow-up, ``--no-ff`` merge) — no ``claude`` call — so the
    frontmatter ``done``, the index row, the commit, and the ledger checkpoint can no
    longer drift apart. With no REQ_ID the target is the current cursor step; PHASE
    defaults to ``develop``. On red nothing lands; fix and re-run.
    """
    cfg = _load_or_die()
    ex = build_executor(cfg)
    if req_id is None:
        # REQ-041: resolve the cursor from the live integration-branch ledger, not an
        # unbound snapshot of another branch (REQ-040 Decision 1, completed across read sites).
        step_id = ex.live_ledger().cursor_step
        # REQ-060: an unset cursor — or one pinned to a done/non-derivable step (the
        # all-caught-up terminal) — means nothing is in flight. Say so plainly rather than
        # push a stale cursor into the "not a derivable step" error below.
        if not step_id or ex.step_by_id(step_id) is None:
            raise click.ClickException(
                "nothing in flight to checkpoint — pass a target explicitly: "
                "`steward checkpoint REQ-NNN [PHASE]`"
            )
    else:
        step_id = f"{req_id}:{phase or 'develop'}"
    step = ex.step_by_id(step_id)
    if step is None:
        # REQ-060: name *why* an explicit target is not derivable — tell, don't interrogate.
        # The common case is a finished REQ, which has a clear forward action (supersede).
        from .profiles.req.reqfile import load_reqs

        req = step_id.partition(":")[0]
        target = next((r for r in load_reqs(cfg.req_dir) if r.id == req), None)
        if target is not None and target.status == "done":
            raise click.ClickException(
                f"{req} is done — nothing to checkpoint; supersede it to change direction"
            )
        raise click.ClickException(
            f"{step_id} is not a derivable step — is {req} active "
            f"(not draft/done) and is the phase 'develop'?"
        )
    if step.phase == "validate":
        # The System-Test phase has its own gate (engine-run artifact ACs, evidence,
        # sign-offs) — checkpointing it here would land on marker-trust (REQ-030).
        raise click.ClickException(
            f"{step_id} is a System-Test step — run `steward validate {step.req}` instead"
        )
    res = ex.checkpoint(step)
    if res.outcome is RunOutcome.REFUSED:
        raise click.ClickException(res.detail)
    if res.outcome is RunOutcome.VERIFY_FAILED:
        raise click.ClickException(f"verify failed — not checkpointed:\n{res.detail}")
    _print_report(ex, res)


# -- validate (System-Test phase) ----------------------------------------------


def _git_user_name(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "config", "user.name"],
            capture_output=True, text=True, check=False,
        ).stdout.strip()
    except OSError:
        out = ""
    return out


def _interactive_signoff(root: Path):
    """The attended sign-off source (REQ-030 D4 / REQ-034 D7): present the manual AC, take
    the human's verdict — one of three terminal outcomes — and an optional one-line scope.
    The engine composes everything else.

    Taken *after* the guided session exits (the editor pattern), so the verdict is the
    human's and engine-recorded; the session cannot self-certify (Decision 2)."""
    from .profiles.req.validate import Signoff

    def provider(ac) -> Signoff:
        click.echo(click.style(f"\nmanual {ac.id}:", bold=True) + f" {ac.text}")
        if ac.test:
            click.echo(f"  oracle: {ac.test}")
        verdict = click.prompt(
            "Verdict — [a]pprove / [d]ecline / [p]ending (defer as async QA)",
            type=click.Choice(["a", "d", "p"]), default="p", show_choices=True,
        )
        if verdict == "p":
            return Signoff(approved=False, reviewer="", deferred=True)
        reviewer = _git_user_name(root) or click.prompt("Reviewer")
        scope = ""
        if verdict == "a":
            scope = click.prompt(
                "Scope (one line, e.g. what was reviewed; empty to skip)",
                default="", show_default=False,
            ).strip()
        return Signoff(approved=(verdict == "a"), reviewer=reviewer, scope=scope)

    return provider


@main.command()
@click.argument("req_id")
@click.option("--quiet", is_flag=True, help="Suppress live claude output; show only the report.")
def validate(req_id: str, quiet: bool) -> None:
    """Run REQ_ID's System-Test phase — the single entry point (REQ-030).

    On an in-flight REQ this executes the pending ``validate`` step: the fresh System
    Tester session preps the lab and captures artifacts, the engine runs each
    ``artifact`` AC's named test itself, ``manual`` ACs take your sign-off here, and on
    green the REQ lands mechanically (flip, index, commit, merge). On a **done** REQ it
    appends a fresh dated evidence event and leaves the REQ file untouched — status *and*
    ``verified_by`` stay the frozen landing provenance (re-run policy, REQ-030 Decision 5
    as clarified by REQ-035). A red validation parks with the failure brief — no repair loop.
    """
    cfg = _load_or_die()
    ctrl = StopController()
    ctrl.install()
    ex = build_executor(cfg, announce=_stderr_announcer, stop=ctrl)
    routine = ex.validate_runner
    if routine is None:
        raise click.ClickException("the generic profile has no validation phase")
    from .profiles.req.reqfile import load_reqs

    req = next((r for r in load_reqs(cfg.req_dir) if r.id == req_id), None)
    if req is None:
        raise click.ClickException(f"{req_id}: no such requirement")
    on_event = None if quiet else _stream_printer()
    signoff = _interactive_signoff(cfg.root)

    if req.status == "done":
        res = routine.revalidate(ex, req_id, on_event=on_event, signoff=signoff)
        if res.outcome is RunOutcome.REFUSED:
            raise click.ClickException(res.detail)
        if res.outcome is not RunOutcome.DONE:
            raise click.ClickException(f"re-validation red:\n{res.detail}")
        click.echo(click.style(
            f"fresh evidence recorded for {req_id} — the REQ file is unchanged "
            f"(status and verified_by both frozen).", fg="green"
        ))
        return

    step = ex.step_by_id(f"{req_id}:validate")
    if step is None:
        raise click.ClickException(
            f"{req_id} has no validate step — it declares no artifact/manual acceptance "
            f"criterion, or it is not active"
        )
    # REQ-041: the develop-done pre-flight must read the live integration-branch ledger —
    # an unbound read from another branch sees a stale snapshot and falsely reports a
    # checkpointed develop step as "not closed" (REQ-040 Decision 1, finished here).
    if ex.live_ledger().status_of(f"{req_id}:develop") is not StepStatus.DONE:
        raise click.ClickException(
            f"{req_id}:develop is not closed yet — validation follows the develop "
            f"checkpoint (run `steward checkpoint {req_id} develop` first)"
        )
    # REQ-034 Decision 6: the bring-up path never spawns Claude from within Claude — refuse
    # early when already inside a Claude session, pointing at a plain terminal / the skill.
    if claude_mod.in_claude_session():
        raise click.ClickException(
            f"refusing to bring up a guided validation session from inside a Claude "
            f"session (CLAUDECODE set) — Claude is never spawned from within Claude. Open a "
            f"plain terminal tab and run `steward validate {req_id}` there, or drive the "
            f"validation in this session via the /system-test skill's start/record steps."
        )
    check_invariants(ex)  # REQ-049: refuse on production / mid-merge (raises; handled top-level)
    # REQ-034 Decision 6 (shape A): start → interactive guided bring-up (editor pattern) →
    # record. The routine readies/reconciles the branch (Decision 5) inside its start half.
    res = routine.guided_validate(
        ex, step, signoff=signoff, on_event=on_event, driver="interactive",
    )
    if res.outcome is RunOutcome.REFUSED:
        raise click.ClickException(res.detail)
    if res.outcome is RunOutcome.PARKED:
        click.echo(click.style(f"validation parked: {res.detail}", fg="yellow"))
        raise SystemExit(1)
    _print_report(ex, res)


# -- run (unattended) ---------------------------------------------------------


@main.command()
@click.argument("req_id", required=False, default=None)
@click.option("--pin", type=int, default=None, help="Pin one clauder account (drain its 7d budget); forwards `clauder gate --pin N`.")
@click.option("--threshold", type=float, default=None, help="Quota gate (fraction or percent; default 70).")
@click.option("--model", default=None, help="Claude model (default claude-opus-4-8).")
@click.option("--effort", default=None, help="Reasoning effort (default high).")
@click.option("--only", default=None, help="Restrict to one REQ's steps (fails if none eligible).")
@click.option("--max-steps", type=int, default=None, help="Stop after N steps.")
@click.option("--quiet", is_flag=True, help="Suppress live claude output; show only results.")
def run(
    req_id: str | None,
    pin: int | None, threshold: float | None, model: str | None, effort: str | None,
    only: str | None, max_steps: int | None, quiet: bool,
) -> None:
    """Unattended: march eligible steps headless; park on forks.

    Name a REQ positionally (``steward run REQ-NNN``) to restrict the run to that REQ's
    steps; it maps onto ``--only`` and the two may not both be given (REQ-042).

    A single Ctrl-C finishes the running step and then exits; a Ctrl-C during a quota wait
    ends it at once; a second Ctrl-C kills the running ``claude`` child (REQ-025).
    """
    target = _resolve_target(req_id, only)
    cfg = _load_or_die()
    ctrl = StopController()
    ctrl.install()
    ex = build_executor(
        cfg, pin=pin, threshold=threshold, model=model, effort=effort,
        announce=_stderr_announcer, stop=ctrl,
    )
    if target is None:
        _print_steer_hint(ex, "run")
    on_event = None if quiet else _stream_printer()
    results = ex.run(only=target, max_steps=max_steps, on_event=on_event)
    if not results:
        if target is not None:
            raise click.ClickException(ex.only_ineligibility_reason(target))
        click.echo("Nothing eligible to run.")
        return
    for res in results:
        _echo_result(res)
    parked = [r for r in results if r.outcome is RunOutcome.PARKED]
    if parked:
        click.echo(
            click.style(
                f"\n{len(parked)} fork(s) parked — see `steward decision list`.", fg="yellow"
            )
        )


def _echo_result(res: StepResult) -> None:
    if res.outcome is RunOutcome.REFUSED:
        click.echo(click.style(f"  REFUSED: {res.detail}", fg="red"))
        return
    color = {
        RunOutcome.DONE: "green",
        RunOutcome.PARKED: "yellow",
        RunOutcome.VERIFY_FAILED: "red",
        RunOutcome.FAILED: "red",
        RunOutcome.LIMIT: "yellow",
    }.get(res.outcome, "white")
    sha = f" @ {res.commit[:8]}" if res.commit else ""
    step_id = res.step.id if res.step else "—"
    click.echo(click.style(f"  {step_id}: {res.outcome.value}{sha}", fg=color))


def _print_report(ex, res: StepResult) -> None:
    """The fixed report: Did / Cursor / Review / Decisions / Next."""
    if res.outcome is RunOutcome.REFUSED:
        click.echo(click.style(f"\n✗ {res.detail}", fg="red"))
        return
    click.echo(click.style("\n── checkpoint report ──", bold=True))
    click.echo(f"Did:       {res.step.id} — {res.outcome.value}")
    if res.commit:
        click.echo(f"           committed {res.commit[:8]}")
    # REQ-041: report the live integration-branch cursor/decisions (REQ-040 Decision 1).
    led = ex.live_ledger()
    click.echo(f"Cursor:    {led.cursor_step or '—'}")
    if res.detail:
        click.echo(f"Review:    {res.detail.splitlines()[0]}")
    decisions = led.open_decisions()
    if decisions:
        click.echo("Decisions: " + ", ".join(f"{d.id} ({d.question})" for d in decisions))
    else:
        click.echo("Decisions: none parked")
    nxt = ex.next_eligible()
    click.echo(f"Next:      {nxt.id if nxt else '— nothing eligible'}")


# -- decision -----------------------------------------------------------------


@main.group()
def decision() -> None:
    """Inspect and resolve forks parked while running unattended."""


@decision.command("list")
def decision_list() -> None:
    cfg = _load_or_die()
    led = Ledger(cfg.root)
    open_d = led.open_decisions()
    if not open_d:
        click.echo("No parked decisions.")
        return
    for d in open_d:
        click.echo(f"{d.id}  [{d.step}]")
        click.echo(f"    {d.question}")
        if d.options:
            click.echo("    options: " + ", ".join(d.options))


@decision.command("answer")
@click.argument("decision_id")
@click.argument("answer")
def decision_answer(decision_id: str, answer: str) -> None:
    cfg = _load_or_die()
    ex = build_executor(cfg)
    # REQ-049 AC3: answering a parked decision succeeds regardless of HEAD — the historical
    # stranding (a parked decision stuck on the wrong branch, no command able to recover it)
    # is unreachable: single-ledger (INV-1) only, no branch/tree gate.
    check_invariants(ex, allow_any_head=True)
    d = ex.ledger.find_decision(decision_id)
    if d is None or d.status is not DecisionStatus.OPEN:
        raise click.ClickException(f"no open decision {decision_id}")
    # REQ-057 Decision 5: a validation-phase hold is *not* a fork to answer here. A `manual`-AC
    # await (state F) or a red validation parks on a `:validate` step and has dedicated verbs.
    # Answering it would flip the validate step BLOCKED -> PENDING; unattended it re-runs, still
    # can't reach the human, and re-parks — the circular trap REQ-056 removed for D/H. Refuse
    # *before* any mutation (so the step stays BLOCKED, no re-park) and redirect to the real verb.
    if d.step.endswith(":validate"):
        req = d.req or d.step.split(":", 1)[0]
        raise click.ClickException(
            f"{decision_id} is a validation hold on {d.step}, not a fork to answer. "
            f"Record the human sign-off with `steward validate {req}` "
            f"(or, for a red validation, `steward rework {req}` / `steward revalidate {req}`)."
        )
    with transaction(ex.git, label=f"decision answer {decision_id}"):
        d = ex.ledger.answer_decision(decision_id, answer)
    click.echo(f"Answered {decision_id}; {d.step} unblocked. Run `steward run` to resume.")


# -- init (ledger only) -------------------------------------------------------


@main.command()
@click.option("--profile", default="req", show_default=True)
def init(profile: str) -> None:
    """Initialize a ledger in the current directory (without stamping templates)."""
    root = Path.cwd()
    if (root / ".devsteward" / "state.yaml").exists():
        raise click.ClickException("ledger already initialized here")
    Ledger.init(root, profile=profile)
    click.echo(f"Initialized .devsteward/ ({profile} profile) in {root}")


# -- seed-ledger (onboard an already-built corpus) ----------------------------


@main.command(name="seed-ledger")
def seed_ledger_cmd() -> None:
    """Mark every terminal REQ's phase-step(s) done — seed a ledger for built history.

    For onboarding an already-finished project (REQ-022): run after the per-project
    converter has produced schema-valid REQs. Reads only frontmatter (id, status), so it is
    dialect-independent and idempotent. Requires an already-initialized ledger.
    """
    from .profiles.req.seed import seed_ledger

    cfg = _load_or_die()
    seeded = seed_ledger(Ledger(cfg.root), cfg.req_dir)
    if seeded:
        click.echo(f"Seeded {len(seeded)} terminal REQ(s): {', '.join(seeded)}")
    else:
        click.echo("Nothing to seed (no un-seeded terminal REQs).")


if __name__ == "__main__":
    main()
