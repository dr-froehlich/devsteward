"""REQ-092 — the compass may be handed on.

Rule 6 of :mod:`devsteward.lint` used to pin the north star to the literal id ``REQ-001``
and refuse any ``dropped``/``superseded`` status on it — the very move the method
prescribes ("direction changes by superseding REQ-001"), which blocked DriveSteward
REQ-016's land. The rule now guards the *role*: REQ-001 may retire once a live heir
carrying the ``north-star`` tag has taken it over.

The oracle is a lint problem list over requirement dirs the test writes itself, so every
branch — including the ones no real project has reached yet (a two-hop chain, a dead
heir, a supersedes cycle) — is exercised without a service, a secret or a network.
"""

from __future__ import annotations

import os
from importlib.resources import files
from pathlib import Path

from devsteward.config import Config, load_config
from devsteward.lint import lint

from conftest import write_index, write_req

REPO_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATES = files("devsteward") / "templates"


def _cfg(tmp_path) -> Config:
    return Config(root=tmp_path, requirements_dir="reqs",
                  index_file="reqs/REQUIREMENTS_INDEX.md")


def _compass_problems(tmp_path) -> list[str]:
    """The lint problems attributable to rule 6 (the other rules stay green here)."""
    return [p for p in lint(_cfg(tmp_path)) if "north star" in p]


def _project(tmp_path, reqs: list[dict]) -> Path:
    """Write a synthetic requirement dir + a matching index from ``reqs`` specs."""
    req_dir = tmp_path / "reqs"
    for spec in reqs:
        write_req(req_dir, spec["rid"], status=spec.get("status", "open"),
                  supersedes=spec.get("supersedes"), tags=spec.get("tags", ()))
    write_index(req_dir, [(s["rid"], s["rid"], s.get("status", "open").upper(), "–")
                          for s in reqs])
    return req_dir


# --- the compass is held ------------------------------------------------------------

def test_live_north_star_is_silent(tmp_path):
    """Today's ordinary project: REQ-001 is live and the rule has nothing to say."""
    _project(tmp_path, [{"rid": "REQ-001", "status": "open", "tags": ["north-star"]}])
    assert _compass_problems(tmp_path) == []


def test_superseded_north_star_with_a_live_tagged_heir_passes(tmp_path):
    """The DriveSteward REQ-016 shape — the move that used to be refused."""
    _project(tmp_path, [
        {"rid": "REQ-001", "status": "superseded", "tags": ["north-star"]},
        {"rid": "REQ-002", "status": "open", "supersedes": "REQ-001",
         "tags": ["north-star"]},
    ])
    assert _compass_problems(tmp_path) == []


def test_a_draft_heir_still_counts(tmp_path):
    """Decision 4: any non-terminal status holds the role — the rule names the compass,
    it does not adjudicate whether the compass has been adopted."""
    _project(tmp_path, [
        {"rid": "REQ-001", "status": "superseded", "tags": ["north-star"]},
        {"rid": "REQ-002", "status": "draft", "supersedes": "REQ-001",
         "tags": ["north-star"]},
    ])
    assert _compass_problems(tmp_path) == []


def test_two_hop_chain_resolves(tmp_path):
    """Decision 3: a project that changes direction twice — 001 -> 002 -> 003."""
    _project(tmp_path, [
        {"rid": "REQ-001", "status": "superseded", "tags": ["north-star"]},
        {"rid": "REQ-002", "status": "superseded", "supersedes": "REQ-001",
         "tags": ["north-star"]},
        {"rid": "REQ-003", "status": "open", "supersedes": "REQ-002",
         "tags": ["north-star"]},
    ])
    assert _compass_problems(tmp_path) == []


def test_supersedes_list_containing_the_north_star_counts(tmp_path):
    """A design that retires a whole stack (REQ-048) names them all in one list."""
    _project(tmp_path, [
        {"rid": "REQ-001", "status": "superseded", "tags": ["north-star"]},
        {"rid": "REQ-002", "status": "done"},
        {"rid": "REQ-003", "status": "open", "supersedes": ["REQ-002", "REQ-001"],
         "tags": ["north-star"]},
    ])
    assert _compass_problems(tmp_path) == []


# --- the compass is lost ------------------------------------------------------------

def test_superseded_with_no_heir_at_all_refuses(tmp_path):
    _project(tmp_path, [{"rid": "REQ-001", "status": "superseded",
                         "tags": ["north-star"]}])
    problems = _compass_problems(tmp_path)
    assert len(problems) == 1
    # Decision 6: the message names both conditions an heir must meet.
    assert "supersedes: REQ-001" in problems[0] and "north-star" in problems[0]


