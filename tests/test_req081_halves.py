"""REQ-081 — the warm validation cycle: `steward validate start/record` as real CLI verbs.

The REQ-034 two-phase halves get entrypoints so a red validation no longer costs the
System-Tester session: `start` opens the step and readies the evidence dir from inside the
warm session (it spawns nothing — no CLAUDECODE refusal), the guided work and capture
happen there, and the operator records the verdict from a **second plain shell** with
`record` — the engine's interactive prompt is the only verdict channel (REQ-034 D2). On a
red, `steward rework`/`steward revalidate` run from that shell and the still-warm session
re-runs `start`; the revalidate edge is scoped per REQ-075. Shape A stays intact.

Wired CLI-first (CliRunner over a real temp git repo + real `Ledger`, like
`test_validate_recovery.py` / `test_transaction_boundary.py`): the ACs claim command
behavior across *separate processes*, so each half is a separate `invoke`. Hermetic
(REQ-064 screen) — the fake System Tester is the test itself writing capture files.

`-k` selector tokens (`start_half`, `record_green`, `record_red`, `full_cycle`,
`shape_a`) are disjoint from the module name (REQ-080's selector lesson).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from devsteward.cli import main as cli_main
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.profiles.req.reqfile import parse_req

from conftest import write_index
from test_system_test_phase import _write_req, _write_plan, _ARTIFACT_OK, _MANUAL

_CONFIG = """\
profile: req
accounts:
  provider: single
git:
  production_branch: main
  integration_branch: dev
"""


@pytest.fixture(autouse=True)
def _plain_shell(monkeypatch):
    """The default scenario is the plain shell — CLAUDECODE unset (the suite itself may
    run inside a Claude session). Tests about the warm session set it explicitly."""
    monkeypatch.delenv("CLAUDECODE", raising=False)


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _project(
    root: Path, acs, *, plan=True, process=None, develop_done=True
) -> None:
    """A real on-disk project (config + git repo on `dev`) the CLI verbs can run against,
    with REQ-001's develop already checkpointed unless a test probes that pre-flight."""
    req_dir = root / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", list(acs), process=process)
    write_index(req_dir, [("REQ-001", "REQ-001 title", "OPEN", "–")])
    if plan:
        _write_plan(root, "REQ-001")
    Ledger.init(root)
    (root / ".devsteward" / "config.yaml").write_text(_CONFIG, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "warm@devsteward.test")
    _git(root, "config", "user.name", "Warm Cycle Test")
    _git(root, "checkout", "-q", "-b", "dev")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "scaffold")
    if develop_done:
        led = Ledger(root)
        led.set_status("REQ-001:develop", StepStatus.DONE)
        led.save()


def _events(root: Path) -> list[dict]:
    path = root / ".devsteward" / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _started_evidence(root: Path) -> Path:
    """The evidence dir the latest start half recorded on its `step_started` event —
    the REQ-081 D6 handoff channel the record half resolves."""
    rel = [
        e["evidence"] for e in _events(root)
        if e["event"] == "step_started" and e.get("evidence")
    ][-1]
    return root / rel


def _capture(root: Path, content: str = "observed behaviour\n") -> None:
    """Stand in for the warm session's guided capture."""
    (_started_evidence(root) / "capture.txt").write_text(content, encoding="utf-8")


def _invoke(root: Path, args, input=None):
    return CliRunner().invoke(cli_main, args, input=input)


# -- AC1: the start half --------------------------------------------------------


def test_start_half_opens_step_inside_claude_session(tmp_path, monkeypatch):
    """`steward validate start` sets RUNNING, readies + prints the evidence dir, records
    it on the start event, and spawns nothing — so it works with CLAUDECODE set (the warm
    System-Tester session *is* the session)."""
    _project(tmp_path, [_ARTIFACT_OK, _MANUAL])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")

    res = _invoke(tmp_path, ["validate", "start", "REQ-001"])

    assert res.exit_code == 0, res.output
    assert "validation started: REQ-001:validate" in res.output
    assert "evidence dir: .devsteward/evidence/REQ-001/" in res.output
    assert "steward validate record REQ-001" in res.output  # the handoff hint
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:validate") is StepStatus.RUNNING
    assert _started_evidence(tmp_path).is_dir()


def test_start_half_reentry_mints_fresh_evidence_dir(tmp_path, monkeypatch):
    """start on an already-RUNNING step is the clean re-entry (mirrors shape A after a
    killed session): a fresh dated dir, and record resolves the *latest* one."""
    _project(tmp_path, [_ARTIFACT_OK])
    monkeypatch.chdir(tmp_path)
    assert _invoke(tmp_path, ["validate", "start", "REQ-001"]).exit_code == 0
    first = _started_evidence(tmp_path)
    time.sleep(1.1)  # the dated dir name is second-granular
    res = _invoke(tmp_path, ["validate", "start", "REQ-001"])
    assert res.exit_code == 0, res.output
    second = _started_evidence(tmp_path)
    assert second != first
    assert Ledger(tmp_path).status_of("REQ-001:validate") is StepStatus.RUNNING


