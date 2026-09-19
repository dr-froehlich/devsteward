"""REQ-098 — two moves, not four.

The operator's recovery vocabulary is `steward repeat` (*again*) and `steward rework`
(*back*), and the **engine** reads the ledger to decide which body each one runs. Two verbs
were deleted outright (not aliased), and `rework` lost the "a real red must exist"
precondition that REQ-033 Decision 3 and REQ-055 Decision 2 recorded — it made the operator
pay for a validation whose verdict they already knew in order to type the verb they wanted.

Every criterion here is `regression`: the ledger, the CLI and the dashboard all run headless
in a clean checkout. The fixtures are the ones the folded verbs were built against —
`test_rework._seed_red` for the red park, `test_req075_scoped_revalidate._seed_mixed_red`
for the carry, `test_reland._build` for the land replay — so the collapsed verb runs on
exactly the wiring its parts were proven on.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from devsteward.cli import main as cli_main
from devsteward.config import Config
from devsteward.core.executor import RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.lifecycle import (
    DEFAULT_REWORK_BRIEF,
    LifecycleError,
    plan_repeat,
    repeat,
    rework,
)

from conftest import write_index
from test_req075_scoped_revalidate import _seed_mixed_red
from test_rework import _seed_red
from test_system_test_phase import _MANUAL, _REGRESSION, _write_req, _write_plan
from test_dashboard import client, root  # noqa: F401 — reused pytest fixtures
from test_transaction_boundary import _init_git, _scaffold

pytest.importorskip("flask")  # the `dashboard` extra is a declared requirement of this gate

_ARTIFACT = {"id": "AC2", "test": "false", "check": "artifact"}


def _project(root, acs=(_REGRESSION, _ARTIFACT), *, status="open", develop=StepStatus.DONE):
    """An in-flight REQ-001 with its develop step closed and its validate step untouched."""
    root.mkdir(parents=True, exist_ok=True)
    req_dir = root / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", list(acs), status=status)
    write_index(req_dir, [("REQ-001", "t", status.upper(), "–")])
    Ledger.init(root)
    led = Ledger(root)
    led.set_status("REQ-001:develop", develop)
    led.save()
    return led


def _rework_event(root) -> dict:
    return [e for e in Ledger(root).events() if e["event"] == "rework"][-1]


# -- AC1 -------------------------------------------------------------------------------


def test_rework_returns_any_unfinished_validate_to_develop(tmp_path):
    """`rework` is keyed on a **state**, not on a red (Decision 2).

    It returns the validate step to develop from every unfinished state — never started,
    held on a `manual` AC awaiting its oracle, failed, or parked on a red. The first three
    carry no evidence and no scope (there is no System-Tester write-up to carry); the red
    keeps everything REQ-089 gave it. Four shapes still refuse, and a refusal mutates
    nothing.
    """
    # (a) never started: the validate step has no recorded status at all.
    never = tmp_path / "never"
    led = _project(never)
    res = rework(Config(root=never), led, "REQ-001")

    assert (res.develop_step, res.validate_step) == ("REQ-001:develop", "REQ-001:validate")
    assert res.from_status == StepStatus.PENDING.value
    assert res.evidence is None and res.scope is None and res.carried is None
    assert res.brief == DEFAULT_REWORK_BRIEF
    fresh = Ledger(never)
    assert fresh.status_of("REQ-001:develop") is StepStatus.RECOVER
    assert fresh.status_of("REQ-001:validate") is StepStatus.PENDING
    ev = _rework_event(never)
    assert ev["brief"] == DEFAULT_REWORK_BRIEF and ev["evidence"] is None
    assert "scope" not in ev and "carried" not in ev

    # (b) held on a `manual` AC awaiting its human oracle — the hold goes with the transition.
    held = tmp_path / "held"
    led_h = _project(held, [_REGRESSION, _MANUAL])
    led_h.set_hold("REQ-001:validate", "REQ-001 awaits its human sign-off")
    led_h.save()
    res_h = rework(Config(root=held), led_h, "REQ-001", reason="the spec was wrong")

    assert res_h.from_status == StepStatus.BLOCKED.value
    assert res_h.brief == "the spec was wrong"     # --reason is the repair context
    fresh_h = Ledger(held)
    assert fresh_h.status_of("REQ-001:validate") is StepStatus.PENDING
    assert fresh_h.hold_note("REQ-001:validate") == ""      # cleared by the transition
    assert _rework_event(held)["brief"] == "the spec was wrong"

    # (c) failed: the partial tree is left as it is (the `repeat` doctrine), no scope.
    failed = tmp_path / "failed"
    led_f = _project(failed)
    led_f.set_status("REQ-001:validate", StepStatus.FAILED)
    led_f.save()
    res_f = rework(Config(root=failed), led_f, "REQ-001")

    assert res_f.from_status == StepStatus.FAILED.value
    assert res_f.evidence is None and res_f.scope is None
    assert Ledger(failed).status_of("REQ-001:validate") is StepStatus.PENDING

    # (d) parked on a red: unchanged — evidence, the red brief, the scope and the carried
    #     greens with provenance (REQ-075 / REQ-089 Decision 6).
    red = tmp_path / "red"
    red.mkdir()
    led_r = _seed_mixed_red(
        red,
        [_REGRESSION,
         {"id": "AC2", "test": "true", "check": "artifact"},
         {"id": "AC3", "test": "false", "check": "artifact"}],
        [{"ac": "AC2", "check": "artifact", "ok": True, "detail": "green"},
         {"ac": "AC3", "check": "artifact", "ok": False, "detail": "boom"}],
        evidence=".devsteward/evidence/REQ-001/src",
    )
    led_r.set_status("REQ-001:validate", StepStatus.BLOCKED)
    led_r.save()
    res_r = rework(Config(root=red), led_r, "REQ-001")

    assert res_r.evidence == ".devsteward/evidence/REQ-001/src"
    assert "boom" in res_r.brief and res_r.scope == ["AC3"]
    assert [c["ac"] for c in res_r.carried] == ["AC2"]
    assert res_r.carried[0]["source_evidence"] == ".devsteward/evidence/REQ-001/src"
    assert res_r.carried[0]["source_event"] is not None
    assert res_r.decision == "DEC-001"                      # the parked decision is answered
    ev_r = _rework_event(red)
    assert ev_r["scope"] == ["AC3"] and ev_r["evidence"] == ".devsteward/evidence/REQ-001/src"
    assert Ledger(red).status_of("REQ-001:develop") is StepStatus.RECOVER

    # -- the four refusals, each proven non-mutating ------------------------------------
    def _refuses(root, led, match):
        state = (root / ".devsteward" / "state.yaml").read_bytes()
        events = (root / ".devsteward" / "events.jsonl").read_bytes()
        with pytest.raises(LifecycleError, match=match):
            rework(Config(root=root), led, "REQ-001")
        assert (root / ".devsteward" / "state.yaml").read_bytes() == state
        assert (root / ".devsteward" / "events.jsonl").read_bytes() == events

    done = tmp_path / "done"
    led_d = _project(done, status="done")
    led_d.set_status("REQ-001:validate", StepStatus.DONE)
    led_d.save()
    _refuses(done, led_d, "supersed")                        # done is never weakened

    reg = tmp_path / "reg"
    _refuses(reg, _project(reg, [_REGRESSION]), "no validate step")

    open_dev = tmp_path / "open_dev"
    _refuses(open_dev, _project(open_dev, develop=StepStatus.FAILED), "nothing to go back from")

    running = tmp_path / "running"
    led_x = _project(running)
    led_x.set_status("REQ-001:validate", StepStatus.RUNNING)
    led_x.save()
    _refuses(running, led_x, "is running")

    with pytest.raises(LifecycleError, match="not a known requirement"):
        rework(Config(root=never), Ledger(never), "REQ-999")


# -- AC2 -------------------------------------------------------------------------------


def test_rework_reason_reaches_the_event_via_cli_and_dashboard(tmp_path, monkeypatch,
                                                              root, client):
    """`--reason` is the operator's one line of repair context (Decision 4).

    Without a red there is no System-Tester write-up, so a resuming `/advance` session would
    otherwise know only that it was sent back. The reason reaches the `rework` event's
    `brief` through both surfaces — and through the *same* `verbs.rework` call (REQ-097
    Decision 5), which is why the dashboard needs no transition of its own. The shipped
    `/advance` skill is the third half of this: it must tell the resuming session to orient
    from the brief when the event carries no evidence dir.
    """
    # -- (1) the CLI, on a project with no red anywhere near it.
    proj = tmp_path / "cli"
    proj.mkdir()
    _scaffold(proj, acs=(("AC1", "true", "regression"), ("AC2", "manual: look", "manual")))
    _init_git(proj)
    monkeypatch.chdir(proj)
    led = Ledger(proj)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.set_hold("REQ-001:validate", "REQ-001 awaits a human sign-off")
    led.save()

    out = CliRunner().invoke(
        cli_main, ["rework", "REQ-001", "--reason", "the acceptance fixture is wrong"],
        catch_exceptions=False,
    )
    assert out.exit_code == 0, out.output
    assert "the acceptance fixture is wrong" in out.output   # printed as the repair context
    assert f"was {StepStatus.BLOCKED.value}" in out.output   # what it came back from
    ev = [e for e in Ledger(proj).events() if e["event"] == "rework"][-1]
    assert ev["brief"] == "the acceptance fixture is wrong" and ev["evidence"] is None

    # Omitting it never blocks the verb — the engine supplies the default.
    led2 = Ledger(proj)
    led2.set_status("REQ-001:develop", StepStatus.DONE)
    led2.set_hold("REQ-001:validate", "held again")
    led2.save()
    assert CliRunner().invoke(cli_main, ["rework", "REQ-001"]).exit_code == 0
    assert [e for e in Ledger(proj).events()
            if e["event"] == "rework"][-1]["brief"] == DEFAULT_REWORK_BRIEF

    # -- (2) the dashboard's rework form, hitting the same `verbs.rework`.
    alpha = root / "alpha"
    assert 'name="reason"' in client.get("/p/alpha").get_data(as_text=True)
    resp = client.post("/p/alpha/verb/rework",
                       data={"req": "REQ-008", "reason": "the lab was never built"},
                       follow_redirects=True)
    assert resp.status_code == 200
    ev_d = [e for e in Ledger(alpha).events() if e["event"] == "rework"][-1]
    assert ev_d["req"] == "REQ-008" and ev_d["brief"] == "the lab was never built"
    assert Ledger(alpha).status_of("REQ-008:develop") is StepStatus.RECOVER

    # -- (3) the shipped `/advance` skill teaches the no-evidence orientation.
    from devsteward.cli import _package_templates

    skill = (_package_templates() / ".claude" / "skills" / "advance" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "no** `evidence` dir" in skill, "the skill does not name the no-evidence shape"
    assert "`brief`** is your whole repair context" in skill


# -- AC3 -------------------------------------------------------------------------------


def test_repeat_rearms_from_every_stopping_state(tmp_path):
    """`repeat` reads the ledger for what stopped the REQ and re-arms it (Decision 3).

    Four bodies behind one verb — the three that used to be `repeat`, `revalidate` and
    `reland`, plus the manual hold that had no verb at all. The discrimination the operator
    used to perform (recognise a ledger shape, choose a verb) moves into the one place that
    already holds the facts. The event vocabulary does not move with it (Decision 5).
    """
    # (a) a FAILED step → RECOVER, its partial tree untouched.
    failed = tmp_path / "failed"
    led = _project(failed, develop=StepStatus.FAILED)
    res = repeat(Config(root=failed), led, "REQ-001")

    assert res.kinds == ["recover"] and res.recovered == ["REQ-001:develop"]
    fresh = Ledger(failed)
    assert fresh.status_of("REQ-001:develop") is StepStatus.RECOVER
    assert fresh.events()[-1]["event"] == "step_recover"

    # (b) a validate step BLOCKED on a red → PENDING, the greens carried with provenance,
    #     a scope-bearing `revalidate` event. Develop is left alone: that is the difference
    #     from `rework`, and the whole reason both moves exist.
    red = tmp_path / "red"
    red.mkdir()
    led_r = _seed_mixed_red(
        red,
        [_REGRESSION,
         {"id": "AC2", "test": "true", "check": "artifact"},
         {"id": "AC3", "test": "false", "check": "artifact"}],
        [{"ac": "AC2", "check": "artifact", "ok": True, "detail": "green"},
         {"ac": "AC3", "check": "artifact", "ok": False, "detail": "boom"}],
        evidence=".devsteward/evidence/REQ-001/src",
    )
    led_r.set_status("REQ-001:validate", StepStatus.BLOCKED)
    led_r.save()
    res_r = repeat(Config(root=red), led_r, "REQ-001")

    assert res_r.kinds == ["revalidate"] and res_r.scope == ["AC3"]
    assert [c["ac"] for c in res_r.carried] == ["AC2"]
    assert res_r.carried[0]["source_evidence"] == ".devsteward/evidence/REQ-001/src"
    assert res_r.carried[0]["source_event"] is not None
    assert res_r.decision == "DEC-001"
    fresh_r = Ledger(red)
    assert fresh_r.status_of("REQ-001:develop") is StepStatus.DONE       # untouched
    assert fresh_r.status_of("REQ-001:validate") is StepStatus.PENDING
    ev_r = [e for e in fresh_r.events() if e["event"] == "revalidate"][-1]
    assert ev_r["scope"] == ["AC3"] and [c["ac"] for c in ev_r["carried"]] == ["AC2"]

    # (c) a validate step BLOCKED on a manual hold → PENDING, hold cleared, no scope (a full
    #     re-run). The sign-off itself is still only ever recorded by `steward validate`
    #     (Decision 6) — this is a reset, never a verdict.
    held = tmp_path / "held"
    led_h = _project(held, [_REGRESSION, _MANUAL])
    led_h.set_hold("REQ-001:validate", "REQ-001 awaits a human sign-off")
    led_h.save()
    res_h = repeat(Config(root=held), led_h, "REQ-001")

    assert res_h.kinds == ["unhold"] and res_h.scope is None and res_h.evidence is None
    fresh_h = Ledger(held)
    assert fresh_h.status_of("REQ-001:validate") is StepStatus.PENDING
    assert fresh_h.hold_note("REQ-001:validate") == ""
    ev_h = [e for e in fresh_h.events() if e["event"] == "revalidate"][-1]
    assert "scope" not in ev_h                                            # a full re-run

    # (d) a validate step FAILED after a green validation and a land refusal → the recorded
    #     green is replayed and the REQ lands, with no session. `plan_repeat` is what routes
    #     there; the replay itself is REQ-065's body, unchanged.
    from test_reland import _build, _green_then_refused

    land = tmp_path / "land"
    ex = _build(land, plan=False)
    _green_then_refused(ex)
    plan = plan_repeat(ex.ledger, "REQ-001")
    assert plan.lands and plan.mode == "reland" and plan.failed == []

    # …and while the land gate is still red (no plan artifact) the replay refuses.
    assert ex.validate_runner.reland(ex, "REQ-001").outcome is RunOutcome.REFUSED
    assert Ledger(land).status_of("REQ-001:validate") is StepStatus.FAILED

    _write_plan(land, "REQ-001")                       # fix the formality
    res_l = ex.validate_runner.reland(ex, "REQ-001")
    assert res_l.outcome is RunOutcome.DONE
    assert Ledger(land).status_of("REQ-001:validate") is StepStatus.DONE
    assert any(e["event"] == "reland" for e in Ledger(land).events())

    # The land replay needs the executor, so the ledger-only body refuses to apply it — the
    # branch lives in `verbs.repeat`, which is what the CLI and the dashboard both call.
    with pytest.raises(LifecycleError, match="land replay"):
        repeat(Config(root=land), ex.ledger, "REQ-001", plan=plan)

    # (e) a REQ with both a failed develop and a stopped validate re-arms both (Risk 3): the
    #     executor's dependency order runs develop first.
    both = tmp_path / "both"
    both.mkdir()
    led_b = _seed_red(both)[0]
    led_b.set_status("REQ-001:develop", StepStatus.FAILED)
    led_b.set_status("REQ-001:validate", StepStatus.BLOCKED)
    led_b.save()
    res_b = repeat(Config(root=both), led_b, "REQ-001")
    assert res_b.kinds == ["recover", "revalidate"]
    assert res_b.steps == ["REQ-001:develop", "REQ-001:validate"]

    # (f) nothing stopped → one refusal covering every shape, and it names the other move.
    quiet = tmp_path / "quiet"
    led_q = _project(quiet)
    with pytest.raises(LifecycleError, match="nothing to repeat"):
        repeat(Config(root=quiet), led_q, "REQ-001")
    with pytest.raises(LifecycleError, match="steward rework REQ-001"):
        repeat(Config(root=quiet), led_q, "REQ-001")


# -- AC4 -------------------------------------------------------------------------------

_RETIRED = ("steward revalidate", "steward reland")


def test_revalidate_and_reland_are_gone_from_registry_hints_and_shipped_artifacts(
    tmp_path, monkeypatch, root
):
    """Deleted, not aliased, and not left standing in any surface that names verbs (D1, D7).

    The derived verb-coverage guard (REQ-094) goes red on an *undocumented* verb but is blind
    to a *documented, removed* one — the manual would go on describing verbs the engine no
    longer has, and a consumer agent drives the engine through that manual alone. This grep
    is the other half. It scans whole files, not tables: the house rule for a retired verb is
    that no surface names it at all, not even to say it is gone (`test_steward_manual.py`'s
    `steward recover` denylist is the precedent).
    """
    from devsteward.cli import _package_templates
    from devsteward.dashboard.app import STEP_VERBS
    from devsteward.dashboard.model import _offer
    from test_steward_manual import test_manual_covers_every_registered_verb

    # (a) the click registry.
    assert "revalidate" not in cli_main.commands and "reland" not in cli_main.commands
    assert {"repeat", "rework"} <= set(cli_main.commands)

    # (b) the derived manual-coverage guard stays green in both directions.
    test_manual_covers_every_registered_verb()

    # (c) no shipped artifact and no handbook chapter names a retired verb.
    repo = Path(__file__).resolve().parent.parent
    surfaces = {
        "STEWARD.md": _package_templates() / "STEWARD.md",
        "CLAUDE.md.tmpl": _package_templates() / "CLAUDE.md.tmpl",
    }
    for skill in (_package_templates() / ".claude" / "skills").rglob("SKILL.md"):
        surfaces[f"skill:{skill.parent.name}"] = skill
    for chapter in (repo / "devsteward" / "handbook").glob("*.qmd"):
        surfaces[f"handbook:{chapter.name}"] = chapter
    assert len(surfaces) > 6, surfaces          # the scan found real files, not an empty glob
    for name, path in surfaces.items():
        text = path.read_text(encoding="utf-8")
        for verb in _RETIRED:
            assert verb not in text, f"{name} still presents `{verb}`, which the engine no longer has"

    # (d) `steward status` names only the two moves (and the hold's own shell command).
    proj = tmp_path / "status"
    proj.mkdir()
    _scaffold(proj, acs=(("AC1", "true", "regression"), ("AC2", "manual: look", "manual")))
    _init_git(proj)
    monkeypatch.chdir(proj)
    led = Ledger(proj)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.set_hold("REQ-001:validate", "REQ-001 awaits a human sign-off — steward validate REQ-001")
    led.save()
    out = CliRunner().invoke(cli_main, ["status"], catch_exceptions=False)
    assert out.exit_code == 0, out.output
    assert "steward repeat REQ-001" in out.output and "steward rework REQ-001" in out.output
    assert all(verb not in out.output for verb in _RETIRED)

    # (e) the red-park brief and (f) the validate-record routing.
    from test_reland import _build

    ex = _build(tmp_path / "routing")
    routine = ex.validate_runner
    step = ex.step_by_id("REQ-001:validate")
    red = routine._park_red(
        ex, step, routine._req("REQ-001"),
        [{"ac": "AC2", "check": "artifact", "ok": False, "detail": "boom"}],
        in_flight=False,
    )
    assert "steward rework REQ-001" in red.detail and "steward repeat REQ-001" in red.detail
    assert all(verb not in red.detail for verb in _RETIRED)

    ex.ledger.set_status("REQ-001:validate", StepStatus.BLOCKED)
    ex.ledger.save()
    routed = routine.resume_context(ex, "REQ-001")
    assert routed.outcome is RunOutcome.REFUSED
    assert "steward rework REQ-001" in routed.detail and "steward repeat REQ-001" in routed.detail
    assert all(verb not in routed.detail for verb in _RETIRED)

    # (g) the dashboard offers exactly the CLI's set — and its route rejects the retired verbs.
    assert set(STEP_VERBS) == {"repeat", "rework", "activate"}
    from devsteward.config import load_config
    from devsteward.dashboard import model as dash_model

    st = dash_model.project_status(load_config(root / "alpha"))
    offered = {v for s in st.steps for v in s.actions}
    assert offered <= {"repeat", "rework"}
    shells = {s.shell for s in st.steps if s.shell}
    assert all(sh.startswith("steward validate") or sh.startswith("/advance") for sh in shells)
    assert _offer.__doc__ and "two verbs" in _offer.__doc__


# -- AC5 -------------------------------------------------------------------------------


def test_project_page_renders_backlog_above_requirements(client):
    """Decision 8: the backlog is what the operator acts on from this page (add, edit,
    verdict); the requirements list is read-only (REQ-097 Decision 10). Nothing else moves."""
    page = client.get("/p/alpha").get_data(as_text=True)
    backlog, requirements = page.index("<h2>Backlog"), page.index("<h2>Requirements")
    assert backlog < requirements, "the Requirements section still renders above the Backlog"
    # The add-a-need form stays with its section rather than being stranded below the REQs.
    assert backlog < page.index("Add a need") < requirements
    # And the rest of the page is where it was: status above both, REQ links still rendered.
    assert page.index("<h2>Steward status") < backlog
    assert "/p/alpha/req/REQ-002" in page[requirements:]


# -- AC6 -------------------------------------------------------------------------------

#: What the two folded verbs proved, and where it still has to be proved. The bodies
#: survived Decision 1 intact, so their tests survive with them — re-pointed at the verb
#: that now reaches each body, never deleted along with the verb name.
_MIGRATED = {
    "tests/test_repeat_red_validate.py": {          # was tests/test_revalidate.py
        "test_repeat_rearms_validate_only",
        "test_repeat_refuses_only_when_nothing_stopped",
        "test_red_park_brief_names_both_moves",
        "test_repeat_cli_wiring_on_a_red",
    },
    "tests/test_reland.py": {
        "test_reland_lands_recorded_green_without_session",
        "test_reland_refuses_if_gate_still_red",
        "test_reland_precondition_failures",
    },
}


def test_former_verb_tests_are_migrated_onto_repeat():
    """Deleting a verb must not delete the proof of the behaviour behind it (AC6).

    `revalidate` and `reland` are gone as *verbs*; their bodies are not, so the coverage that
    held them honest is re-pointed at `repeat` rather than removed with the names. Nothing
    else guards this: the suite would stay green if someone deleted both files, because every
    test they hold is about a verb no one types any more.

    (AC6 originally read `test: "python -m pytest"`. The develop gate treats a *named* test's
    skip as red (REQ-028) and this suite carries one permanent artifact-graded skip, so that
    could never go green — while `verify.full_suite` already gates the whole suite, where
    skips are legal. Re-pointed at the substantive half with the owner present, 2026-09-19;
    recorded as Decision 11.)
    """
    repo = Path(__file__).resolve().parent.parent
    assert not (repo / "tests" / "test_revalidate.py").exists(), (
        "test_revalidate.py is back — the migration renames it onto the surviving verb"
    )

    for rel, expected in _MIGRATED.items():
        path = repo / rel
        assert path.is_file(), f"{rel} is gone — the behaviour it proves still ships"
        tree = ast.parse(path.read_text(encoding="utf-8"))

        names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        assert expected <= names, f"{rel} lost: {sorted(expected - names)}"

        # It exercises a surviving entry point — `repeat` for the re-arm, the routine for the
        # land replay — rather than sitting inert next to a deleted verb.
        called = {
            n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
            for n in ast.walk(tree) if isinstance(n, ast.Call)
        }
        assert called & {"repeat", "reland"}, f"{rel} calls neither repeat nor the land replay"

        # And it names no deleted verb: not as an import, not as a CLI argument.
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("devsteward"):
                bad = {a.name for a in node.names} & {"revalidate", "reland"}
                assert not bad or node.module.endswith("validate"), (
                    f"{rel} imports {sorted(bad)} from {node.module} — that verb is gone"
                )
        # A CLI invocation of a deleted verb — `["revalidate", "REQ-001"]`. Matched narrowly
        # on purpose: the *ledger event* keeps both names (Decision 5), so these files still
        # assert `kinds == ["revalidate"]` and read `event == "reland"`, which is correct.
        argv = re.search(r'\["(revalidate|reland)",\s*"REQ-', path.read_text(encoding="utf-8"))
        assert argv is None, (
            f"{rel} still invokes `steward {argv.group(1)}` through the CLI"
        )
