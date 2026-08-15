"""REQ-091 — the commit discloses assistance instead of claiming co-authorship.

This file **supersedes** ``tests/test_coauthor_trailer.py`` (REQ-090) rather than sitting
beside it. REQ-090 subtracted the stale model name and the address from the trailer, leaving
a bare ``Co-Authored-By: Claude``; that removed the *stale* part and kept the *false* one.
Authorship is a claim a model cannot hold — no copyright, no CLA, no DCO — and GitHub only
parses the key when it carries a resolvable address, so the bare form was not even
attribution any more. REQ-091 changes the claim instead of blanking the field:
``Assisted-by: <agent>:<version>``, the Linux kernel's shape
(``Documentation/process/coding-assistants.rst``, 2025-12-23).

What moved here from the retired file, and why the shapes are kept:

* the repo-wide **scan** (AC9) — strictly stronger than REQ-090's, since it forbids the key
  outright rather than policing what sits inside it;
* the ``MODEL_TOKEN`` regex, the ``_scannable_files`` walker and ``PRUNE_DIRS``, imported by
  :mod:`tests.test_req091_model_surfacing` for AC4 (REQ-090's surviving invariant: no model
  identifier in engine Python);
* the walker is deliberately **not** ``git ls-files`` — REQ-063's capture check re-runs each
  acceptance test from a bare extract of the recorded commit, which is not a git repository,
  so a git-dependent scan reds there while passing in the working tree.

REQ-090's ``test_engine_commits_carry_generic_trailer`` has no successor by design: it
asserted the exact string this REQ retires. :func:`test_engine_commit_discloses_resolved_model`
answers the same question the bug report asked (``git log -1 --format='%B'``) against the new
invariant.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

from devsteward.core import attribution
from devsteward.core.executor import RunOutcome

from test_commit_integrity import _executor, _git, _init_git, _scaffold

REPO = Path(__file__).resolve().parent.parent

#: A model identifier in any of its written forms — the marketing name (``Opus``) or the API
#: id (``claude-opus-5``). Deliberately family-level: the defect was never "the version
#: drifted" but "a model was named at all in a place with no way to maintain it".
MODEL_TOKEN = re.compile(r"\b(opus|sonnet|haiku|fable)\b|claude-[a-z]+-[0-9]", re.IGNORECASE)

#: The one file allowed to name a model: the stamped project config. That *is* the answer —
#: the identifier lives in the consumer's editable file. Asserted by exact path so widening
#: the exemption requires editing a test.
CONFIG_TEMPLATE = "devsteward/templates/.devsteward/config.yaml.tmpl"

#: Files that legitimately *quote* the retired trailer as prose: the REQs and plans that
#: record the defect, the index rows naming their titles, and these tests. Excluding them is
#: not weakening the scan — a bug report has to be able to state the bug. Explicit paths, never
#: a wildcard over ``docs/``: a wildcard would let live doctrine drift back unnoticed, which is
#: the one thing this scan exists to prevent.
QUOTES_THE_DEFECT = {
    "docs/requirements/REQ-019.md",
    "docs/requirements/REQ-020.md",
    "docs/requirements/REQ-024.md",
    "docs/requirements/REQ-062.md",
    "docs/requirements/REQ-090.md",
    "docs/requirements/REQ-091.md",
    "docs/requirements/REQUIREMENTS_INDEX.md",
    "docs/plans/0001-baseline-and-steward-plan.md",
    "docs/plans/0005-memzy-onboarding.md",
    "docs/plans/0006-branch-lifecycle-automation.md",
    "docs/plans/0038-onboard-skill.md",
    "docs/plans/REQ-090-model-ids-out-of-code.md",
    "docs/plans/REQ-091-spawn-model-and-attribution.md",
    "tests/test_req091_assisted_by.py",
    "tests/test_req091_model_surfacing.py",
}

#: Machinery directories that are never part of what this repository *says* — tool caches,
#: virtualenvs (whose site-packages legitimately name models), git's own store, build output.
PRUNE_DIRS = {
    ".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", "node_modules", "build", "dist",
}


def _scannable_files() -> list[str]:
    """Repo-relative paths of every source file, by walking the tree (see module docstring
    for why this is a walk and not ``git ls-files``)."""
    found = []
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = sorted(d for d in dirnames if d not in PRUNE_DIRS)
        for name in sorted(filenames):
            found.append(str((Path(dirpath) / name).relative_to(REPO)))
    return found


def _text_lines(rel: str) -> list[str]:
    """Lines of a scanned path, or none for anything unreadable as text.

    The walk also reaches symlinks (``.claude/skills`` is one) and binary assets; a symlink's
    target is scanned in its own right, so skipping it here loses no coverage."""
    path = REPO / rel
    if not path.is_file() or path.is_symlink():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []


def _trailers(root: Path, key: str) -> list[str]:
    """Every ``key:`` trailer line across the repo's whole history at ``root``."""
    bodies = _git(root, "log", "--format=%B%x00").split("\0")
    return [
        line.strip()
        for body in bodies
        for line in body.splitlines()
        if line.strip().startswith(f"{key}:")
    ]


