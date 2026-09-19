"""The Flask application behind ``steward dashboard`` (REQ-097; the ``dashboard`` extra).

Routes render :mod:`devsteward.dashboard.model`; form handlers call the **same** functions
the CLI verbs call — :mod:`devsteward.verbs` for the ledger state changes and
:mod:`devsteward.profiles.req.backlog` for the backlog — and flash the result or the
refusal. Nothing here spawns a Claude session or runs ``steward run``/``advance``/
``validate`` (Decision 5); a session command is shown to the operator as text to run.

The app binds to loopback only (Decision 4): ``create_app`` builds it, ``steward dashboard``
serves it on ``127.0.0.1``.
"""

from __future__ import annotations

import secrets
import threading
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, url_for

from .. import verbs
from ..core.errors import StewardError
from ..lifecycle import LifecycleError
from ..profiles.req import backlog as bl
from . import model

#: Ledger and file writes are serialized: one operator, one page, one write at a time — the
#: same discipline as typing verbs into one shell.
_WRITE_LOCK = threading.Lock()

#: The state-changing verbs a step form may name (REQ-097 Decision 5: exactly the CLI's
#: set — which REQ-098 shrank to the operator's two moves plus ``activate``).
STEP_VERBS = ("repeat", "rework", "activate")


def _repeat_message(req_id: str, res) -> str:
    """``steward repeat``'s report, one line per branch it took (REQ-098 Decision 3).

    The verb reads the ledger for what stopped the REQ, so the page cannot know in advance
    which body ran — it says what happened, exactly as the CLI prints it.
    """
    if res.land is not None:
        return f"repeating {req_id}: the recorded green was replayed and landed — {res.land.detail}"
    parts: list[str] = []
    if "recover" in res.kinds:
        parts.append(f"{', '.join(res.recovered)} -> recover. Re-run `steward run` to re-attempt.")
    if "revalidate" in res.kinds:
        carried = (
            " carried forward: " + ", ".join(f"{c['ac']} [{c['check']}]" for c in res.carried)
            if res.carried else ""
        )
        parts.append(f"{req_id}:validate -> pending (develop stays done). Re-run "
                     f"`steward validate {req_id}` to re-validate.{carried}")
    if "unhold" in res.kinds:
        parts.append(f"{req_id}:validate -> pending (hold cleared). Re-run "
                     f"`steward validate {req_id}` for a full re-run.")
    return f"repeating {req_id}: " + " ".join(parts)


