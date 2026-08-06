"""REQ-088 Cause A — the evidence-dir mint can never alias two validations.

`_now_stamp()` was second-granular, so a second validation starting inside the same
wall-clock second resolved to the *same* `.devsteward/evidence/<REQ>/<stamp>/` directory as
the first (both mint sites called `mkdir(exist_ok=True)`). `_carry_forward` then walked the
source evidence dir and copied every file onto itself:

    SameFileError: …/evidence/REQ-001/20260806T050731Z/capture.txt
               and …/evidence/REQ-001/20260806T050731Z/capture.txt are the same file

Deterministic teeth: the clock is pinned to one wall-clock second, so these tests force the
collision window rather than racing for it (the old shape needed a `time.sleep(1.1)` pad to
*avoid* it — AC3 guards that the pads stay gone).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from devsteward.profiles.req import validate as validate_mod

from test_req081_halves import _capture, _events, _invoke, _project, _started_evidence
from test_system_test_phase import _ARTIFACT_OK

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def pinned_clock(monkeypatch):
    """Pin `_now_stamp`'s clock to a single wall-clock second.

    The stamp still varies within the second (that is the fix); what is pinned is the second,
    which is exactly the collision window the defect lived in."""
    micros = iter(range(100_000, 1_000_000, 7_919))

    class _Pinned:
        @staticmethod
        def now(tz=None):
            from datetime import datetime, timezone

            return datetime(2026, 8, 6, 5, 7, 31, next(micros), tzinfo=tz or timezone.utc)

    monkeypatch.setattr(validate_mod, "datetime", _Pinned)
    return _Pinned


# -- AC1: two mints in one second are two distinct, fresh directories ----------


def test_same_second_mints_are_distinct(tmp_path, pinned_clock):
    """AC1: with the clock pinned to a single wall-clock second, consecutive mints yield
    distinct directories that did not previously exist — the mint never re-enters an existing
    dir, and it does not rely on `mkdir(exist_ok=True)` to paper over a repeat."""
    seen: list[Path] = []
    for _ in range(5):
        d = validate_mod._mint_evidence_dir(tmp_path, "REQ-001")
        assert d.is_dir()
        assert d not in seen, f"mint returned an already-issued dir: {d}"
        seen.append(d)

    # All within the pinned second, so the collision window is genuinely exercised …
    stamps = [d.name for d in seen]
    assert all(s.startswith("20260806T050731") for s in stamps), stamps
    assert len(set(stamps)) == len(stamps)

    # … and a mint onto an existing dir is refused rather than silently aliased.
    with pytest.raises(FileExistsError):
        seen[0].parent.joinpath(stamps[0]).mkdir(parents=True, exist_ok=False)


def test_recorded_second_granular_paths_still_resolve(tmp_path):
    """AC1 (no migration): evidence paths recorded by the *old* second-granular format are
    read back literally from the event log, never re-derived from the stamp format, so
    history written before this REQ keeps resolving."""
    legacy = tmp_path / ".devsteward" / "evidence" / "REQ-001" / "20260806T050731Z"
    legacy.mkdir(parents=True)
    (legacy / "capture.txt").write_text("legacy evidence\n", encoding="utf-8")

    rel = str(legacy.relative_to(tmp_path))
    assert (tmp_path / rel).is_dir()
    assert (tmp_path / rel / "capture.txt").read_text() == "legacy evidence\n"
    # The engine's own resolution path is a literal join of root + the recorded rel path.
    assert re.fullmatch(r"\.devsteward/evidence/REQ-001/20260806T050731Z", rel)


# -- AC2: a same-second revalidate carries forward without copying onto itself -


def test_same_second_revalidate_carries_without_self_copy(tmp_path, monkeypatch, pinned_clock):
    """AC2: a scoped revalidate started in the same wall-clock second as the validation it
    carries from completes, lands the carried green one-off's artifacts as real files in a
    NEW evidence dir distinct from the source, and records the source_evidence provenance.

    Pre-fix this raised `SameFileError` from `_carry_forward` (dest == src) and the whole
    validate mutation rolled back."""
    red_ac = {"id": "AC4", "test": "test -f fixed.marker", "check": "artifact"}
    _project(tmp_path, [_ARTIFACT_OK, red_ac])
    monkeypatch.chdir(tmp_path)

    assert _invoke(tmp_path, ["validate", "start", "REQ-001"]).exit_code == 0
    source_evidence = _started_evidence(tmp_path)
    _capture(tmp_path)
    assert _invoke(tmp_path, ["validate", "record", "REQ-001"]).exit_code == 1  # AC4 red

    assert _invoke(tmp_path, ["revalidate", "REQ-001"]).exit_code == 0
    (tmp_path / "fixed.marker").write_text("external cause fixed\n", encoding="utf-8")

    # No sleep — the re-start happens inside the same pinned second as the source validation.
    res = _invoke(tmp_path, ["validate", "start", "REQ-001"])
    assert res.exit_code == 0, res.output
    fresh_evidence = _started_evidence(tmp_path)
    assert fresh_evidence != source_evidence, "the re-run aliased the source evidence dir"

    res = _invoke(tmp_path, ["validate", "record", "REQ-001"])
    assert res.exit_code == 0, res.output

    val = [e for e in _events(tmp_path) if e["event"] == "validation"][-1]
    assert val["ok"] is True
    carried = val["carried"]
    assert [c["ac"] for c in carried] == ["AC2"]
    assert carried[0]["source_evidence"] == str(source_evidence.relative_to(tmp_path))
    # The carried artifact is a real file in the NEW dir, not the source file seen twice.
    copied = fresh_evidence / "capture.txt"
    assert copied.is_file()
    assert copied.resolve() != (source_evidence / "capture.txt").resolve()


# -- AC3: the workarounds these defects grew are gone -------------------------


def test_no_sleep_workarounds_remain():
    """AC3: the two `time.sleep(1.1)` pads that existed only to dodge the second-granular
    mint are gone (a padded test cannot disconfirm the bug it sits next to), and the
    REQ-087 surfaces carrying the "re-run before believing a lone red" caveat name REQ-088
    as superseding it."""
    halves = (_REPO / "tests" / "test_req081_halves.py").read_text(encoding="utf-8")
    assert "time.sleep" not in halves, "a sleep workaround came back into test_req081_halves.py"

    for rel in ("docs/requirements/REQ-087.md", "docs/plans/REQ-087-north-star-bootstrap.md"):
        text = (_REPO / rel).read_text(encoding="utf-8")
        if "flake" in text.lower():
            assert "REQ-088" in text, f"{rel} still carries the flake caveat without naming REQ-088"