def test_start_half_preflight_refusals(tmp_path, monkeypatch):
    """The shape-A pre-flights apply unchanged: develop not checkpointed, a pending
    declared lab, and the REQ-065 formality gate (no plan) each refuse start — and a done
    REQ routes to the bare re-run form."""
    a = tmp_path / "a"
    a.mkdir()
    _project(a, [_ARTIFACT_OK], develop_done=False)
    monkeypatch.chdir(a)
    res = _invoke(a, ["validate", "start", "REQ-001"])
    assert res.exit_code != 0 and "develop is not closed" in res.output

    b = tmp_path / "b"
    b.mkdir()
    _project(b, [_ARTIFACT_OK], process={"lab": ["REQ-777"]})
    monkeypatch.chdir(b)
    res = _invoke(b, ["validate", "start", "REQ-001"])
    assert res.exit_code != 0 and "waiting on REQ-777" in res.output
    assert Ledger(b).status_of("REQ-001:validate") is StepStatus.PENDING

    c = tmp_path / "c"
    c.mkdir()
    _project(c, [_ARTIFACT_OK], plan=False)
    monkeypatch.chdir(c)
    res = _invoke(c, ["validate", "start", "REQ-001"])
    assert res.exit_code != 0 and "plan" in res.output.lower()
    assert Ledger(c).status_of("REQ-001:validate") is StepStatus.PENDING

    d = tmp_path / "d"
    d.mkdir()
    _project(d, [_ARTIFACT_OK])
    req_path = d / "docs" / "requirements" / "REQ-001.md"
    req_path.write_text(
        req_path.read_text(encoding="utf-8").replace("status: open", "status: done"),
        encoding="utf-8",
    )
    monkeypatch.chdir(d)
    res = _invoke(d, ["validate", "start", "REQ-001"])
    assert res.exit_code != 0 and "steward validate REQ-001" in res.output


# -- AC2: the record half, green ------------------------------------------------


def test_record_green_lands_from_second_process(tmp_path, monkeypatch):
    """A separate `record` invocation resolves the started step + evidence dir from the
    ledger, runs the artifact gate on the capture, takes the manual verdict via the
    engine's interactive prompt, and lands mechanically — flip, index sync, clean tree."""
    _project(tmp_path, [_ARTIFACT_OK, _MANUAL])
    monkeypatch.chdir(tmp_path)
    assert _invoke(tmp_path, ["validate", "start", "REQ-001"]).exit_code == 0
    _capture(tmp_path)

    res = _invoke(tmp_path, ["validate", "record", "REQ-001"], input="a\nproof run reviewed\n")

    assert res.exit_code == 0, res.output
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "done"
    index = (tmp_path / "docs/requirements/REQUIREMENTS_INDEX.md").read_text()
    assert "| DONE |" in index
    vals = [e for e in _events(tmp_path) if e["event"] == "validation"]
    assert len(vals) == 1 and vals[0]["ok"] is True
    assert vals[0]["signoffs"][0]["reviewer"] == "Warm Cycle Test"
    assert Ledger(tmp_path).status_of("REQ-001:validate") is StepStatus.DONE
    assert _git(tmp_path, "status", "--porcelain").strip() == ""


# -- AC3: the record half, red / deferred — the warm-cycle enabler ---------------


def test_record_red_parks_and_rework_accepts_immediately(tmp_path, monkeypatch):
    """A declined verdict parks red and self-commits the ledger close **with no session
    having ended** — and `steward rework` accepts right away (its recorded-red
    precondition, unchanged, is already satisfied)."""
    _project(tmp_path, [_ARTIFACT_OK, _MANUAL])
    monkeypatch.chdir(tmp_path)
    assert _invoke(tmp_path, ["validate", "start", "REQ-001"]).exit_code == 0
    _capture(tmp_path)

    res = _invoke(tmp_path, ["validate", "record", "REQ-001"], input="d\n")

    assert res.exit_code == 1
    assert "validation parked" in res.output and "steward rework REQ-001" in res.output
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:validate") is StepStatus.BLOCKED
    vals = [e for e in _events(tmp_path) if e["event"] == "validation"]
    assert vals[-1]["ok"] is False
    assert _git(tmp_path, "status", "--porcelain").strip() == ""  # close committed

    rework = _invoke(tmp_path, ["rework", "REQ-001"])
    assert rework.exit_code == 0, rework.output
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.RECOVER
    assert led.status_of("REQ-001:validate") is StepStatus.PENDING