def create_app(root: Path, *, templates_root: Path | None = None,
               backlog_template: str | None = None) -> Flask:
    """Build the application over ``root`` (the directory whose children are projects)."""
    app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))
    app.config["SECRET_KEY"] = secrets.token_hex(16)  # flash needs a session; loopback only
    app.config["DASHBOARD_ROOT"] = Path(root).resolve()
    app.config["TEMPLATES_ROOT"] = templates_root
    app.config["BACKLOG_TEMPLATE"] = backlog_template
    app.jinja_env.globals["MARKS"] = model.MARKS

    def _refs() -> list[model.ProjectRef]:
        return model.scan_root(app.config["DASHBOARD_ROOT"])

    def _ref(name: str) -> model.ProjectRef:
        for ref in _refs():
            if ref.name == name and ref.stamped:
                return ref
        abort(404)

    def _project(name: str) -> model.ProjectView:
        return model.load_project(_ref(name), app.config["TEMPLATES_ROOT"])

    def _cfg(name: str):
        from ..config import load_config

        return load_config(_ref(name).root)

    # -- pages -------------------------------------------------------------------------

    @app.get("/")
    def overview():
        refs = _refs()
        projects = [model.load_project(r, app.config["TEMPLATES_ROOT"]) for r in refs if r.stamped]
        unstamped = [r for r in refs if not r.stamped]
        needs = [a for p in projects for a in p.attention]
        return render_template(
            "overview.html", root=app.config["DASHBOARD_ROOT"], projects=projects,
            unstamped=unstamped, needs=needs,
        )

    @app.get("/p/<name>")
    def project(name: str):
        return render_template("project.html", p=_project(name), bl=bl)

    @app.get("/p/<name>/req/<req_id>")
    def req_page(name: str, req_id: str):
        p = _project(name)
        req = next((r for r in p.reqs if r.id == req_id), None)
        if req is None:
            abort(404)
        return render_template("req.html", p=p, req=req, body=model.req_body_html(req))

    # -- state changes: the CLI's verbs, the CLI's refusals --------------------------

    def _run(name: str, label: str, fn):
        """Run one write under the lock; flash the outcome the way the CLI would print it."""
        try:
            with _WRITE_LOCK:
                message = fn()
        except (LifecycleError, bl.BacklogError) as exc:
            flash(f"{label}: {exc}", "error")
        except StewardError as exc:
            flash(f"{label}: {exc} — recovery: {exc.recovery}", "error")
        else:
            flash(message, "ok")
        return redirect(url_for("project", name=name))

    @app.post("/p/<name>/verb/<verb>")
    def step_verb(name: str, verb: str):
        if verb not in STEP_VERBS:
            abort(404)
        req_id = request.form.get("req", "").strip()
        if not req_id:
            abort(400)
        cfg = _cfg(name)

        def fn():
            if verb == "activate":
                return verbs.activate(cfg, req_id).message
            if verb == "repeat":
                res = verbs.repeat(cfg, req_id)
                return _repeat_message(req_id, res)
            res = verbs.rework(cfg, req_id, reason=request.form.get("reason", "").strip() or None)
            carried = (
                " carried forward: " + ", ".join(f"{c['ac']} [{c['check']}]" for c in res.carried)
                if res.carried else ""
            )
            return (f"reworking {req_id}: {res.develop_step} -> recover, {res.validate_step} -> "
                    f"pending (was {res.from_status}). Re-run `steward run` to fix and "
                    f"re-validate.{carried} — {res.brief.splitlines()[0]}")

        return _run(name, f"{verb} {req_id}", fn)

    @app.post("/p/<name>/decision/<decision_id>")
    def decision(name: str, decision_id: str):
        answer = request.form.get("answer", "").strip()
        rationale = request.form.get("rationale", "").strip() or None
        if not answer:
            flash(f"decision-answer {decision_id}: an answer is required", "error")
            return redirect(url_for("project", name=name))
        cfg = _cfg(name)
        return _run(
            name, f"decision-answer {decision_id}",
            lambda: (lambda d: f"Answered {decision_id}; {d.step} unblocked. Run `steward run` to resume.")(
                verbs.answer_decision(cfg, decision_id, answer, rationale)
            ),
        )

    # -- the backlog: the same file operations as backlog-add/-edit/-accept/... ---------

    @app.post("/p/<name>/backlog/add")
    def backlog_add(name: str):
        cfg = _cfg(name)
        need = request.form.get("need", "").strip()
        handle = request.form.get("handle", "").strip() or None
        origin = request.form.get("origin", bl.OPERATOR)
        if not need:
            flash("backlog-add: the need is required", "error")
            return redirect(url_for("project", name=name))

        def fn():
            h, created = bl.add(cfg, need, handle=handle, origin=origin,
                                template=app.config["BACKLOG_TEMPLATE"])
            return f"+ {h} — {need}" + (f" (created {cfg.backlog_file})" if created else "")

        return _run(name, "backlog-add", fn)

    @app.post("/p/<name>/backlog/<handle>/edit")
    def backlog_edit(name: str, handle: str):
        cfg = _cfg(name)
        need = request.form.get("need")
        origin = request.form.get("origin") or None
        raw = request.form.get("criteria")
        criteria = [ln.strip().lstrip("-*").strip() for ln in raw.splitlines()] if raw is not None else None
        if criteria is not None:
            criteria = [c for c in criteria if c]

        def fn():
            item = bl.edit(cfg, handle, need=need, origin=origin, criteria=criteria)
            return f"~ {handle} — {item.need} [{item.origin}]"

        return _run(name, f"backlog-edit {handle}", fn)

    @app.post("/p/<name>/backlog/<handle>/verdict")
    def backlog_verdict(name: str, handle: str):
        cfg = _cfg(name)
        verdict = request.form.get("verdict", "")
        reason = request.form.get("reason", "").strip() or None
        note = request.form.get("note", "").strip() or None
        if verdict not in bl.VERDICTS:
            abort(400)

        def fn():
            item, event, _ = bl.record_verdict(cfg, handle, verdict, reason=reason, note=note)
            tail = f" (attempted by {event.req})" if event.req else ""
            return f"{handle}: {verdict}{tail} — {item.need[:70]}"

        verb = {bl.ACCEPTED: "accept", bl.DENIED: "deny", bl.HELD: "hold", bl.RETIRED: "retire"}[verdict]
        return _run(name, f"backlog-{verb}", fn)

    return app
