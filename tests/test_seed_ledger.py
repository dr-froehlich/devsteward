"""REQ-022 — ``steward seed-ledger``: seed a ledger for an already-built corpus.

Every terminal REQ's phase-step(s) become ``done`` with a provenance event; active/draft
REQs are left for the engine; the operation is idempotent and dialect-independent (lettered
ids seed via the same opaque path). See plan 0006.
"""

from __future__ import annotations

from click.testing import CliRunner
from conftest import write_req

from devsteward.cli import main
from devsteward.core.ledger import Ledger
from devsteward.core.model import StepStatus
from devsteward.profiles.req.seed import seed_ledger
from devsteward.profiles.req.source import ReqStepSource


def _seed(project, req_dir):
    """Run the seeder against a project's ledger; reload and return it."""
    seeded = seed_ledger(Ledger(project), req_dir)
    return Ledger(project), seeded


def test_seeds_terminal_reqs_done(project):
    """AC1 — seed-ledger sets the develop step (and the validate step, when the REQ declared
    an artifact/manual AC) of every terminal REQ (done/dropped/superseded) to done."""
    req_dir = project / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="done")  # regression-only → develop step only
    write_req(req_dir, "REQ-002", status="dropped")
    write_req(req_dir, "REQ-003", status="superseded")
    write_req(req_dir, "REQ-004", status="done", check="artifact")  # → +validate step

    led, seeded = _seed(project, req_dir)

    assert set(seeded) == {"REQ-001", "REQ-002", "REQ-003", "REQ-004"}
    for rid in ("REQ-001", "REQ-002", "REQ-003", "REQ-004"):
        assert led.status_of(f"{rid}:develop") is StepStatus.DONE
    # Only the artifact-declaring REQ gets a validate step seeded.
    assert led.status_of("REQ-004:validate") is StepStatus.DONE
    assert led.status_of("REQ-001:validate") is StepStatus.PENDING


def test_active_and_draft_reqs_not_seeded(project):
    """AC2 — active (open/in-progress/blocked) and draft REQs are left untouched: their
    steps stay pending so the engine still drives them."""
    req_dir = project / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open")
    write_req(req_dir, "REQ-002", status="in-progress")
    write_req(req_dir, "REQ-003", status="blocked")
    write_req(req_dir, "REQ-004", status="draft")
    write_req(req_dir, "REQ-005", status="done")  # one terminal control

    led, seeded = _seed(project, req_dir)

    assert seeded == ["REQ-005"]
    for rid in ("REQ-001", "REQ-002", "REQ-003", "REQ-004"):
        assert led.status_of(f"{rid}:develop") is StepStatus.PENDING
    assert led.status_of("REQ-005:develop") is StepStatus.DONE


def test_provenance_event_and_idempotent(project):
    """AC3 — each newly-seeded REQ appends one ledger_seed provenance event; re-running is
    idempotent (no duplicate events, no error, nothing re-seeded)."""
    req_dir = project / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="done")
    write_req(req_dir, "REQ-002", status="done")

    led1, seeded1 = _seed(project, req_dir)
    seed_events = [e for e in led1.events() if e["event"] == "ledger_seed"]
    assert sorted(seeded1) == ["REQ-001", "REQ-002"]
    assert {e["req"] for e in seed_events} == {"REQ-001", "REQ-002"}
    assert len(seed_events) == 2  # exactly one per seeded REQ

    # Re-run: nothing already-done is re-seeded, no duplicate events, no error.
    led2, seeded2 = _seed(project, req_dir)
    assert seeded2 == []
    assert len([e for e in led2.events() if e["event"] == "ledger_seed"]) == 2


def test_seeded_corpus_yields_no_active_steps(project):
    """AC4 — after seeding a fully-terminal corpus, the work queue is empty: the step source
    derives no steps, so advance is a no-op."""
    req_dir = project / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="done")
    write_req(req_dir, "REQ-002", status="done", check="artifact")
    write_req(req_dir, "REQ-003", status="superseded")

    led, seeded = _seed(project, req_dir)

    assert len(seeded) == 3
    # The step source emits steps only for active REQs — a fully-terminal corpus yields none.
    assert ReqStepSource(req_dir).steps(led) == []
    # And every seeded step is recorded done in the overlay.
    assert all(s is StepStatus.DONE for s in led.all_statuses().values())


def test_seeds_lettered_id_req(project):
    """AC5 — a terminal lettered-id REQ (REQ-NNNx) is seeded correctly via the opaque step
    path (the ids are built by string, never assuming exactly three digits)."""
    req_dir = project / "docs" / "requirements"
    write_req(req_dir, "REQ-099z", status="done")

    led, seeded = _seed(project, req_dir)

    assert seeded == ["REQ-099z"]
    assert led.status_of("REQ-099z:develop") is StepStatus.DONE


def test_errors_without_initialized_ledger(tmp_path, monkeypatch):
    """AC6 — seed-ledger errors cleanly when run with no initialized ledger (no traceback,
    non-zero exit, a message pointing at how to initialize)."""
    monkeypatch.chdir(tmp_path)  # an empty dir — no .devsteward/ here or above
    result = CliRunner().invoke(main, ["seed-ledger"])
    assert result.exit_code != 0, result.output
    assert "Traceback" not in result.output
    assert ".devsteward" in result.output or "steward new" in result.output
