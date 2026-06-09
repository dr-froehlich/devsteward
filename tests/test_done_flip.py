"""The engine-owned terminal flip: a verified land marks the REQ `done` (frontmatter +
index, in lockstep), and only the land phase does so."""

from __future__ import annotations

from devsteward.core.model import Step
from devsteward.profiles.req.checkpoint import ReqDoneFlipper
from devsteward.profiles.req.index import read_statuses
from devsteward.profiles.req.reqfile import parse_req

from conftest import write_index, write_req


def _flipper(tmp_path):
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-007", status="open")
    write_index(req_dir, [("REQ-007", "seven", "OPEN", "–")])
    index_path = req_dir / "REQUIREMENTS_INDEX.md"
    return ReqDoneFlipper(req_dir, index_path), req_dir, index_path


def test_land_flips_frontmatter_and_index(tmp_path):
    flip, req_dir, index_path = _flipper(tmp_path)
    flip(Step(id="REQ-007:land", command="/advance", req="REQ-007", phase="land"))
    assert parse_req(req_dir / "REQ-007.md").status == "done"
    assert read_statuses(index_path)["REQ-007"] == "done"


def test_non_land_phase_leaves_status_untouched(tmp_path):
    flip, req_dir, index_path = _flipper(tmp_path)
    for phase in ("design", "build"):
        flip(Step(id=f"REQ-007:{phase}", command="/advance", req="REQ-007", phase=phase))
    assert parse_req(req_dir / "REQ-007.md").status == "open"
    assert read_statuses(index_path)["REQ-007"] == "open"


def test_flip_is_idempotent(tmp_path):
    """A re-run (e.g. a second `steward checkpoint`) over an already-done REQ is a no-op."""
    flip, req_dir, index_path = _flipper(tmp_path)
    step = Step(id="REQ-007:land", command="/advance", req="REQ-007", phase="land")
    flip(step)
    flip(step)
    assert parse_req(req_dir / "REQ-007.md").status == "done"
    assert read_statuses(index_path)["REQ-007"] == "done"