def _land_one_req(tmp_path: Path, **executor_kwargs):
    """Scaffold a one-REQ project, drive a real headless land, return the executor."""
    _scaffold(tmp_path, test="python -m pytest tests/test_ok.py")
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    _init_git(tmp_path)
    ex = _executor(tmp_path, env_file=None, **executor_kwargs)
    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE, res.detail
    return ex


# -- AC6: the engine's commits name the model it actually spawned with ---------


def test_engine_commit_discloses_resolved_model(tmp_path):
    """AC6: both engine commit sites — the whole-tree code commit and the trailing ledger
    commit — carry ``Assisted-by: Claude:<model>`` naming the model the executor resolved for
    the session it spawned, with no retired trailer, no address and no angle brackets.

    The model is *not* re-derived here: the assertion reads ``ex._spawn_model``, the value the
    executor recorded when it resolved the spawn, so the test cannot pass by agreeing with a
    duplicate resolution that has drifted from the real one.
    """
    ex = _land_one_req(tmp_path)

    assert ex._spawn_model, "the executor must record the model it spawned with"
    expected = f"{attribution.TRAILER_KEY}: {attribution.AGENT}:{ex._spawn_model}"

    trailers = _trailers(tmp_path, attribution.TRAILER_KEY)
    assert len(trailers) >= 2, f"expected code + ledger commits to be trailed, got {trailers}"
    for line in trailers:
        assert line == expected, f"engine trailer drifted: {line!r}"

    # The retired key is gone from the engine's own history, not merely supplemented.
    assert not _trailers(tmp_path, "Co-Authored-By")
    bodies = _git(tmp_path, "log", "--format=%B")
    assert "@" not in bodies and "<" not in bodies


# -- AC7: attended identity, or an explicit unknown ---------------------------


def test_attended_identity_or_explicit_unknown(monkeypatch):
    """AC7: with ``DEVSTEWARD_ASSISTED_BY`` exported the trailer carries that identity; with
    it unset and nothing spawned, the trailer is an explicit ``Claude:unknown``.

    The unknown case is the load-bearing one (Decision 11). A bare agent name with the
    version silently dropped would rebuild the very failure this REQ replaces, so it is
    asserted *against* directly rather than left implied by the happy path.
    """
    env_key = attribution.IDENTITY_ENV
    bare_agent = f"{attribution.TRAILER_KEY}: {attribution.AGENT}"

    # 1. The engine spawned the session, so it knows — no env var consulted.
    assert attribution.trailer("some-model", env={env_key: "ignored-because-spawned"}) == (
        f"{attribution.TRAILER_KEY}: {attribution.AGENT}:some-model"
    )

    # 2. Nothing spawned (an attended `steward checkpoint`): the session's export answers,
    #    in either the bare-id or the agent-qualified form.
    assert attribution.trailer(None, env={env_key: "some-model"}).endswith(":some-model")
    assert attribution.trailer(None, env={env_key: "Agent:some-model"}) == (
        f"{attribution.TRAILER_KEY}: Agent:some-model"
    )

    # 3. Nothing anywhere: unknown is *said*, never blanked to a bare agent name.
    for env in ({}, {env_key: ""}, {env_key: "   "}):
        line = attribution.trailer(None, env=env)
        assert line == f"{attribution.TRAILER_KEY}: {attribution.AGENT}:{attribution.UNKNOWN}"
        assert line != bare_agent

    # 4. A malformed identity falls back to unknown rather than being scrubbed into something
    #    that looks authoritative — an address must never enter this trailer.
    for hostile in ("Claude <noreply@example.invalid>", "x\nSigned-off-by: someone"):
        assert attribution.trailer(None, env={env_key: hostile}).endswith(attribution.UNKNOWN)

    # 5. A missing identity never *blocks* — sign() always returns a usable message.
    monkeypatch.delenv(env_key, raising=False)
    signed = attribution.sign("REQ-000: subject")
    assert signed.startswith("REQ-000: subject")
    assert attribution.UNKNOWN in signed


# -- AC8: the on/off seam ------------------------------------------------------


def test_attribution_trailer_can_be_disabled(tmp_path):
    """AC8: ``attribution_trailer: false`` in the project config yields commits with no
    attribution trailer of any kind — not an empty one, not an unknown one; absent, the
    default is on.

    Exercised through the real config-loading path (``Config.attribution_trailer``), not by
    patching a module constant, so a project genuinely can comply with a policy that bans AI
    trailers without patching the engine.
    """
    from devsteward.config import Config, load_config

    (tmp_path / ".devsteward").mkdir(parents=True)
    cfg_path = tmp_path / ".devsteward" / "config.yaml"

    cfg_path.write_text("attribution_trailer: false\n", encoding="utf-8")
    assert load_config(tmp_path).attribution_trailer is False
    cfg_path.write_text("profile: req\n", encoding="utf-8")
    assert load_config(tmp_path).attribution_trailer is True
    assert Config(root=tmp_path).attribution_trailer is True

    # And the executor honors it end to end, over a real git land.
    project = tmp_path / "project"
    project.mkdir()
    ex = _land_one_req(project, attribution_trailer=False)
    assert ex._spawn_model, "a disabled trailer must not disable model resolution"
    bodies = _git(project, "log", "--format=%B")
    assert attribution.TRAILER_KEY not in bodies
    assert "Co-Authored-By" not in bodies


