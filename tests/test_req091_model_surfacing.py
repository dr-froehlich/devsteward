"""REQ-091 — a spawn never hides the model it runs on.

REQ-090 moved every model identifier out of engine Python and into the stamped config, and
made "unset means claude's own default" a legitimate contract. It became a trap only because
it was **silent**: deleting the built-in per-step tier deleted twelve stamped projects'
repair/validate policy with it, and every develop, repair and validate session in all twelve
spawned on a model nobody chose for two days before a ``steward validate`` in one repo
happened to be noticed running the top model. The reporter could see *that* it ran and could
not see *why*; that asymmetry is the defect these tests close.

The cure is surfacing plus one refusal, not new config machinery:

* every spawn announces the ``(model, effort)`` it resolved and records it as a ledger event;
* an **unattended** spawn with no configured model refuses, naming the key and the file —
  the expensive failure is ``steward run`` marching a queue for hours unwatched;
* an **attended** spawn warns and proceeds, preserving REQ-090's contract where a human is
  present to judge in the moment.

AC4 re-asserts REQ-090's surviving invariant (no model identifier in engine Python) here,
because REQ-091's diagnostic and error paths are new prose — exactly where a "helpful"
example model string creeps back in. It imports the scan machinery from
:mod:`tests.test_req091_assisted_by` rather than duplicating it.
"""

from __future__ import annotations

import re
from pathlib import Path

from devsteward.config import Config
from devsteward.core.executor import (
    MODEL_CONFIG_FILE,
    MODEL_CONFIG_KEY,
    RunOutcome,
    unconfigured_model_notice,
)

from test_commit_integrity import _executor, _init_git, _scaffold
from test_req091_assisted_by import (
    CONFIG_TEMPLATE,
    MODEL_TOKEN,
    REPO,
    _scannable_files,
    _text_lines,
)


def _project(tmp_path: Path):
    _scaffold(tmp_path, test="python -m pytest tests/test_ok.py")
    (tmp_path / "tests").mkdir(exist_ok=True)
    (tmp_path / "tests" / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )
    _init_git(tmp_path)


def _spawn_events(ex) -> list[dict]:
    return [e for e in ex.ledger.events() if e.get("event") == "spawn_model"]


# -- AC1: the resolved model is surfaced --------------------------------------


def test_spawn_surfaces_resolved_model(tmp_path):
    """AC1: resolving a spawn announces the model and records a ``spawn_model`` ledger event;
    when nothing is configured it says *that*, naming ``claude.model`` and the config file
    rather than printing a blank or a plausible-looking default.

    Driven through the executor's own resolution path for all three kinds, so the test cannot
    pass against a re-implementation that has drifted from what actually spawns.
    """
    _project(tmp_path)
    said: list[str] = []
    ex = _executor(tmp_path, env_file=None, announce=said.append)
    ex.step_claude = {
        "develop": ("model-dev", "high"),
        "repair": ("model-rep", None),
        "validate": ("model-val", None),
    }

    for kind, expected in (
        ("develop", "model-dev"), ("repair", "model-rep"), ("validate", "model-val")
    ):
        model, _effort, refusal = ex._resolve_spawn(kind, unattended=True)
        assert (model, refusal) == (expected, None)

    assert [e["model"] for e in _spawn_events(ex)] == ["model-dev", "model-rep", "model-val"]
    for kind, expected in (
        ("develop", "model-dev"), ("repair", "model-rep"), ("validate", "model-val")
    ):
        assert any(kind in line and expected in line for line in said), said

    # Unconfigured: the fact is stated, and it points at the answer.
    said.clear()
    ex.step_claude = {}
    ex.model = None
    model, _effort, _refusal = ex._resolve_spawn("develop", unattended=True)
    assert model is None
    assert _spawn_events(ex)[-1]["model"] is None
    surfaced = " ".join(said)
    assert MODEL_CONFIG_KEY in surfaced and MODEL_CONFIG_FILE in surfaced
    assert not MODEL_TOKEN.search(surfaced), (
        "the diagnostic names the key, never a model value (REQ-090 holds in error paths)"
    )


# -- AC2: an unattended spawn refuses -----------------------------------------


