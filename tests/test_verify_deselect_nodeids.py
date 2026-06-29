"""REQ-070 — the develop full-suite deselect set must contain only real node-ids.

REQ-068 Decision 2 deselects every one-time ``artifact``/``manual`` acceptance node-id from
the standing suite. The derivation (:func:`devsteward.build._validation_nodeids` →
:func:`devsteward.core.verify._pytest_targets`) used to tokenize a ``manual:`` AC's *prose*
into deselect targets whenever the prose mentioned ``pytest`` — harvesting bare words like
``tests``. ``pytest --deselect tests`` deselects the whole ``tests/`` tree, so the gate
selected 0 tests: a false signal indistinguishable from a zero-match ``-m regression`` and a
silent neutering of the gate (reproduced on FlowSteward, ``steward 0.2.0``). These tests pin
the fix: a ``manual:`` AC contributes nothing, and only genuine node-ids/paths survive.
"""

from __future__ import annotations

from types import SimpleNamespace

from devsteward.build import _validation_nodeids
from devsteward.core.verify import _pytest_targets

from conftest import write_req

# A perfectly ordinary manual AC: human prose that happens to mention the tool. The fatal
# token is the bare word ``tests``, which ``--deselect tests`` would read as the whole tree.
MANUAL_PROSE = (
    "manual: run `python -m pytest -m not live` and confirm a `0 skipped` summary; "
    "the live tests under `-m live` stay deselected"
)


def test_pytest_targets_emits_only_real_nodeids():
    """AC2: only collectible node-ids/paths survive — never a bare word, dir, or marker value."""
    # a real node-id and a whole-file target are kept (both collectible)
    assert _pytest_targets("python -m pytest tests/test_x.py::test_y") == ["tests/test_x.py::test_y"]
    assert _pytest_targets("python -m pytest tests/test_x.py") == ["tests/test_x.py"]
    # a `-m <marker>` value is dropped along with the flag — only the real target remains
    assert _pytest_targets("python -m pytest -m live tests/test_x.py::test_y") == [
        "tests/test_x.py::test_y"
    ]
    assert _pytest_targets("python -m pytest -m live") == []
    assert _pytest_targets('python -m pytest -m "not live"') == []
    # prose / bare words yield nothing, even though the string contains the token ``pytest``
    assert _pytest_targets(MANUAL_PROSE) == []
    assert "tests" not in _pytest_targets(MANUAL_PROSE)


def test_manual_prose_ac_contributes_no_deselect_targets(tmp_path):
    """AC1: a manual AC whose prose mentions pytest derives no deselect target (never ``tests``)."""
    write_req(tmp_path, "REQ-900", status="done", check="manual", test=MANUAL_PROSE)
    nids = _validation_nodeids(SimpleNamespace(req_dir=tmp_path))
    assert nids == ()
    assert "tests" not in nids


def test_exclude_set_is_pure_nodeids_no_suite_wipe(tmp_path):
    """AC3: a mixed REQ-set yields only the real artifact node-ids — no suite-wiping token."""
    write_req(tmp_path, "REQ-901", status="done", check="artifact",
              test="python -m pytest tests/test_real.py::test_keeps")
    write_req(tmp_path, "REQ-902", status="done", check="manual", test=MANUAL_PROSE)
    write_req(tmp_path, "REQ-903", status="done", check="artifact",
              test="python -m pytest -m live tests/test_live.py::test_e2e")
    nids = _validation_nodeids(SimpleNamespace(req_dir=tmp_path))
    assert set(nids) == {"tests/test_real.py::test_keeps", "tests/test_live.py::test_e2e"}
    # the catastrophic tokens can never reach ``--deselect``
    assert all(n.endswith(".py") or ".py::" in n for n in nids)
    assert "tests" not in nids and "live" not in nids
