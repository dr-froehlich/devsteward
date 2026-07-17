"""steward — the DevSteward command-line interface."""

from __future__ import annotations

import os
import shutil
import subprocess
from datetime import date
from importlib.resources import files
from pathlib import Path

import click

from . import __version__, cache as cache_mod, skillsync
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
        # REQ-036/066: engine-owned stamped artifacts (the bundled skills and the root
        # STEWARD.md manual) are pure engine *behavior* and must byte-match the template they
        # were stamped from (the drift model's whole premise) — copy them verbatim, never
        # substituting. A skill like bootstrap carries `{{TODAY}}` as literal instruction
        # text, so substituting there would both corrupt the instruction and break every
        # drift comparison.
        is_skill = rel.parts[: len(skillsync.SKILLS_RELDIR.parts)] == skillsync.SKILLS_RELDIR.parts
        if is_skill or rel == Path(skillsync.MANUAL_FILENAME):
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


# -- cache (session prompt-cache warmth) --------------------------------------


@main.command()
@click.option(
    "--ttl",
    "ttl_minutes",
    type=int,
    metavar="MINUTES",
    default=cache_mod.DEFAULT_TTL_MINUTES,
    show_default=True,
    help="Assumed prompt-cache TTL in minutes (pass 5 when a usage-limit overage applies).",
)
@click.pass_context
def cache(ctx: click.Context, ttl_minutes: int) -> None:
    """Is this project's Claude session still cache-warm? (0 = warm, 1 = cold, 2 = none.)

    Reports how long ago the newest Claude Code session transcript for this project was
    written, and whether the prompt cache is warm under the assumed TTL (REQ-082). The
    verdict is computed purely from the filesystem — the newest transcript's mtime under
    `$CLAUDE_PROJECTS_DIR/<slug>/` (default `~/.claude/projects/`) — so running it from a
    second shell never touches the session or its cache, which asking inside the session
    would. Read-only and ledger-free: it works in any directory and writes nothing.
    """
    report = cache_mod.probe(ttl_minutes=ttl_minutes)
    if not report.found:
        click.echo(
            click.style(
                f"no Claude session transcript for this project — looked in "
                f"{report.session_dir}",
                fg="yellow",
            ),
            err=True,
        )
        ctx.exit(report.exit_code)
    verdict = (
        click.style("WARM", fg="green") if report.warm else click.style("cold", fg="red")
    )
    click.echo(
        f"{report.session_id}  last write {report.age_minutes:.0f}m ago  "
        f"{verdict} (ttl {report.ttl_minutes}m)"
    )
    click.echo(click.style(cache_mod.INVALIDATION_CAVEAT, fg="yellow"))
    ctx.exit(report.exit_code)


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