def test_record_red_revalidate_also_accepts(tmp_path, monkeypatch):
    """The external-cause edge accepts the standalone-recorded red identically — develop
    stays DONE, only validate re-arms."""
    _project(tmp_path, [_ARTIFACT_OK, _MANUAL])
    monkeypatch.chdir(tmp_path)
    assert _invoke(tmp_path, ["validate", "start", "REQ-001"]).exit_code == 0
    _capture(tmp_path)
    assert _invoke(tmp_path, ["validate", "record", "REQ-001"], input="d\n").exit_code == 1

    reval = _invoke(tmp_path, ["revalidate", "REQ-001"])
    assert reval.exit_code == 0, reval.output
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.DONE
    assert led.status_of("REQ-001:validate") is StepStatus.PENDING


def test_record_red_deferred_verdict_parks_pending(tmp_path, monkeypatch):
    """A deferred verdict is async QA, not a red: the step parks pending with a clean
    tree, nothing recorded — the warm work-item stands."""
    _project(tmp_path, [_ARTIFACT_OK, _MANUAL])
    monkeypatch.chdir(tmp_path)
    assert _invoke(tmp_path, ["validate", "start", "REQ-001"]).exit_code == 0
    _capture(tmp_path)

    res = _invoke(tmp_path, ["validate", "record", "REQ-001"], input="p\n")

    assert res.exit_code == 1 and "async QA" in res.output
    assert not [e for e in _events(tmp_path) if e["event"] == "validation"]
    assert _git(tmp_path, "status", "--porcelain").strip() == ""