def test_unattended_spawn_refuses_unconfigured_model(tmp_path):
    """AC2: an unattended run with no configured model launches no claude process, and the
    surfaced message names the step kind, the config key and the config file — with no model
    identifier anywhere in it.

    The oracle is the runner: it is asserted **not called**, so a refusal that still spawned
    (and merely complained) cannot pass.
    """
    _project(tmp_path)
    spawned: list[str] = []

    def refuse_to_be_called(command, **kwargs):
        spawned.append(command)
        raise AssertionError("a session was spawned on an unconfigured model")

    ex = _executor(tmp_path, env_file=None)
    ex.model = None
    ex.step_claude = {}
    ex.runner = refuse_to_be_called

    res = ex.advance_once(unattended=True)
    assert res.outcome is RunOutcome.REFUSED, res.detail
    assert spawned == []
    assert "develop" in res.detail
    assert MODEL_CONFIG_KEY in res.detail and MODEL_CONFIG_FILE in res.detail
    assert not MODEL_TOKEN.search(res.detail)

    # The step stays runnable — this is a config answer away, not a failure.
    assert any(e.get("event") == "spawn_refused" for e in ex.ledger.events())
    assert unconfigured_model_notice("validate").count("validate") >= 1


# -- AC3: an attended spawn warns and proceeds --------------------------------


def test_attended_spawn_warns_and_proceeds(tmp_path):
    """AC3: attended, an unconfigured model warns and still spawns — with **no** ``--model``
    flag, preserving REQ-090's "unset means claude's own default" contract for the
    interactive case; and an explicit ``--model`` override counts as configured in both
    lanes, drawing no warning.

    Blocking an attended operator would be paternalism: they see the warning and can decide
    in the moment. It is the unwatched queue that must be stopped.
    """
    _project(tmp_path)
    said: list[str] = []
    ex = _executor(tmp_path, env_file=None, announce=said.append)
    ex.model = None
    ex.step_claude = {}

    model, _effort, refusal = ex._resolve_spawn("develop", unattended=False)
    assert (model, refusal) == (None, None), "attended must proceed, not refuse"
    assert any("warning" in line.lower() for line in said), said
    assert ex._spawn_model is None, "nothing chosen means nothing claimed in the trailer"

    # A CLI --model override arrives already folded into step_claude by build_executor, so it
    # is simply *configured*: no warning, and it is what the trailer will name.
    said.clear()
    ex.step_claude = {"develop": ("model-from-flag", "high")}
    for unattended in (True, False):
        model, _effort, refusal = ex._resolve_spawn("develop", unattended=unattended)
        assert (model, refusal) == ("model-from-flag", None)
    assert not any("warning" in line.lower() for line in said), said
    assert ex._spawn_model == "model-from-flag"


# -- AC4: no model identifier in engine code (REQ-090's surviving invariant) ---


def test_no_model_identifier_in_engine_code():
    """AC4: nothing under ``devsteward/`` names a Claude model except the stamped config
    template, and that template ships both levels filled in — so a new Anthropic release never
    obliges an engine source change, and no project inherits a default it cannot see.

    Re-asserted from REQ-090 because this REQ adds new diagnostic prose to the engine, which
    is precisely the kind of place an illustrative model id gets written by reflex.
    """
    offenders = []
    for rel in _scannable_files():
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

    text = (REPO / CONFIG_TEMPLATE).read_text(encoding="utf-8")
    active = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    body = "\n".join(active)
    assert re.search(r"^\s{2}model:\s*\S+", body, re.MULTILINE), (
        "the stamped config must ship a visible global `claude.model` — an invisible default "
        "is the defect REQ-090 fixed and REQ-091 pays the migration for"
    )
    assert re.search(r"^\s{2}steps:", body, re.MULTILINE), (
        "the stamped config must ship the per-step overrides too — deleting the built-in tier "
        "without shipping a replacement is what left twelve consumers on an unchosen model"
    )
    assert MODEL_TOKEN.search(body), "the shipped keys must name real models, not placeholders"

    # And this repo's own config practices what the template preaches.
    own = Config(root=REPO, raw={}, claude=(_own_claude_block()))
    assert own.model, "devsteward's own config must pin a model"
    assert own.step_claude("repair")[0] and own.step_claude("validate")[0]


def _own_claude_block() -> dict:
    from devsteward.config import load_config

    return load_config(REPO).claude