@main.command()
@click.argument("req_id")
def reland(req_id: str) -> None:
    """Replay REQ_ID's mechanical land after a land-gate refusal — no re-validation (REQ-065).

    The cheap recovery edge for a validate step left FAILED by a land-gate refusal (a missing
    concept doc / plan): the session already ran and its sign-offs are durable in the green
    validation event, so once the formality is fixed this re-certifies that same green and
    lands — no re-prompting, no re-run. Narrow preconditions: REQ_ID:validate is FAILED and
    its last events are a green validation followed by a land_refused. For a *red* validation
    use `steward revalidate`; for a develop step use `steward repeat`.
    """
    cfg = _load_or_die()
    ctrl = StopController()
    ctrl.install()
    ex = build_executor(cfg, announce=_stderr_announcer, stop=ctrl)
    routine = ex.validate_runner
    if routine is None:
        raise click.ClickException("the generic profile has no validation phase")
    check_invariants(ex)  # REQ-049: refuse on production / mid-merge before any write
    # REQ-049: the replayed land is atomic — a git failure mid-commit rolls repo + ledger back.
    with transaction(ex.git, label=f"reland {req_id}"):
        res = routine.reland(ex, req_id, driver="interactive")
    if res.outcome is RunOutcome.REFUSED:
        raise click.ClickException(res.detail)
    if res.outcome is RunOutcome.FAILED:
        raise click.ClickException(res.detail)
    if res.outcome is RunOutcome.VERIFY_FAILED:
        raise click.ClickException(f"reland could not land — {res.detail}")
    _print_report(ex, res)


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
            # REQ-074: a live ledger hold (a non-fork wait naming its own verb) takes
            # precedence over the static profile note.
            note = ""
            hold = led.hold_note(s.id) if st is StepStatus.BLOCKED else ""
            if hold:
                note = click.style(f"  ⏳ {hold.splitlines()[0]}", fg="yellow")
            elif s.blocked_note and s.id not in eligible and st is not StepStatus.DONE:
                note = click.style(f"  ⏳ {s.blocked_note}", fg="yellow")
            elif st is StepStatus.FAILED:
                # REQ-056 Decision 4: a FAILED step names its own forward verb. D, H, and the
                # pre-existing FAILED states (A/B/G) now carry the next-action hint the parked
                # -decision line used to give — `steward repeat REQ` re-runs against the tree.
                note = click.style(f"  → steward repeat {s.req or s.id}", fg="red")
            click.echo(f"  {mark} {s.id:<22} {st.value}{tag}{note}")

    decisions = led.open_decisions()
    if decisions:
        click.echo(click.style("\nparked forks:", fg="yellow"))
        for d in decisions:
            click.echo(f"  {d.id} [{d.step}] {d.question}")
        click.echo(
            "  resolve in a guided session: `steward decide DEC-NNN` (plain shell)"
        )

    # REQ-036 Decision 3 / REQ-066 Decision 3: a stamped engine-owned artifact (a bundled
    # skill or the STEWARD.md manual) drifting from the installed engine is an informational
    # warning — visible (the fix for "silent"), never a blocking gate; the hint names the
    # generalized `steward sync` verb.
    drifted = skillsync.drift(cfg.root, _package_templates())
    if drifted:
        click.echo(click.style("\nstamped artifacts:", fg="yellow"))
        for d in drifted:
            click.echo(
                click.style(f"  ⚠ {d.name:<14} {d.bucket.value}", fg="yellow")
                + "  — run `steward sync`"
            )


# -- sync (engine-owned stamped-artifact drift) -------------------------------


