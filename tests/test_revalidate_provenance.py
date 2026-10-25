"""REQ-035 — re-validating a done REQ leaves ``verified_by`` frozen.

A ``done`` re-validation (``steward validate`` on a done REQ → ``revalidate``,
``in_flight=False``) is a sanctioned, *non-mutating* re-check (REQ-030 D5): it appends a
fresh dated evidence event (REQ-030 D3) and must leave the REQ file untouched — status
*and* ``verified_by`` stay the frozen landing provenance ("done is never weakened",
REQ-001). The guard is scoped strictly to the done path: an in-flight first validation still
composes and writes ``verified_by`` as the landing provenance being established.

Wired like ``test_system_test_phase.py`` (the REQ profile's real source/verifier/flipper/
land-gate/validate routine around the fake System-Tester runner + in-memory git topology).
"""

from __future__ import annotations

from click.testing import CliRunner

from devsteward.cli import main as cli_main
from devsteward.core.executor import RunOutcome, StepResult
from devsteward.core.ledger import Ledger
from devsteward.profiles.req.reqfile import parse_req
from devsteward.profiles.req.validate import ReqValidateRoutine

from conftest import FakeGitTopology, write_index
from test_system_test_phase import (
    _events,
    _executor,
    _project,
    _validation_events,
    _write_req,
    _REGRESSION,
    _ARTIFACT_OK,
)

_CONFIG = """\
profile: req
accounts:
  provider: single
git:
  production_branch: main
  integration_branch: dev
"""


# -- AC1 ------------------------------------------------------------------------


def test_done_revalidation_leaves_verified_by_and_status_frozen(tmp_path):
    """A done re-validation appends a fresh evidence event (per-AC results + artifact
    hashes) yet leaves the REQ file byte-identical — status and ``verified_by`` both frozen.
    The clobber the postmortem caught is gone (REQ-035 Decisions 1/4)."""
    _project(tmp_path, [_REGRESSION, _ARTIFACT_OK])
    git = FakeGitTopology(current="dev")
    ex = _executor(tmp_path, git=git)
    ex.advance_once(only="REQ-001")  # develop (deferred land)

    routine = ex.validate_runner
    step = ex.step_by_id("REQ-001:validate")
    res = routine(ex, step, unattended=False, driver="interactive")
    assert res.outcome is RunOutcome.DONE  # the in-flight land proceeded

    req_path = tmp_path / "docs/requirements/REQ-001.md"
    landed = parse_req(req_path)
    assert landed.status == "done"
    frozen_verified_by = landed.frontmatter["verified_by"]
    assert frozen_verified_by and "validation green" in frozen_verified_by
    before_bytes = req_path.read_bytes()
    n_events_before = len(_validation_events(tmp_path))

    # done re-validation: append-only evidence, the REQ file untouched.
    res2 = routine.revalidate(ex, "REQ-001")
    assert res2.outcome is RunOutcome.DONE
    assert req_path.read_bytes() == before_bytes  # status + verified_by byte-identical
    after = parse_req(req_path)
    assert after.status == "done"
    assert after.frontmatter["verified_by"] == frozen_verified_by

    fresh_events = _validation_events(tmp_path)
    assert len(fresh_events) == n_events_before + 1  # a fresh event WAS appended
    fresh = fresh_events[-1]
    assert fresh["rerun"] is True
    assert fresh["results"]  # per-AC results carried
    assert fresh["artifacts"] and all("sha256" in a for a in fresh["artifacts"])
    # REQ-048: a done re-validation lands nothing — the checkpoint count is unchanged.
    assert len([e for e in _events(tmp_path) if e["event"] == "checkpoint"]) == 1


# -- AC2 ------------------------------------------------------------------------


def test_in_flight_validation_still_writes_verified_by(tmp_path):
    """The guard is scoped to the done re-run: an in-flight REQ's first green validation
    still composes and writes ``verified_by`` (the landing provenance) — the fix must not
    over-correct and strangle the landing path (REQ-035 Decision 2)."""
    _project(tmp_path, [_REGRESSION, _ARTIFACT_OK])
    ex = _executor(tmp_path)
    ex.advance_once(only="REQ-001")  # develop (deferred land)

    step = ex.step_by_id("REQ-001:validate")
    res = ex.validate_runner(ex, step, unattended=False, driver="interactive")
    assert res.outcome is RunOutcome.DONE

    req = parse_req(tmp_path / "docs/requirements/REQ-001.md")
    assert req.status == "done"
    verified_by = req.frontmatter["verified_by"]
    assert verified_by and verified_by != "null"
    assert "validation green" in verified_by  # the landing provenance was established


# -- AC3 ------------------------------------------------------------------------


def test_revalidate_cli_message_is_honest(tmp_path, monkeypatch):
    """The done re-validation CLI message states fresh evidence was recorded and the REQ
    file (status + ``verified_by``) is unchanged; it neither claims nor performs a
    provenance rewrite (REQ-035 Decision 3). ``revalidate`` is stubbed so the message branch
    is isolated from a real System-Tester session."""
    req_dir = tmp_path / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", [_REGRESSION, _ARTIFACT_OK], status="done")
    write_index(req_dir, [("REQ-001", "REQ-001 title", "DONE", "–")])
    Ledger.init(tmp_path)
    (tmp_path / ".devsteward" / "config.yaml").write_text(_CONFIG, encoding="utf-8")

    monkeypatch.setattr(
        ReqValidateRoutine,
        "revalidate",
        lambda self, ex, req_id, **kw: StepResult(None, RunOutcome.DONE, "ok"),
    )
    monkeypatch.chdir(tmp_path)
    out = CliRunner().invoke(cli_main, ["validate", "REQ-001"]).output

    assert "fresh evidence recorded" in out
    assert "verified_by" in out
    assert "frozen" in out or "unchanged" in out
    assert "rewrite" not in out.lower() and "overwrite" not in out.lower()
