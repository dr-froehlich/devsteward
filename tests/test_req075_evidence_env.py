"""REQ-075 AC3 — the engine hands each `artifact` grading command its evidence dir.

Every engine-run `artifact` grading command receives `DEVSTEWARD_EVIDENCE_DIR` set to the
current run's evidence dir, per-subprocess, **overriding** any stale value inherited from the
launching environment. Covered on both grading subprocess call sites — the non-pytest
`_exit_code` path and the pytest `_pytest_outcome` path — plus the STEWARD.md doc.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from devsteward.profiles.req.validate import EVIDENCE_ENV_VAR
from devsteward.profiles.req.verify import ReqVerifier

from test_system_test_phase import _REGRESSION, _write_req


def _gate(tmp_path, ac, monkeypatch):
    """Run the artifact gate for a single AC with a *stale* inherited value present, so the
    test proves the injected value wins. Returns (results, all_green, evidence_dir)."""
    req_dir = tmp_path / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", [_REGRESSION, ac], status="open")
    routine_root = req_dir
    from devsteward.profiles.req.validate import ReqValidateRoutine

    routine = ReqValidateRoutine(routine_root)
    req = routine._req("REQ-001")
    evidence_dir = tmp_path / ".devsteward" / "evidence" / "REQ-001" / "run"
    evidence_dir.mkdir(parents=True)
    ex = SimpleNamespace(root=tmp_path)
    monkeypatch.setenv(EVIDENCE_ENV_VAR, "/stale/leaked/from/another/req")
    artifact_acs = [c for c in req.acceptance if c.check == "artifact"]
    results, all_green = routine._artifact_gate(ex, req, artifact_acs, evidence_dir)
    return results, all_green, evidence_dir


def test_non_pytest_grading_command_sees_injected_evidence_dir(tmp_path, monkeypatch):
    """A non-pytest artifact command (`_exit_code` path) sees the injected evidence dir, not
    the stale inherited one."""
    # The command writes $DEVSTEWARD_EVIDENCE_DIR into a probe file inside that dir. Only
    # single quotes (YAML-safe inside the double-quoted `test:` scalar); mkdtemp paths have
    # no spaces so the unquoted expansion is safe.
    ac = {
        "id": "AC2",
        "test": "sh -c 'printf %s $DEVSTEWARD_EVIDENCE_DIR > $DEVSTEWARD_EVIDENCE_DIR/probe.txt'",
        "check": "artifact",
    }
    results, all_green, evidence_dir = _gate(tmp_path, ac, monkeypatch)
    assert all_green, results
    probe = (evidence_dir / "probe.txt").read_text()
    assert probe == str(evidence_dir)                    # injected value, absolute, current run
    assert probe != "/stale/leaked/from/another/req"     # the stale value did not win


def test_pytest_grading_command_sees_injected_evidence_dir(tmp_path, monkeypatch):
    """A pytest artifact command (`_pytest_outcome` path) sees the injected evidence dir too
    — the env override reaches the junit-wrapped subprocess."""
    probe_test = tmp_path / "probe_test.py"
    probe_test.write_text(
        "import os\n"
        "def test_evidence_env():\n"
        "    d = os.environ['DEVSTEWARD_EVIDENCE_DIR']\n"
        "    assert d != '/stale/leaked/from/another/req'\n"
        "    open(os.path.join(d, 'pyprobe.txt'), 'w').write(d)\n"
    )
    ac = {"id": "AC2", "test": "python -m pytest probe_test.py", "check": "artifact"}
    results, all_green, evidence_dir = _gate(tmp_path, ac, monkeypatch)
    assert all_green, results
    assert (evidence_dir / "pyprobe.txt").read_text() == str(evidence_dir)


def test_env_helper_overlays_and_overrides(monkeypatch):
    """The subprocess-env helper overlays onto the engine's environment and the overlay wins
    over an inherited value; an empty overlay is a no-op (inherit unchanged)."""
    from devsteward.core.verify import _subprocess_env

    monkeypatch.setenv("PRE_EXISTING", "keep")
    monkeypatch.setenv(EVIDENCE_ENV_VAR, "stale")
    env = _subprocess_env({EVIDENCE_ENV_VAR: "fresh"})
    assert env[EVIDENCE_ENV_VAR] == "fresh"      # overlay wins
    assert env["PRE_EXISTING"] == "keep"          # rest of the environment preserved
    assert _subprocess_env(None) is None          # no overlay → inherit unchanged
    assert _subprocess_env({}) is None


def test_steward_md_documents_the_variable():
    """STEWARD.md (the black-box contract) documents `DEVSTEWARD_EVIDENCE_DIR`."""
    doc = Path(__file__).resolve().parents[1] / "devsteward" / "templates" / "STEWARD.md"
    text = doc.read_text()
    assert EVIDENCE_ENV_VAR in text
