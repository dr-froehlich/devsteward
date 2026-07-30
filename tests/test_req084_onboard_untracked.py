"""REQ-084 half B — the operator-only ``onboard`` skill does not ship to consumers.

REQ-024 Decision 2 already ruled it ("Lives in DevSteward's **own** ``.claude/skills/``, not
in ``templates/`` … Bundling it would ship dead scaffolding"), but the commit that recorded
the decision added the template copy anyway and every consumer has received it since. The
repo's ``.claude/skills`` is a *symlink* onto the template tree — one file per skill, no
second copy — so the skill stays where it is and the engine filters it by name at the two
places that ship it: the stamp and the tracked set.
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from devsteward import skillsync
from devsteward.cli import _package_templates, main

_REPO_ROOT = Path(__file__).resolve().parents[1]
#: The skills a consumer legitimately receives.
_CONSUMER_SKILLS = {"advance", "bootstrap", "intake", "system-test"}


def _stamp_project(tmp_path: Path) -> Path:
    target = tmp_path / "consumer"
    result = CliRunner().invoke(main, ["new", str(target)])
    assert result.exit_code == 0, result.output
    return target


# -- AC5 ----------------------------------------------------------------------


def test_onboard_left_the_stamped_set(tmp_path):
    """Both directions pinned: ``onboard`` is excluded from what ships and tracks, and the
    four consumer skills still do."""
    templates = _package_templates()

    assert skillsync.OPERATOR_ONLY == frozenset({"onboard"})
    names = set(skillsync.bundled_skill_names(templates))
    assert "onboard" not in names
    assert _CONSUMER_SKILLS <= names, "the consumer skills must still ship"

    tracked = {a.key for a in skillsync.tracked_artifacts(templates)}
    assert "onboard" not in tracked
    assert _CONSUMER_SKILLS <= tracked

    target = _stamp_project(tmp_path)
    skills = target / ".claude" / "skills"
    assert not (skills / "onboard").exists(), "steward new must not stamp the operator skill"
    for skill in sorted(_CONSUMER_SKILLS):
        assert (skills / skill / "SKILL.md").is_file()
    assert "onboard" not in skillsync.read_lock(target)

    # The operator's own copy is untouched and still declares what it is — DevSteward's
    # `.claude/skills` is a symlink onto the template tree, so this is that same file.
    operator = _REPO_ROOT / ".claude" / "skills" / "onboard" / "SKILL.md"
    assert operator.is_file()
    assert "operator tool" in operator.read_text(encoding="utf-8")


# -- AC6 ----------------------------------------------------------------------


def test_stray_onboard_is_inert(tmp_path):
    """A consumer stamped before REQ-084 keeps its ``onboard/`` copy: the engine never
    deletes a consumer file. It simply stops tracking it — no drift record, no refresh, and
    the next sync prunes the dead key from the provenance lock."""
    target = _stamp_project(tmp_path)
    stray = target / ".claude" / "skills" / "onboard"
    stray.mkdir(parents=True)
    (stray / "SKILL.md").write_text("stale operator skill\n", encoding="utf-8")

    lock_path = skillsync.lock_path(target)
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["onboard"] = "deadbeef"
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    templates = _package_templates()
    assert [d.name for d in skillsync.drift(target, templates) if d.name == "onboard"] == []

    result = skillsync.sync(target, templates)
    assert "onboard" not in result.synced + result.forced + result.refused + result.unchanged

    # Left exactly as the consumer had it — theirs to keep or delete by hand.
    assert (stray / "SKILL.md").read_text(encoding="utf-8") == "stale operator skill\n"
    assert not (stray / "SKILL.md.orig").exists()

    # The manifest records the tracked artifacts and nothing else.
    after = skillsync.read_lock(target)
    assert "onboard" not in after
    assert set(after) == {a.key for a in skillsync.tracked_artifacts(templates)}
