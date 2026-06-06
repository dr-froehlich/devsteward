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
from .core.model import StepStatus
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
                StepStatus.RUNNING: click.style("…", fg="cyan"),
            }.get(st, "•")
            tag = click.style(" (eligible)", fg="cyan") if s.id in eligible else ""
            click.echo(f"  {mark} {s.id:<22} {st.value}{tag}")

    decisions = led.open_decisions()
    if decisions:
        click.echo(click.style("\nparked decisions:", fg="yellow"))
        for d in decisions:
            click.echo(f"  {d.id} [{d.step}] {d.question}")


# -- advance (attended) -------------------------------------------------------


@main.command()
@click.option("--use", type=int, default=None, help="Pin a claude-swap account index.")
def advance(use: int | None) -> None:
    """Attended: do exactly one checkpoint, then print the fixed report."""
    cfg = _load_or_die()
    ex = build_executor(cfg, use=use)
    res = ex.advance_once(unattended=False)
    if res is None:
        click.echo("Nothing eligible — every step is done, blocked, or waiting on a dep.")
        return
    _print_report(ex, res)


# -- run (unattended) ---------------------------------------------------------


@main.command()
@click.option("--use", type=int, default=None, help="Pin a claude-swap account index.")
@click.option("--max-steps", type=int, default=None, help="Stop after N steps.")
def run(use: int | None, max_steps: int | None) -> None:
    """Unattended: march eligible steps headless; park on forks."""
    cfg = _load_or_die()
    ex = build_executor(cfg, use=use)
    results = ex.run(max_steps=max_steps)
    if not results:
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
    color = {
        RunOutcome.DONE: "green",
        RunOutcome.PARKED: "yellow",
        RunOutcome.VERIFY_FAILED: "red",
        RunOutcome.FAILED: "red",
        RunOutcome.LIMIT: "yellow",
    }.get(res.outcome, "white")
    sha = f" @ {res.commit[:8]}" if res.commit else ""
    click.echo(click.style(f"  {res.step.id}: {res.outcome.value}{sha}", fg=color))


def _print_report(ex, res: StepResult) -> None:
    """The fixed report: Did / Cursor / Review / Decisions / Next."""
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
