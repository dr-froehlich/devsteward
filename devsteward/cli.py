"""steward — the DevSteward command-line interface."""

from __future__ import annotations

import shutil
import subprocess
from datetime import date
from importlib.resources import files
from pathlib import Path

import click

from . import __version__
from .build import build_executor
from .config import Config, ProjectNotFound, load_config
from .core.executor import RunOutcome, StepResult
from .core.ledger import Ledger
from .core.stop import StopController
from .core.model import StepStatus
from .lifecycle import LifecycleError, activate as lifecycle_activate, recover as lifecycle_recover
from .lint import lint as run_lint


def _package_templates() -> Path:
    return Path(str(files("devsteward"))) / "templates"


def _load_or_die() -> Config:
    try:
        return load_config()
    except ProjectNotFound as exc:
        raise click.ClickException(str(exc)) from exc


@click.group()
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


# -- lifecycle (activate / recover) -------------------------------------------


@main.command()
@click.argument("req_id")
def activate(req_id: str) -> None:
    """Flip REQ_ID from draft (or dropped) to open, syncing its index row; uncommitted.

    One verb for one logical action — it edits the REQ frontmatter and the
    ``REQUIREMENTS_INDEX.md`` row in lockstep so ``steward lint`` stays green, leaving both
    files for you to commit deliberately. Refuses done/superseded REQs (supersede instead).
    """
    cfg = _load_or_die()
    try:
        res = lifecycle_activate(cfg, req_id)
    except LifecycleError as exc:
        raise click.ClickException(str(exc)) from exc
    color = "green" if res.changed else "yellow"
    click.echo(click.style(res.message, fg=color))


@main.command()
@click.argument("req_id")
def recover(req_id: str) -> None:
    """Re-arm REQ_ID's failed step so the next run re-attempts it (its partial work intact).

    Flips the REQ's FAILED ledger step(s) to RECOVER and records an event; the working tree
    is left exactly as the failed attempt left it, for the resuming skill to assess. Fails
    (non-zero) when the REQ has no failed step.
    """
    cfg = _load_or_die()
    led = Ledger(cfg.root)
    try:
        res = lifecycle_recover(led, req_id)
    except LifecycleError as exc:
        raise click.ClickException(str(exc)) from exc
    flipped = ", ".join(res.steps)
    click.echo(
        click.style(
            f"recovered {req_id}: {flipped} -> recover. Re-run `steward run` to re-attempt.",
            fg="green",
        )
    )


# -- status -------------------------------------------------------------------


@main.command()
def status() -> None:
    """Show the ledger cursor, eligible/blocked steps, and parked decisions."""
    cfg = _load_or_die()
    ex = build_executor(cfg)
    led = ex.ledger
    click.echo(f"profile: {led.profile}    cursor: {led.cursor_step or '—'}")

    steps = ex.steps()
    if not steps:
        click.echo("no active steps (all requirements done, draft, or none defined).")
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
            click.echo(f"  {mark} {s.id:<22} {st.value}{tag}")

    decisions = led.open_decisions()
    if decisions:
        click.echo(click.style("\nparked decisions:", fg="yellow"))
        for d in decisions:
            click.echo(f"  {d.id} [{d.step}] {d.question}")


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


@main.command()
@click.option("--use", type=int, default=None, help="Pin a claude-swap account index.")
@click.option("--threshold", type=float, default=None, help="Quota gate (fraction or percent; default 70).")
@click.option("--model", default=None, help="Claude model (default claude-opus-4-8).")
@click.option("--effort", default=None, help="Reasoning effort (default high).")
@click.option("--only", default=None, help="Restrict to one REQ's steps (fails if none eligible).")
@click.option("--quiet", is_flag=True, help="Suppress live claude output; show only the report.")
def advance(
    use: int | None, threshold: float | None, model: str | None, effort: str | None,
    only: str | None, quiet: bool,
) -> None:
    """Do exactly one checkpoint headless, then print the fixed report.

    Like ``run`` this drives ``claude -p`` (no interactive client), so forks
    park-and-surface — there is no human channel for ``AskUserQuestion`` here.
    Resolve any parked fork with ``steward decision answer`` and re-run.
    """
    cfg = _load_or_die()
    ctrl = StopController()
    ctrl.install()
    ex = build_executor(
        cfg, use=use, threshold=threshold, model=model, effort=effort,
        announce=_stderr_announcer, stop=ctrl,
    )
    on_event = None if quiet else _stream_printer()
    res = ex.advance_once(only=only, unattended=True, on_event=on_event)
    if res is None:
        if only is not None:
            raise click.ClickException(ex.only_ineligibility_reason(only))
        click.echo("Nothing eligible — every step is done, blocked, or waiting on a dep.")
        return
    _print_report(ex, res)


