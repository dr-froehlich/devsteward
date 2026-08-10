"""REQ-090 — no model identifier lives in engine code.

Reported from FlowSteward: every ``steward checkpoint`` landing wrote a hardcoded
``Co-Authored-By: Claude Opus 4.8`` trailer naming a model two generations dead, while
hand-made commits in the same sessions recorded the live model correctly. Diagnosis inside
the boundary found the trailer constant was the *smaller* half — ``devsteward/config.py``
also pinned the **spawn** model (a flat fallback plus built-in per-step-kind values), and
``Config.step_claude()`` always resolved to a concrete string, so consumers' headless
sessions really were being driven by an obsolete model.

The rule, and the reason these are scans rather than call-site assertions: **a model
identifier in a Python module ties DevSteward's releases to Anthropic's**. Models live in
`.devsteward/config.yaml`, visible and consumer-owned — both the global default and the
per-step overrides, so a project can no longer override an invisible default it cannot set.

A test pinned to ``executor.py``'s constant would pass while a new commit path, the stamped
template or the handbook reintroduced the same defect somewhere else, so AC1/AC3 scan the
tracked tree instead. AC2 asserts the observable the bug report actually measured (a real
commit body), and AC4 proves the config value reaches the spawned session.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from devsteward.config import Config
from devsteward.core.executor import RunOutcome
from devsteward.core.git import GitCli

from conftest import FakeRunner, ok_result
from test_commit_integrity import _executor, _git, _init_git, _scaffold

REPO = Path(__file__).resolve().parent.parent

#: A model identifier in any of its written forms — the marketing name (``Opus``) or the API
#: id (``claude-opus-5``). Deliberately family-level: the defect was not "the version drifted"
#: but "a model was named at all in a place with no way to maintain it".
MODEL_TOKEN = re.compile(r"\b(opus|sonnet|haiku|fable)\b|claude-[a-z]+-[0-9]", re.IGNORECASE)

#: The one file allowed to name a model: the stamped project config. That *is* the answer to
#: this REQ — the identifier lives in the consumer's editable file. Asserted by exact path so
#: widening the exemption requires editing this test.
CONFIG_TEMPLATE = "devsteward/templates/.devsteward/config.yaml.tmpl"

#: Files that legitimately *quote* the defect as prose: the REQ that fixes it, its plan, and
#: this test. Excluding them is not weakening the scan — a bug report has to be able to state
#: the bug.
QUOTES_THE_DEFECT = {
    "docs/requirements/REQ-090.md",
    "docs/plans/REQ-090-model-ids-out-of-code.md",
    "tests/test_coauthor_trailer.py",
}


def _tracked_files() -> list[str]:
    """Repo-relative paths of every tracked file.

    ``git ls-files`` rather than a walk: it excludes ``.git/`` and build detritus for free,
    and it is exactly the set "what this repository ships".
    """
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout
    return out.split()


def _text_lines(rel: str) -> list[str]:
    """Lines of a tracked path, or none for anything unreadable as text.

    ``git ls-files`` also lists symlinks (``.claude/skills`` is one) and binary assets; their
    targets are tracked in their own right, so skipping them here loses no coverage.
    """
    path = REPO / rel
    if not path.is_file() or path.is_symlink():
        return []
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (UnicodeDecodeError, OSError):
        return []


# -- AC1: no trailer anywhere names a model or carries an address --------------


def test_no_model_or_email_in_any_coauthor_trailer():
    """AC1: every ``Co-Authored-By:`` line in the tracked tree is either the engine's plain
    ``Co-Authored-By: Claude`` or the documented ``<modelname>`` placeholder — no model
    identifier, no email address.

    ``.devsteward/evidence/`` is excluded because it holds hash-recorded *frozen* validation
    artifacts (``REQ-057/*/CLAUDE.stamped.md`` contains the old trailer by design). Rewriting
    them to satisfy a scan would falsify recorded evidence — the artifacts are true
    statements about what was stamped at capture time.
    """
    offenders = []
    for rel in _tracked_files():
        if rel.startswith(".devsteward/evidence/") or rel in QUOTES_THE_DEFECT:
            continue
        for lineno, line in enumerate(_text_lines(rel), 1):
            if "Co-Authored-By:" not in line:
                continue
            value = line.split("Co-Authored-By:", 1)[1].strip().strip("`")
            if MODEL_TOKEN.search(value):
                offenders.append(f"{rel}:{lineno}: names a model — {value!r}")
            if "@" in value:
                offenders.append(f"{rel}:{lineno}: carries an address — {value!r}")

    assert not offenders, "co-author trailers must name no model and carry no address:\n" + "\n".join(
        offenders
    )


def test_the_scan_would_catch_a_reintroduction(tmp_path, monkeypatch):
    """AC1's teeth: the scan's own oracle, proven disconfirmable.

    A scan that passes because it matches nothing is indistinguishable from a scan that
    passes because the tree is clean. Feed the same predicate a trailer of the shape this REQ
    deleted and require it to object — built by concatenation so this file contains no
    literal offending trailer for the real scan to trip over.
    """
    bad_model = "Co-Authored-By: Claude " + "Opus 4.8"
    bad_email = "Co-Authored-By: Claude <noreply@" + "anthropic.com>"
    good = "Co-Authored-By: Claude"
    placeholder = "Co-Authored-By: <modelname>"

    assert MODEL_TOKEN.search(bad_model.split(":", 1)[1])
    assert "@" in bad_email.split(":", 1)[1]
    assert not MODEL_TOKEN.search(good.split(":", 1)[1])
    assert "@" not in good.split(":", 1)[1]
    assert not MODEL_TOKEN.search(placeholder.split(":", 1)[1])


# -- AC2: the observable the bug report measured -------------------------------


def test_engine_commits_carry_generic_trailer(tmp_path):
    """AC2: driving a real land against a temporary git repo, the code commit's message body
    carries the literal ``Co-Authored-By: Claude`` and names no model — and so does the
    trailing ledger commit.

    This is the assertion the reporter could make from outside the boundary
    (``git log -1 --format='%B' | grep Co-Authored-By``), so it is the one that proves the
    fix in the terms the defect was found in.
    """
    _scaffold(tmp_path, test="python -m pytest tests/test_ok.py")
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    _init_git(tmp_path)

    ex = _executor(tmp_path, env_file=None)
    res = ex.advance_once()
    assert res.outcome is RunOutcome.DONE, res.detail

    bodies = _git(tmp_path, "log", "--format=%B%x00").split("\0")
    trailers = [
        line.strip()
        for body in bodies
        for line in body.splitlines()
        if "Co-Authored-By:" in line
    ]
    # Both engine commits: the whole-tree code commit and the trailing ledger commit.
    assert len(trailers) >= 2, f"expected code + ledger commits to be trailed, got {trailers}"
    for trailer in trailers:
        assert trailer == "Co-Authored-By: Claude", f"engine trailer drifted: {trailer!r}"
        assert not MODEL_TOKEN.search(trailer.split(":", 1)[1])
        assert "@" not in trailer


# -- AC3: engine source names no model -----------------------------------------


def test_engine_source_names_no_model():
    """AC3: nothing under ``devsteward/`` names a Claude model except the stamped config
    template — so a new Anthropic release never obliges an engine source change.

    Covers what the intake diagnosis missed as much as what it found: the deleted
    ``DEFAULT_MODEL``, the ``Config.model`` fallback, the built-in ``STEP_CLAUDE_DEFAULTS``
    per-step pins, the ``--model`` help text, the stamped ``CLAUDE.md`` convention and the
    handbook's "defaults Opus-high" prose were all separate instances of one mistake.
    """
    offenders = []
    for rel in _tracked_files():
        if not rel.startswith("devsteward/") or rel == CONFIG_TEMPLATE:
            continue
        for lineno, line in enumerate(_text_lines(rel), 1):
            match = MODEL_TOKEN.search(line)
            if match:
                offenders.append(f"{rel}:{lineno}: {match.group(0)!r} in {line.strip()!r}")

    assert not offenders, (
        "model identifiers belong in .devsteward/config.yaml, not in engine code "
        f"(only {CONFIG_TEMPLATE} may name one):\n" + "\n".join(offenders)
    )


def test_config_template_is_where_the_model_lives():
    """AC3's complement — the exemption is load-bearing, not a hole.

    The template must actually *name* a model: shipping the key empty would put the project
    back where it started (a global default nobody can see) while still passing the scan
    above. Both levels are asserted, because the reported asymmetry was that a project could
    override the per-step model but not set the global one.
    """
    text = (REPO / CONFIG_TEMPLATE).read_text(encoding="utf-8")
    active = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    body = "\n".join(active)

    assert re.search(r"^\s{2}model:\s*\S+", body, re.MULTILINE), (
        "the stamped config must ship a visible global `claude.model` — an invisible "
        "default is the defect REQ-090 fixes"
    )
    assert re.search(r"^\s{2}steps:", body, re.MULTILINE), (
        "the stamped config must ship the per-step overrides too, so both levels are "
        "readable in the one file the consumer owns"
    )
    assert MODEL_TOKEN.search(body), "the shipped keys must name real models, not placeholders"


# -- AC4: the configured model reaches the spawned session ---------------------


def test_stamped_config_pins_model_and_reaches_spawn(tmp_path):
    """AC4: a configured ``claude.model`` reaches the spawned session as ``--model``, a
    ``claude.steps.<kind>`` override wins for its own kind, and a project that configures no
    model spawns with **no** ``--model`` flag at all.

    The last case is the behaviour change this REQ makes honest: it used to mean "silently
    get whatever config.py hardcoded", and now means "use claude's own default".
    """
    cfg = Config(
        root=tmp_path,
        claude={"model": "test-model-flat", "effort": "high",
                "steps": {"repair": {"model": "test-model-repair"}}},
    )
    assert cfg.model == "test-model-flat"
    assert cfg.step_claude("develop") == ("test-model-flat", "high")
    assert cfg.step_claude("repair")[0] == "test-model-repair"
    # A kind the config never names inherits the flat default rather than a built-in.
    assert cfg.step_claude("validate")[0] == "test-model-flat"

    # Unset: no model anywhere, so no flag — never a hidden fallback.
    bare = Config(root=tmp_path, claude={})
    assert bare.model is None
    assert bare.step_claude("develop")[0] is None
    assert bare.step_claude("repair")[0] is None

    # End-to-end: the resolved value is what run_claude is actually called with.
    from devsteward.core.claude import run_claude

    captured: dict = {}

    class _FakePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            self.stdout = iter(['{"type":"result","subtype":"success","result":"x"}\n'])
            self._done = False

        def wait(self, timeout=None):
            self._done = True
            return 0

        def poll(self):
            return 0 if self._done else None

        def kill(self):
            self._done = True

        def terminate(self):
            self._done = True

    from devsteward.core import claude as claude_mod

    monkey = pytest.MonkeyPatch()
    try:
        monkey.setattr(claude_mod.subprocess, "Popen", _FakePopen)
        run_claude("/advance REQ-001 develop", model=cfg.step_claude("develop")[0])
        assert "--model" in captured["argv"]
        assert captured["argv"][captured["argv"].index("--model") + 1] == "test-model-flat"

        run_claude("/advance REQ-001 develop", model=bare.step_claude("develop")[0])
        assert "--model" not in captured["argv"], (
            "an unconfigured project must spawn with no --model flag, not a hidden default"
        )
    finally:
        monkey.undo()


def test_stamped_project_gets_a_visible_model(tmp_path):
    """AC4, through the stamp: a project created by ``steward new`` has an active (not
    commented) ``claude.model`` that ``Config`` reads back — the round trip from template to
    resolved spawn value, which is what a consumer actually experiences.
    """
    from click.testing import CliRunner

    from devsteward.cli import main

    target = tmp_path / "proj"
    result = CliRunner().invoke(main, ["new", str(target)])
    assert result.exit_code == 0, result.output

    from devsteward.config import load_config

    cfg = load_config(target)
    assert cfg.model, "a stamped project must have a visible model, not an invisible default"
    assert cfg.step_claude("develop")[0] == cfg.model
    # And it is genuinely active in the file, not merely a parsed default.
    raw = (target / ".devsteward" / "config.yaml").read_text(encoding="utf-8")
    assert re.search(r"^\s{2}model:\s*\S+", raw, re.MULTILINE)
