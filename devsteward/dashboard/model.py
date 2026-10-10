"""Read-only derivations for the dashboard (REQ-097) — no web framework in here.

Everything a page shows is computed here from the same primitives the CLI reads: the
executor's derived steps and eligibility (``steward status``), the ledger's holds and parked
decisions, the backlog standings (``steward backlog-list``), and git's porcelain. Nothing is
cached and nothing is stored — the working tree the sessions use is the only source.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import skillsync
from ..build import build_executor
from ..config import Config, load_config
from ..core.model import Decision, StepStatus
from ..profiles.req import backlog as bl
from ..profiles.req.reqfile import ReqFile, load_reqs
# Discovery (Decision 7) lives in :mod:`devsteward.projects` since REQ-101, shared with the
# joint-task verbs; re-exported here, where the app and the tests read it.
from ..projects import ProjectRef, resolve_root, scan_root  # noqa: F401

# -- steward status (the model behind the CLI's report) ------------------------------


#: The one-glyph status marks ``steward status`` prints, kept identical so the page reads
#: like the terminal.
MARKS = {
    StepStatus.DONE.value: "✓",
    StepStatus.BLOCKED.value: "⏸",
    StepStatus.FAILED.value: "✗",
    StepStatus.RECOVER.value: "↻",
    StepStatus.RUNNING.value: "…",
    StepStatus.PENDING.value: "•",
}


@dataclass
class StepView:
    id: str
    req: str
    phase: str
    status: str
    eligible: bool
    note: str = ""
    attended: bool = False
    title: str = ""
    #: Verbs the page offers for this step — display hints only. The engine's own
    #: preconditions decide; a refused action renders the CLI's refusal (Decision 5).
    actions: list[str] = field(default_factory=list)
    #: A shell/session command the operator must run themselves (never an action).
    shell: str = ""

    @property
    def mark(self) -> str:
        return MARKS.get(self.status, "•")


@dataclass
class StatusView:
    profile: str
    cursor: str | None
    steps: list[StepView]
    decisions: list[Decision]
    drift: list[tuple[str, str]]
    #: The caught-up line ``steward status`` prints when no step is derived.
    terminal: str | None
    drafts: list[str]

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.steps:
            out[s.status] = out.get(s.status, 0) + 1
        return out


def project_status(cfg: Config, templates_root: Path | None = None,
                   reqs: list[ReqFile] | None = None) -> StatusView:
    """Derive what ``steward status`` reports for ``cfg``'s project, as data.

    Built from the same calls the CLI makes — the executor's ``steps()`` and
    ``eligible_steps()``, the live ledger's statuses, holds and open decisions, and the
    stamped-artifact drift — so the page and the terminal cannot disagree.
    """
    if reqs is None:
        reqs = load_reqs(cfg.req_dir) if cfg.req_dir.exists() else []
    ex = build_executor(cfg, reqs=reqs)  # one parse per page load (see build_executor)
    led = ex.live_ledger()
    steps = ex.steps()
    eligible = {s.id for s in ex.eligible_steps()}
    drafts = [r.id for r in reqs if r.status == "draft"]

    cursor = led.cursor_step
    if cursor and cursor not in {s.id for s in steps}:
        cursor = None  # REQ-060: a cursor pinned to a done step is misleading — suppress

    terminal: str | None = None
    if not steps:
        terminal = (
            "all active requirements done — activate a waiting draft with `steward activate REQ-NNN`."
            if drafts
            else "all requirements done — nothing to do; add the next with `/intake`."
        )

    views: list[StepView] = []
    for s in steps:
        st = led.status_of(s.id)
        note = ""
        hold = led.hold_note(s.id) if st is StepStatus.BLOCKED else ""
        if hold:
            note = hold.splitlines()[0]
        elif s.blocked_note and s.id not in eligible and st is not StepStatus.DONE:
            note = s.blocked_note
        view = StepView(
            id=s.id, req=s.req or s.id.split(":", 1)[0], phase=s.phase or "",
            status=st.value, eligible=s.id in eligible, note=note, attended=s.attended,
            title=s.title,
        )
        view.actions, view.shell = _offer(view, led)
        views.append(view)

    drift: list[tuple[str, str]] = []
    if templates_root is not None:
        try:
            drift = [
                (d.name, d.bucket.value)
                for d in skillsync.drift(cfg.root, templates_root, cfg.requirements_dir)
            ]
        except Exception as exc:  # noqa: BLE001 — drift is informational, never fatal
            drift = [("(drift check failed)", str(exc))]

    return StatusView(
        profile=led.profile, cursor=cursor, steps=views, decisions=led.open_decisions(),
        drift=drift, terminal=terminal, drafts=drafts,
    )


def _offer(view: StepView, led) -> tuple[list[str], str]:
    """Which CLI verbs the page offers on a step, and which command is the operator's own.

    Mirrors the hints ``steward status`` prints, which since REQ-098 are two verbs: a stopped
    step (FAILED, or a validate step held or parked on a red) offers ``repeat`` and — where
    there is a develop step to go back to — ``rework``; a validate step that has not started
    offers ``rework`` alone, because ``repeat`` has nothing to re-arm there. A manual hold
    keeps naming the shell-only ``steward validate`` beside them (Decision 6): the page never
    replaces the human procedure, it only offers the two moves next to it. Eligible steps name
    the session command that runs them — never an action here (REQ-097 Decision 5: no session
    is ever spawned from the page).

    Display hints only. The engine's own preconditions decide, so an offer the ledger does not
    actually support renders the CLI's refusal rather than a wrong state change.
    """
    req = view.req
    develop_done = led.status_of(f"{req}:develop") is StepStatus.DONE
    back = ["rework"] if view.phase == "validate" and develop_done else []
    if view.status == StepStatus.FAILED.value:
        return ["repeat"] + back, ""
    if view.status == StepStatus.BLOCKED.value and view.phase == "validate":
        latest = led.latest_validation(req)
        red = latest is not None and latest.get("ok") is False
        # A `manual`-AC hold (state F) keeps its own forward path — the sign-off itself is
        # only ever recorded by `steward validate` (Decision 6).
        return ["repeat"] + back, "" if red else f"steward validate {req}"
    if view.eligible:
        if view.phase == "validate":
            return back, f"steward validate {req}"
        return [], f"/advance {req} develop"
    return [], ""


# -- git facts (Decision 8) --------------------------------------------------------------


@dataclass
class GitFacts:
    branch: str
    dirty: int
    remote: str | None
    #: Commits on the integration branch its remote-tracking branch lacks; None = no
    #: remote-tracking branch to compare against.
    unpushed: int | None
    #: Commits on the integration branch the production branch lacks (the release gap);
    #: None when either branch is absent locally.
    gap: int | None
    last_commit_ts: int | None
    head: str = ""
    subject: str = ""
    error: str = ""

    @property
    def age(self) -> str:
        return humanize_age(self.last_commit_ts)


def humanize_age(ts: int | None, now: float | None = None) -> str:
    if ts is None:
        return "—"
    delta = max(0, int((now or time.time()) - ts))
    if delta < 3600:
        return f"{delta // 60} min"
    if delta < 86400:
        return f"{delta // 3600} h"
    return f"{delta // 86400} d"


def git_facts(root: Path, integration: str = "dev", production: str = "main") -> GitFacts | None:
    """Read-only git facts for ``root``; ``None`` when it is not a git repository.

    Every call is a porcelain/plumbing *read* — the page never runs a mutating git command.
    """
    root = Path(root)
    if not (root / ".git").exists():
        return None

    def g(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)

    head = g("rev-parse", "--abbrev-ref", "HEAD")
    if head.returncode != 0:
        return GitFacts("?", 0, None, None, None, None, error=head.stderr.strip())
    branch = head.stdout.strip()
    dirty = len([ln for ln in g("status", "--porcelain").stdout.splitlines() if ln.strip()])
    remotes = g("remote").stdout.split()
    remote = remotes[0] if remotes else None

    def has_ref(ref: str) -> bool:
        return g("rev-parse", "--verify", "--quiet", ref).returncode == 0

    unpushed = None
    if remote and has_ref(integration) and has_ref(f"{remote}/{integration}"):
        r = g("rev-list", "--count", f"{remote}/{integration}..{integration}")
        unpushed = int(r.stdout.strip() or 0) if r.returncode == 0 else None
    gap = None
    if has_ref(integration) and has_ref(production):
        r = g("rev-list", "--count", f"{production}..{integration}")
        gap = int(r.stdout.strip() or 0) if r.returncode == 0 else None
    ts = None
    sha = subject = ""
    last = g("log", "-1", "--format=%ct%n%h%n%s")
    if last.returncode == 0 and last.stdout.strip():
        parts = last.stdout.rstrip("\n").split("\n", 2)
        ts = int(parts[0]) if parts[0].isdigit() else None
        sha = parts[1] if len(parts) > 1 else ""
        subject = parts[2] if len(parts) > 2 else ""
    return GitFacts(branch, dirty, remote, unpushed, gap, ts, sha, subject)


# -- what waits on the operator (needs-me) ---------------------------------------------


@dataclass
class Attention:
    project: str
    kind: str  # decision | failed | validation | attended
    ref: str
    text: str
    hint: str = ""


def attention(project: str, st: StatusView) -> list[Attention]:
    """Everything in one project that waits on a human: parked decisions, validate steps
    awaiting a sign-off (held or eligible), failed steps, and attended develop steps."""
    out: list[Attention] = []
    for d in st.decisions:
        out.append(Attention(project, "decision", d.id, f"{d.step}: {d.question.splitlines()[0]}",
                             f"steward decide {d.id}"))
    for s in st.steps:
        # The operator's move: the shell/session command when there is one, else the offered
        # verbs spelled the way the CLI would be typed.
        move = s.shell or "  |  ".join(f"steward {v} {s.req}" for v in s.actions)
        if s.status == StepStatus.FAILED.value:
            out.append(Attention(project, "failed", s.id, s.note or "step failed", move))
        elif s.phase == "validate" and s.status == StepStatus.BLOCKED.value:
            out.append(Attention(project, "validation", s.id, s.note or "validation held", move))
        elif s.phase == "validate" and s.eligible:
            out.append(Attention(project, "validation", s.id, "validation to run and sign off", move))
        elif s.phase == "develop" and s.eligible and s.attended:
            out.append(Attention(project, "attended", s.id, s.note or "needs an attended session", move))
    return out


# -- one project, everything the pages need ------------------------------------------


@dataclass
class ProjectView:
    ref: ProjectRef
    cfg: Config | None = None
    status: StatusView | None = None
    git: GitFacts | None = None
    reqs: list[ReqFile] = field(default_factory=list)
    backlog: list[bl.Standing] = field(default_factory=list)
    backlog_file: str = ""
    backlog_error: str = ""
    attention: list[Attention] = field(default_factory=list)
    error: str = ""

    @property
    def name(self) -> str:
        return self.ref.name

    @property
    def backlog_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.backlog:
            out[s.state] = out.get(s.state, 0) + 1
        return out


def load_project(ref: ProjectRef, templates_root: Path | None = None) -> ProjectView:
    """Everything the overview and the project page show for one stamped project.

    Each part is read independently so one broken artifact (a REQ that fails to parse, a
    malformed backlog) degrades that part to an error line instead of hiding the project.
    """
    view = ProjectView(ref=ref)
    try:
        cfg = load_config(ref.root)
    except Exception as exc:  # noqa: BLE001
        view.error = f"config: {exc}"
        return view
    view.cfg = cfg
    view.git = git_facts(ref.root, cfg.integration_branch, cfg.production_branch)
    reqs: list[ReqFile] | None = None
    try:
        reqs = load_reqs(cfg.req_dir) if cfg.req_dir.exists() else []
        view.reqs = reqs
    except Exception as exc:  # noqa: BLE001
        view.error = f"requirements: {exc}"
    try:
        view.status = project_status(cfg, templates_root, reqs)
        view.attention = attention(ref.name, view.status)
    except Exception as exc:  # noqa: BLE001
        view.error = (view.error + "; " if view.error else "") + f"status: {exc}"
    view.backlog_file = cfg.backlog_file
    if cfg.backlog_path.exists():
        try:
            view.backlog = bl.bits(cfg, reqs).standings()
        except bl.BacklogError as exc:
            view.backlog_error = str(exc)
    return view


# -- a REQ page (Decision 10: read-only) ----------------------------------------------


def render_markdown(text: str) -> str:
    """Markdown → HTML through Python-Markdown when the extra is installed, else ``<pre>``."""
    try:
        import markdown  # the `dashboard` extra
    except ImportError:
        import html

        return f"<pre>{html.escape(text)}</pre>"
    return markdown.markdown(text, extensions=["tables", "fenced_code"])


def req_body_html(req: ReqFile) -> str:
    """The REQ's prose as HTML with the acceptance fence removed — the page renders the
    parsed criteria as a table instead, so they are not shown twice."""
    from ..profiles.req.reqfile import _ACCEPTANCE_RE

    body = _ACCEPTANCE_RE.sub("\n", req.body)
    return render_markdown(body)