# -- checkpoint (interactive land tail) ---------------------------------------


@main.command()
@click.argument("req_id")
@click.argument("phase", default="develop")
def checkpoint(req_id: str, phase: str) -> None:
    """Verify, flip the REQ done, commit, and advance the ledger — one transaction.

    The interactive ``/advance`` skill does the thinking and leaves the tree dirty; this
    runs the engine's verify → flip-done → commit → advance tail (no ``claude`` call), so
    the frontmatter ``done``, the index row, the commit, and the ledger checkpoint can no
    longer drift apart. Use it in place of hand-editing ``state.yaml``.
    """
    cfg = _load_or_die()
    ex = build_executor(cfg)
    step_id = f"{req_id}:{phase}"
    step = ex.step_by_id(step_id)
    if step is None:
        raise click.ClickException(
            f"{step_id} is not a derivable step — is {req_id} active (not draft/done) and "
            f"is the phase 'develop'?"
        )
    res = ex.checkpoint(step)
    if res.outcome is RunOutcome.REFUSED:
        raise click.ClickException(res.detail)
    if res.outcome is RunOutcome.VERIFY_FAILED:
        raise click.ClickException(f"verify failed — not checkpointed:\n{res.detail}")
    _print_report(ex, res)


# -- run (unattended) ---------------------------------------------------------


@main.command()
@click.option("--use", type=int, default=None, help="Pin a claude-swap account index.")
@click.option("--threshold", type=float, default=None, help="Quota gate (fraction or percent; default 70).")
@click.option("--model", default=None, help="Claude model (default claude-opus-4-8).")
@click.option("--effort", default=None, help="Reasoning effort (default high).")
@click.option("--only", default=None, help="Restrict to one REQ's steps (fails if none eligible).")
@click.option("--max-steps", type=int, default=None, help="Stop after N steps.")
@click.option("--quiet", is_flag=True, help="Suppress live claude output; show only results.")
def run(
    use: int | None, threshold: float | None, model: str | None, effort: str | None,
    only: str | None, max_steps: int | None, quiet: bool,
) -> None:
    """Unattended: march eligible steps headless; park on forks.

    A single Ctrl-C finishes the running step and then exits; a Ctrl-C during a quota wait
    ends it at once; a second Ctrl-C kills the running ``claude`` child (REQ-025).
    """
    cfg = _load_or_die()
    ctrl = StopController()
    ctrl.install()
    ex = build_executor(
        cfg, use=use, threshold=threshold, model=model, effort=effort,
        announce=_stderr_announcer, stop=ctrl,
    )
    on_event = None if quiet else _stream_printer()
    results = ex.run(only=only, max_steps=max_steps, on_event=on_event)
    if not results:
        if only is not None:
            raise click.ClickException(ex.only_ineligibility_reason(only))
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
    click.echo(f"Cursor:    {ex.ledger.cursor_step or '—'}")
    if res.detail:
        click.echo(f"Review:    {res.detail.splitlines()[0]}")
    decisions = ex.ledger.open_decisions()
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
    led = Ledger(cfg.root)
    d = led.answer_decision(decision_id, answer)
    if d is None:
        raise click.ClickException(f"no open decision {decision_id}")
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


if __name__ == "__main__":
    main()