# -- AC9: the retired form survives nowhere in live text -----------------------


def test_no_coauthor_trailer_survives_in_live_text():
    """AC9: no tracked file in this repository's live source, templates, skills, handbook or
    doctrine text instructs or emits ``Co-Authored-By:``, and every ``Assisted-by:``
    occurrence carries an ``<agent>:<version>`` value with no address and no angle brackets.

    Strictly stronger than REQ-090's scan, which policed what sat *inside* the retired key.
    The point is the template: fix only the commit path and every newly stamped project is
    still born instructing its sessions to write the wrong trailer.

    ``.devsteward/evidence/`` is excluded because it holds hash-recorded *frozen* validation
    artifacts (``REQ-057/*/CLAUDE.stamped.md`` contains the old trailer by design). Rewriting
    them to satisfy a scan would falsify recorded evidence — those artifacts are true
    statements about what was stamped at capture time.
    """
    retired = "Co-Authored" + "-By:"
    offenders = []
    for rel in _scannable_files():
        if rel.startswith(".devsteward/evidence/") or rel in QUOTES_THE_DEFECT:
            continue
        for lineno, line in enumerate(_text_lines(rel), 1):
            if retired.lower() in line.lower():
                offenders.append(f"{rel}:{lineno}: retired trailer — {line.strip()!r}")
            if f"{attribution.TRAILER_KEY}:" not in line:
                continue
            value = line.split(f"{attribution.TRAILER_KEY}:", 1)[1].strip().strip("`.")
            # An address is what disqualifies a value — that was defect 3 of the retired
            # form. A ``<placeholder>`` in prose is not an address: documentation has to be
            # able to write the shape, and forbidding the brackets outright would only push
            # the docs into vaguer language without making a single commit more honest.
            if "@" in value:
                offenders.append(f"{rel}:{lineno}: carries an address — {value!r}")

    assert not offenders, (
        "attribution is a disclosure trailer with no address; the co-authorship form is "
        "retired:\n" + "\n".join(offenders)
    )


def test_the_scan_would_catch_a_reintroduction():
    """AC9's teeth: the scan's own oracle, proven disconfirmable.

    A scan that passes because it matches nothing is indistinguishable from a scan that
    passes because the tree is clean. Feed the same predicates the shapes this REQ retires and
    require them to object — built by concatenation so this file contains no literal offending
    trailer for the real scan to trip over.
    """
    retired = "Co-Authored" + "-By:"
    assert retired.lower() in ("Co-Authored" + "-By: Claude").lower()
    assert retired.lower() in ("co-authored" + "-by: someone").lower()
    assert retired.lower() not in f"{attribution.TRAILER_KEY}: {attribution.AGENT}:x".lower()

    addressed = f"{attribution.TRAILER_KEY}: {attribution.AGENT} <x@example.invalid>"
    assert "@" in addressed.split(f"{attribution.TRAILER_KEY}:", 1)[1]
    clean = f"{attribution.TRAILER_KEY}: {attribution.AGENT}:{attribution.UNKNOWN}"
    assert "@" not in clean.split(f"{attribution.TRAILER_KEY}:", 1)[1]
    # A documentation placeholder is not an address, and must not read as one.
    placeholder = f"{attribution.TRAILER_KEY}: {attribution.AGENT}:<model-id>"
    assert "@" not in placeholder.split(f"{attribution.TRAILER_KEY}:", 1)[1]


# -- AC10: a freshly stamped project is born correct ---------------------------


def test_stamped_claude_md_mandates_assisted_by(tmp_path):
    """AC10: ``steward new`` stamps a ``CLAUDE.md`` whose house conventions mandate the
    ``Assisted-by:`` form and carry the ``Signed-off-by:`` prohibition, with no instruction to
    write the retired trailer anywhere in it.

    The scan above proves the *template* is right; this proves the stamp actually delivers it,
    which is the only thing a new consumer ever sees.
    """
    target = tmp_path / "fresh"
    proc = subprocess.run(
        [sys.executable, "-m", "devsteward.cli", "new", str(target)],
        capture_output=True, text=True, cwd=str(REPO),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    text = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert f"{attribution.TRAILER_KEY}:" in text
    assert ("Co-Authored" + "-By").lower() not in text.lower()
    assert "Signed-off-by" in text, "the DCO prohibition must ship with the convention"
    assert "@" not in text.split(f"{attribution.TRAILER_KEY}:", 1)[1].splitlines()[0]

    config = (target / ".devsteward" / "config.yaml").read_text(encoding="utf-8")
    assert "attribution_trailer:" in config, "the on/off seam must be visible in the stamp"