def test_heir_without_the_tag_refuses(tmp_path):
    """A REQ may retire the north star for a scoped reason without becoming the compass."""
    _project(tmp_path, [
        {"rid": "REQ-001", "status": "superseded", "tags": ["north-star"]},
        {"rid": "REQ-002", "status": "open", "supersedes": "REQ-001"},
    ])
    assert len(_compass_problems(tmp_path)) == 1


def test_tagged_heir_that_is_itself_retired_refuses(tmp_path):
    """The chain ends in a dead heir: nobody live holds the role."""
    _project(tmp_path, [
        {"rid": "REQ-001", "status": "superseded", "tags": ["north-star"]},
        {"rid": "REQ-002", "status": "superseded", "supersedes": "REQ-001",
         "tags": ["north-star"]},
    ])
    assert len(_compass_problems(tmp_path)) == 1


def test_untagged_heir_may_still_carry_the_chain(tmp_path):
    """The tag is required of the *holder*, not of every link: an untagged intermediate
    that is itself superseded by a tagged live REQ keeps the chain walkable."""
    _project(tmp_path, [
        {"rid": "REQ-001", "status": "superseded", "tags": ["north-star"]},
        {"rid": "REQ-002", "status": "superseded", "supersedes": "REQ-001"},
        {"rid": "REQ-003", "status": "open", "supersedes": "REQ-002",
         "tags": ["north-star"]},
    ])
    assert _compass_problems(tmp_path) == []


# --- the same rule, whichever verb retired it (Decision 5) ---------------------------

def test_dropped_north_star_is_judged_identically(tmp_path):
    _project(tmp_path, [
        {"rid": "REQ-001", "status": "dropped", "tags": ["north-star"]},
        {"rid": "REQ-002", "status": "open", "supersedes": "REQ-001",
         "tags": ["north-star"]},
    ])
    assert _compass_problems(tmp_path) == []


def test_dropped_north_star_without_an_heir_refuses(tmp_path):
    _project(tmp_path, [{"rid": "REQ-001", "status": "dropped", "tags": ["north-star"]}])
    assert len(_compass_problems(tmp_path)) == 1


# --- the walk terminates ------------------------------------------------------------

def test_supersedes_cycle_terminates(tmp_path):
    """A hand-written cycle must not hang the linter; it simply holds no compass."""
    _project(tmp_path, [
        {"rid": "REQ-001", "status": "superseded", "tags": ["north-star"]},
        {"rid": "REQ-002", "status": "superseded", "supersedes": "REQ-003"},
        {"rid": "REQ-003", "status": "superseded", "supersedes": "REQ-002"},
    ])
    assert len(_compass_problems(tmp_path)) == 1


def test_absent_north_star_is_silent(tmp_path):
    """A project with no REQ-001 at all (an import) is outside the rule's purview."""
    _project(tmp_path, [{"rid": "REQ-002", "status": "open"}])
    assert _compass_problems(tmp_path) == []


# --- AC2: the engine's own repo and the orientation surfaces ------------------------

def _norm(text: str) -> str:
    return " ".join(text.split())


def _skill(name: str) -> str:
    return _norm((_TEMPLATES / ".claude" / "skills" / name / "SKILL.md")
                 .read_text(encoding="utf-8"))


def test_surfaces_and_self_lint() -> None:
    """DevSteward's own REQ set stays green under the rewritten rule, and the two
    orientation skills teach the chain — read from the *stamped templates*, which are the
    same inode as the repo's live skills (asserted below), so one edit covers both."""
    assert lint(load_config(REPO_ROOT)) == []

    for name in ("intake", "bootstrap"):
        text = _skill(name)
        assert "live compass" in text, (
            f"the {name} skill does not name the live compass — a session would orient on "
            f"a retired REQ-001 after a supersede"
        )
        assert "north-star" in text, (
            f"the {name} skill does not name the north-star tag an heir must carry"
        )

        repo_skill = REPO_ROOT / ".claude" / "skills" / name / "SKILL.md"
        template = REPO_ROOT / "devsteward" / "templates" / ".claude" / "skills" / name \
            / "SKILL.md"
        assert os.stat(repo_skill).st_ino == os.stat(template).st_ino, (
            f"{name}: the repo skill and its stamped template are no longer one inode — "
            f"the hardlink was broken, so the two copies can now drift"
        )
