"""REQ-073 D2 — the stale-decision recovery path.

Once a stale save has rewound the cursor behind a committed land, ``state.yaml`` can hold an
**open** ``:validate`` decision for a REQ that is already ``done`` — the diverged ledger the
lost-update guard (D1) now prevents going forward, but which existed in the wild (FlowSteward
DEC-044). Before REQ-073 there was no verb back: ``steward validate`` on a done REQ routed to
the non-mutating revalidate, and ``steward decision answer`` refused a ``:validate`` decision
and redirected to ``steward validate`` — the two remedies pointed at each other, and the only
exit was hand-editing state.yaml (forbidden).

REQ-073 makes ``steward validate REQ-NNN`` on a done REQ first reconcile any lingering open
``:validate`` decision from the event log — the exact verb the REQ-057 guard already
redirects to. The guard stays unchanged; its redirect target now resolves the divergence, so
the loop terminates.

Wired like ``test_revalidate_provenance.py`` — a real ``Ledger`` + config + REQ file under a
temp root, driven through the ``steward`` CLI (CliRunner). Hermetic (REQ-064 screen).
"""

from __future__ import annotations

from click.testing import CliRunner
from ruamel.yaml import YAML

from devsteward.cli import main as cli_main
from devsteward.core.ledger import Ledger
from devsteward.core.model import Decision, DecisionStatus
from devsteward.profiles.req.reqfile import parse_req

from conftest import write_index
from test_system_test_phase import _write_req, _REGRESSION

_CONFIG = """\
profile: req
accounts:
  provider: single
git:
  production_branch: main
  integration_branch: dev
"""

_FROZEN_VERIFIED_BY = "validation green 2026-07-02; signed off by Petra"


def _diverged_ledger(tmp_path):
    """A done REQ whose state.yaml still holds an open :validate decision — the divergence a
    stale save produced. Returns the REQ file path (with a real frozen ``verified_by``)."""
    req_dir = tmp_path / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", [_REGRESSION], status="done")
    req_path = req_dir / "REQ-001.md"
    # Give the landed REQ a real frozen landing provenance to prove recovery never touches it.
    req_path.write_text(
        req_path.read_text(encoding="utf-8").replace(
            "verified_by: null", f"verified_by: {_FROZEN_VERIFIED_BY}"
        ),
        encoding="utf-8",
    )
    write_index(req_dir, [("REQ-001", "REQ-001 title", "DONE", "–")])
    Ledger.init(tmp_path)
    (tmp_path / ".devsteward" / "config.yaml").write_text(_CONFIG, encoding="utf-8")
    Ledger(tmp_path).park_decision(
        Decision(id="DEC-001", step="REQ-001:validate",
                 question="record the human sign-off?", req="REQ-001")
    )
    return req_path


# -- AC4 ------------------------------------------------------------------------


def test_validate_on_done_req_closes_stale_validation_decision(tmp_path, monkeypatch):
    """`steward validate REQ-001` on a done REQ with a lingering open :validate decision
    closes it, appends a reconciliation event, leaves verified_by/status frozen (REQ-035),
    and `steward status` no longer surfaces the decision — no hand-edit of state.yaml."""
    req_path = _diverged_ledger(tmp_path)
    before = req_path.read_bytes()
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(cli_main, ["validate", "REQ-001"])
    assert result.exit_code == 0, result.output
    assert "reconciled stale validation decision" in result.output
    assert "DEC-001" in result.output

    after = Ledger(tmp_path)
    assert after.find_decision("DEC-001").status is DecisionStatus.ANSWERED
    assert after.open_decisions() == []  # what `steward status` reads — no longer surfaced
    assert any(
        e["event"] == "decision_reconciled" and e["decision"] == "DEC-001"
        for e in after.events()
    )

    # REQ-035: recovery is a reconciliation of the cursor, not a re-validation — the REQ file
    # (status + verified_by) is byte-identical.
    assert req_path.read_bytes() == before
    req = parse_req(req_path)
    assert req.status == "done"
    assert req.frontmatter["verified_by"] == _FROZEN_VERIFIED_BY

    # And `steward status` itself no longer names the decision.
    status_out = CliRunner().invoke(cli_main, ["status"]).output
    assert "DEC-001" not in status_out


# -- AC5 ------------------------------------------------------------------------


def test_answer_redirect_target_resolves_diverged_state(tmp_path, monkeypatch):
    """No mutually-pointing dead end: `steward decision answer` on the :validate decision
    still refuses and redirects to `steward validate` (REQ-057 guard intact), and following
    that redirect actually resolves the decision (AC4) — the two remedies terminate."""
    _diverged_ledger(tmp_path)
    monkeypatch.chdir(tmp_path)

    # The REQ-057 guard: `decision answer` refuses a :validate hold and redirects — before any
    # mutation, so the decision stays open.
    refused = CliRunner().invoke(cli_main, ["decision", "answer", "DEC-001", "looks good"])
    assert refused.exit_code != 0
    assert "steward validate REQ-001" in refused.output
    mid = Ledger(tmp_path)
    assert mid.find_decision("DEC-001").status is DecisionStatus.OPEN  # guard did not answer it

    # Following the redirect resolves the divergence — the loop terminates.
    resolved = CliRunner().invoke(cli_main, ["validate", "REQ-001"])
    assert resolved.exit_code == 0, resolved.output
    assert "reconciled" in resolved.output.lower()
    after = Ledger(tmp_path)
    assert after.find_decision("DEC-001").status is DecisionStatus.ANSWERED
    assert after.open_decisions() == []