@main.command("sync")
@click.option(
    "--force", is_flag=True,
    help="Refresh a *customized* artifact too, backing the local copy up (.orig) first.",
)
def sync(force: bool) -> None:
    """Refresh stale/missing engine-owned stamped artifacts from the template (REQ-036/066).

    Covers the bundled skills **and** the root ``STEWARD.md`` manual. A *stale* artifact
    (untouched since stamp, template advanced) or a *missing* one (e.g. a consumer that never
    had ``STEWARD.md``) is refreshed to byte-match the installed engine and the provenance
    lock updated. A *customized* artifact (edited locally) is left untouched and reported
    unless ``--force`` is given, in which case its current bytes are backed up to
    ``<name>.orig`` before the refresh. ``sync-skills`` is a back-compat alias.
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
        click.echo(click.style("all engine-owned artifacts in-sync.", fg="green"))


# REQ-066 Decision 3: keep the pre-rename verb working for muscle memory and any scripted or
# documented `sync-skills` invocations (older stamped copies, handbook prose) — a true alias
# to the same command, not a re-implementation.
main.add_command(sync, name="sync-skills")


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
@click.argument("words", nargs=-1, required=True, metavar="[start|record] REQ_ID")
@click.option("--quiet", is_flag=True, help="Suppress live claude output; show only the report.")
def validate(words: tuple[str, ...], quiet: bool) -> None:
    """Run REQ_ID's System-Test phase — the single entry point (REQ-030).

    Three forms. ``steward validate REQ-NNN`` (shape A, from a plain shell): the fresh
    System Tester session preps the lab and captures artifacts, the engine runs each
    ``artifact`` AC's named test itself, ``manual`` ACs take your sign-off here, and on
    green the REQ lands mechanically (flip, index, commit). On a **done** REQ it appends
    a fresh dated evidence event and leaves the REQ file untouched — status *and*
    ``verified_by`` stay the frozen landing provenance (re-run policy, REQ-030 Decision 5
    as clarified by REQ-035). A red validation parks with the failure brief — no repair loop.

    The warm cycle (REQ-081) splits the same flow into its two REQ-034 halves so the
    System-Tester session survives a red: ``steward validate start REQ-NNN`` opens the
    step and readies the evidence dir (callable from inside the warm session — it spawns
    nothing); the guided work and capture happen there; then ``steward validate record
    REQ-NNN`` from a **second plain shell** runs the artifact gate, takes the human
    verdict via the engine's interactive prompt, and routes the same three outcomes.
    After a red, run the rework from that shell — the warm session re-runs ``start``.
    """
    if len(words) == 1 and words[0] not in ("start", "record"):
        req_id = words[0]
    elif len(words) == 2 and words[0] in ("start", "record"):
        if words[0] == "start":
            _validate_start(words[1])
        else:
            _validate_record(words[1])
        return
    else:
        raise click.UsageError(
            "usage: steward validate REQ-NNN  |  steward validate start REQ-NNN  |  "
            "steward validate record REQ-NNN"
        )
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
        # REQ-073 D2 recovery: a done REQ still surfacing an open :validate decision is a
        # diverged ledger (a stale save rewound the cursor behind the committed land). Close
        # it here — the verb the REQ-057 `decision answer` guard already redirects to — before
        # the (non-mutating) re-validation, so the two remedies terminate instead of looping.
        # HEAD-agnostic like `decision answer` (single-ledger invariant only): recovery must
        # not depend on which branch is checked out.
        check_invariants(ex, allow_any_head=True)
        with transaction(ex.git, label=f"reconcile stale validation {req_id}"):
            recovered = routine.reconcile_stale_validation_decision(ex.ledger, req_id)
        if recovered:
            ids = ", ".join(d.id for d in recovered)
            click.echo(click.style(
                f"reconciled stale validation decision(s) {ids} on {req_id} from the event "
                f"log — status and verified_by stay the frozen landing provenance. No "
                f"hand-edit of state.yaml.", fg="green"
            ))
            return
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
    # early when already inside a Claude session, pointing at a plain terminal or the
    # warm-cycle halves (REQ-081).
    if claude_mod.in_claude_session():
        raise click.ClickException(
            f"refusing to bring up a guided validation session from inside a Claude "
            f"session (CLAUDECODE set) — Claude is never spawned from within Claude. Open a "
            f"plain terminal tab and run `steward validate {req_id}` there, or drive it "
            f"warm (REQ-081): `steward validate start {req_id}` in this session, capture "
            f"the evidence here, then record the verdict from a plain shell with "
            f"`steward validate record {req_id}`."
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


def _validate_start(req_id: str) -> None:
    """The standalone **start** half (REQ-081): open the validate step and ready the
    evidence dir, spawning nothing.

    Callable from inside a Claude session — the warm System-Tester session *is* the
    session, so there is no bring-up and no CLAUDECODE refusal. Everything else mirrors
    shape A's pre-flight: develop must be checkpointed, the declared lab done, and the
    REQ-065 formality gate clear (both live inside ``routine.start``)."""
    cfg = _load_or_die()
    ex = build_executor(cfg, announce=_stderr_announcer)
    routine = ex.validate_runner
    if routine is None:
        raise click.ClickException("the generic profile has no validation phase")
    from .profiles.req.reqfile import load_reqs

    req = next((r for r in load_reqs(cfg.req_dir) if r.id == req_id), None)
    if req is None:
        raise click.ClickException(f"{req_id}: no such requirement")
    if req.status == "done":
        raise click.ClickException(
            f"{req_id} is done — a fresh re-validation is `steward validate {req_id}` "
            f"from a plain shell (REQ-035: provenance stays frozen)"
        )
    step = ex.step_by_id(f"{req_id}:validate")
    if step is None:
        raise click.ClickException(
            f"{req_id} has no validate step — it declares no artifact/manual acceptance "
            f"criterion, or it is not active"
        )
    # REQ-041: the develop-done pre-flight reads the live ledger (as in shape A).
    if ex.live_ledger().status_of(f"{req_id}:develop") is not StepStatus.DONE:
        raise click.ClickException(
            f"{req_id}:develop is not closed yet — validation follows the develop "
            f"checkpoint (run `steward checkpoint {req_id} develop` first)"
        )
    status = ex.ledger.status_of(step.id)
    # PENDING opens fresh; RUNNING is the clean re-entry (a fresh dated dir, mirroring
    # shape A's re-entry after a killed session). Anything else routes elsewhere.
    if status not in (StepStatus.PENDING, StepStatus.RUNNING):
        raise click.ClickException(
            f"{step.id} is {status.value} — nothing to start. A parked red returns via "
            f"`steward rework {req_id}` / `steward revalidate {req_id}`; a failed step "
            f"via `steward repeat {req_id}`."
        )
    check_invariants(ex)  # REQ-049: refuse on production / mid-merge
    ctx = routine.start(ex, step)
    if isinstance(ctx, StepResult):
        raise click.ClickException(ctx.detail)
    click.echo(click.style(f"validation started: {step.id}", fg="green"))
    click.echo(f"evidence dir: {ctx.evidence_rel}")
    if ctx.reval is not None and ctx.reval.get("scope"):
        click.echo(f"scoped re-run (REQ-075): {', '.join(ctx.reval['scope'])}")
    click.echo(
        "capture the validation artifacts there, then record the verdict from a plain "
        f"shell: steward validate record {req_id}"
    )


def _validate_record(req_id: str) -> None:
    """The standalone **record** half (REQ-081): grade what the started validation
    captured and take the human verdict — from a plain shell, while the System-Tester
    session stays warm.

    The verdict channel is the engine's interactive prompt and nothing else (REQ-034
    Decision 2: the session never collects, relays, or asserts it) — so when a fresh
    ``manual`` AC needs a verdict and we are inside a Claude session (no terminal to
    prompt on, and the session must never relay the verdict), record refuses instead of
    aborting mid-transaction."""
    cfg = _load_or_die()
    ex = build_executor(cfg, announce=_stderr_announcer)
    routine = ex.validate_runner
    if routine is None:
        raise click.ClickException("the generic profile has no validation phase")
    ctx = routine.resume_context(ex, req_id)
    if isinstance(ctx, StepResult):
        raise click.ClickException(ctx.detail)
    carried_ids = {c["ac"] for c in (ctx.reval.get("carried") if ctx.reval else []) or []}
    fresh_manual = [
        c for c in ctx.req.acceptance if c.check == "manual" and c.id not in carried_ids
    ]
    if fresh_manual and claude_mod.in_claude_session():
        raise click.ClickException(
            f"{req_id} has manual AC(s) awaiting a human verdict — the verdict is taken "
            f"only by the engine's interactive prompt, which a Claude session cannot host "
            f"(and the session must never relay it). Run `steward validate record "
            f"{req_id}` from a plain shell; this warm session stays as it is."
        )
    check_invariants(ex)  # REQ-049: refuse on production / mid-merge
    # REQ-049: the record/land/park is atomic, exactly as shape A's record half.
    with transaction(ex.git, label=f"validate {req_id}"):
        res = routine.record(
            ex, ctx, signoff=_interactive_signoff(cfg.root), driver="interactive"
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
        # REQ-074: a parked result is either a genuine fork (an open decision — the
        # guided `steward decide` session resolves it) or a hold naming its own verb.
        parked_steps = {r.step.id for r in parked if r.step}
        forks = [
            d for d in ex.live_ledger().open_decisions() if d.step in parked_steps
        ]
        held = len(parked) - len(forks)
        if forks:
            ids = ", ".join(d.id for d in forks)
            click.echo(
                click.style(
                    f"\n{len(forks)} fork(s) parked — resolve with `steward decide "
                    f"{ids if len(forks) == 1 else 'DEC-NNN'}` (see `steward decision list`).",
                    fg="yellow",
                )
            )
        if held:
            click.echo(
                click.style(
                    f"\n{held} step(s) held — see `steward status` for each hold's verb.",
                    fg="yellow",
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
        # REQ-074: render the fork brief so the operator is briefed, not just questioned.
        if d.context:
            for ln in d.context.splitlines():
                click.echo(f"    {ln}")
        for i, opt in enumerate(d.options, 1):
            click.echo(f"    option {i}: {opt}")
        if d.recommendation:
            click.echo(f"    recommendation: {d.recommendation}")
        click.echo(f"    → resolve with `steward decide {d.id}` (plain shell)")


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


def _fork_briefing_prompt(d) -> str:
    """The initial prompt for the guided `steward decide` session (REQ-074): brief the
    operator on the parked fork and support the live interrogation. The session advises;
    the **engine** records the choice after it exits (editor pattern — no self-certify)."""
    lines = [
        f"A steward run parked a genuine fork on step {d.step} ({d.id}) — the autopilot "
        f"raised the captain. Brief the operator and help them decide. Do NOT edit the "
        f"ledger or answer the decision yourself: the engine records the operator's "
        f"choice after this session ends.",
        "",
        f"Question: {d.question}",
    ]
    if d.context:
        lines += ["", "Context from the parked session:", d.context]
    if d.options:
        lines += ["", "Options as the parked session saw them:"]
        lines += [f"  {i}. {opt}" for i, opt in enumerate(d.options, 1)]
    if d.recommendation:
        lines += ["", f"The parked session's recommendation: {d.recommendation}"]
    lines += [
        "",
        f"Start by reading the REQ ({d.req or 'see the step id'}) and the relevant code, "
        f"present the fork in the operator's terms, answer their questions, and give a "
        f"clear recommendation with rationale. When the operator is ready to decide, they "
        f"exit this session; the engine then takes their choice.",
    ]
    return "\n".join(lines)


@main.command()
@click.argument("decision_id")
def decide(decision_id: str) -> None:
    """Resolve a parked fork in a guided attended session (REQ-074).

    The resolution half of park-and-surface: brings up an interactive session that briefs
    you on the fork (question, context, options, the parked session's recommendation),
    supports live interrogation, and — after the session exits — records *your* choice and
    rationale (editor pattern; the session cannot self-certify). The answered fork is
    delivered into the resuming step's prompt; run `steward run` to continue.
    """
    cfg = _load_or_die()
    ex = build_executor(cfg)
    check_invariants(ex, allow_any_head=True)  # single-ledger only, like `decision answer`
    if os.environ.get("DEVSTEWARD_UNATTENDED"):
        raise click.ClickException(
            "steward decide is the attended resolution of a parked fork — it cannot run "
            "unattended (DEVSTEWARD_UNATTENDED is set). Run it from a plain shell."
        )
    if claude_mod.in_claude_session():
        raise click.ClickException(
            f"refusing to bring up a guided decision session from inside a Claude session "
            f"(CLAUDECODE set) — Claude is never spawned from within Claude. Open a plain "
            f"terminal tab and run `steward decide {decision_id}` there."
        )
    d = ex.ledger.find_decision(decision_id)
    if d is None or d.status is not DecisionStatus.OPEN:
        raise click.ClickException(f"no open decision {decision_id}")
    if d.step.endswith(":validate"):
        req = d.req or d.step.split(":", 1)[0]
        raise click.ClickException(
            f"{decision_id} is a legacy validation hold on {d.step}, not a fork to decide. "
            f"Record the human sign-off with `steward validate {req}` "
            f"(or, for a red validation, `steward rework {req}` / `steward revalidate {req}`)."
        )
    code = claude_mod.run_claude_interactive(
        _fork_briefing_prompt(d),
        argv_prefix=ex.accounts.claude_argv(),
        cwd=str(ex.root),
    )
    if code != 0:
        click.echo(click.style(
            f"guided session exited non-zero ({code}) — taking your verdict anyway; "
            f"abort with Ctrl-C to leave {decision_id} parked.", fg="yellow"
        ))
    # The engine records the choice (editor pattern). Numbered options, or free text.
    click.echo(click.style(f"\n{decision_id}:", bold=True) + f" {d.question}")
    for i, opt in enumerate(d.options, 1):
        click.echo(f"  {i}. {opt}")
    raw = click.prompt(
        "Your choice — option number or free text (empty to leave parked)",
        default="", show_default=False,
    ).strip()
    if not raw:
        click.echo(f"{decision_id} stays parked.")
        return
    answer = raw
    if d.options and raw.isdigit() and 1 <= int(raw) <= len(d.options):
        answer = d.options[int(raw) - 1]
    rationale = click.prompt(
        "Rationale (one line; empty to skip)", default="", show_default=False
    ).strip()
    with transaction(ex.git, label=f"decide {decision_id}"):
        d = ex.ledger.answer_decision(decision_id, answer, rationale=rationale or None)
    click.echo(click.style(
        f"Decided {decision_id}: {answer}\n{d.step} unblocked — the choice travels into "
        f"the resuming session. Run `steward run` to continue.", fg="green"
    ))


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