def test_record_red_refuses_manual_verdict_inside_claude_session(tmp_path, monkeypatch):
    """The second-shell mandate has teeth where it matters: with a fresh manual AC due,
    `record` inside a Claude session refuses (the session can neither host nor relay the
    verdict) and the started step stays RUNNING — the warm cycle is not consumed."""
    _project(tmp_path, [_ARTIFACT_OK, _MANUAL])
    monkeypatch.chdir(tmp_path)
    assert _invoke(tmp_path, ["validate", "start", "REQ-001"]).exit_code == 0
    _capture(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")

    res = _invoke(tmp_path, ["validate", "record", "REQ-001"], input="a\n\n")

    assert res.exit_code != 0 and "plain shell" in res.output
    assert Ledger(tmp_path).status_of("REQ-001:validate") is StepStatus.RUNNING
    assert not [e for e in _events(tmp_path) if e["event"] == "validation"]


# -- AC4: the full warm cycle across processes -----------------------------------


def test_full_cycle_red_rework_revalidate_green(tmp_path, monkeypatch):
    """start → capture → record-decline (separate invocation) → rework → repaired develop
    closed → start again → record-approve → land: the whole loop over one project, every
    leg its own process, no step ever forcing the (simulated) warm session down."""
    _project(tmp_path, [_ARTIFACT_OK, _MANUAL])
    monkeypatch.chdir(tmp_path)
    assert _invoke(tmp_path, ["validate", "start", "REQ-001"]).exit_code == 0
    _capture(tmp_path)
    assert _invoke(tmp_path, ["validate", "record", "REQ-001"], input="d\n").exit_code == 1
    assert _invoke(tmp_path, ["rework", "REQ-001"]).exit_code == 0

    # The repaired develop, checkpointed (the checkpoint machinery has its own tests).
    led = Ledger(tmp_path)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.save()

    res = _invoke(tmp_path, ["validate", "start", "REQ-001"])
    assert res.exit_code == 0, res.output
    _capture(tmp_path, "repaired behaviour\n")
    res = _invoke(tmp_path, ["validate", "record", "REQ-001"], input="a\n\n")
    assert res.exit_code == 0, res.output

    vals = [e for e in _events(tmp_path) if e["event"] == "validation"]
    assert [v["ok"] for v in vals] == [False, True]
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "done"
    assert _git(tmp_path, "status", "--porcelain").strip() == ""


def test_full_cycle_revalidate_scoped_carry(tmp_path, monkeypatch):
    """On the revalidate edge the warm re-run is scoped per REQ-075: start names only the
    red ACs, the green one-off's evidence is carried forward with provenance, and the
    scoped record lands."""
    red_ac = {"id": "AC4", "test": "test -f fixed.marker", "check": "artifact"}
    _project(tmp_path, [_ARTIFACT_OK, red_ac])
    monkeypatch.chdir(tmp_path)
    assert _invoke(tmp_path, ["validate", "start", "REQ-001"]).exit_code == 0
    _capture(tmp_path)
    res = _invoke(tmp_path, ["validate", "record", "REQ-001"])  # no manual → no prompt
    assert res.exit_code == 1  # AC4 red (fixed.marker absent)

    assert _invoke(tmp_path, ["revalidate", "REQ-001"]).exit_code == 0
    (tmp_path / "fixed.marker").write_text("external cause fixed\n", encoding="utf-8")

    time.sleep(1.1)  # the dated dir name is second-granular; carry needs a distinct dir
    res = _invoke(tmp_path, ["validate", "start", "REQ-001"])
    assert res.exit_code == 0, res.output
    assert "scoped re-run (REQ-075): AC4" in res.output
    res = _invoke(tmp_path, ["validate", "record", "REQ-001"])
    assert res.exit_code == 0, res.output

    vals = [e for e in _events(tmp_path) if e["event"] == "validation"]
    assert vals[-1]["ok"] is True
    carried = vals[-1]["carried"]
    assert [c["ac"] for c in carried] == ["AC2"]  # the green one-off rode in
    assert carried[0]["source_evidence"]  # with provenance
    assert parse_req(tmp_path / "docs/requirements/REQ-001.md").status == "done"


# -- AC5: shape A unchanged -------------------------------------------------------


def test_shape_a_claudecode_refusal_names_the_halves(tmp_path, monkeypatch):
    """Bare `steward validate` still refuses inside a Claude session — and the refusal
    now points at commands that exist: start here, record from a plain shell."""
    _project(tmp_path, [_ARTIFACT_OK, _MANUAL])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")

    res = _invoke(tmp_path, ["validate", "REQ-001"])

    assert res.exit_code != 0
    assert "steward validate start REQ-001" in res.output
    assert "steward validate record REQ-001" in res.output
    assert Ledger(tmp_path).status_of("REQ-001:validate") is StepStatus.PENDING


def test_shape_a_record_without_start_refuses(tmp_path, monkeypatch):
    """`record` grades exactly one started, unrecorded validation: on a PENDING step it
    refuses pointing at `start`."""
    _project(tmp_path, [_ARTIFACT_OK, _MANUAL])
    monkeypatch.chdir(tmp_path)

    res = _invoke(tmp_path, ["validate", "record", "REQ-001"])

    assert res.exit_code != 0
    assert "steward validate start REQ-001" in res.output


def test_shape_a_usage_forms(tmp_path, monkeypatch):
    """The dispatch accepts exactly the three documented forms."""
    _project(tmp_path, [_ARTIFACT_OK])
    monkeypatch.chdir(tmp_path)
    assert _invoke(tmp_path, ["validate", "start"]).exit_code != 0
    assert _invoke(tmp_path, ["validate", "start", "REQ-001", "extra"]).exit_code != 0
    res = _invoke(tmp_path, ["validate", "bogus", "REQ-001"])
    assert res.exit_code != 0 and "usage" in res.output.lower()


# -- AC6: the artifact grading test (engine-run under `steward validate REQ-081`) --


def test_evidence_warm_cycle_sequence():
    """Grades the ledger-event excerpt captured from the real out-of-band warm cycle
    (REQ-081 Decision 7): a red validation, then a rework/revalidate issued from a shell,
    then a green validation on the same step. Runs under `steward validate REQ-081`, which
    injects DEVSTEWARD_EVIDENCE_DIR (REQ-075); it is a declared artifact AC, deselected
    project-wide from every develop gate (REQ-068) — ad-hoc local runs skip it."""
    evidence = os.environ.get("DEVSTEWARD_EVIDENCE_DIR")
    if not evidence:
        pytest.skip(
            "artifact grading test — runs under `steward validate REQ-081` "
            "(the engine injects DEVSTEWARD_EVIDENCE_DIR per REQ-075)"
        )
    path = Path(evidence) / "warm-cycle-events.jsonl"
    assert path.is_file(), (
        f"warm-cycle-events.jsonl missing from {evidence} — the System Tester must "
        f"capture the warm cycle's ledger-event excerpt"
    )
    events = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

    red = next(
        (i for i, e in enumerate(events)
         if e.get("event") == "validation" and e.get("ok") is False), None
    )
    assert red is not None, "no red validation in the captured excerpt"
    step = events[red]["step"]
    req = events[red]["req"]
    edge = next(
        (i for i, e in enumerate(events[red + 1:], red + 1)
         if e.get("event") in ("rework", "revalidate") and e.get("req") == req), None
    )
    assert edge is not None, f"no rework/revalidate edge after the red validation on {req}"
    green = next(
        (i for i, e in enumerate(events[edge + 1:], edge + 1)
         if e.get("event") == "validation" and e.get("step") == step
         and e.get("ok") is True), None
    )
    assert green is not None, f"no green validation on {step} after the return edge"
