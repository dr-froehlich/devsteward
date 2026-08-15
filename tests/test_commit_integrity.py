"""REQ-063 / REQ-072 — commit integrity: non-destructive, and run in the declared environment.

The REQ-050 gate proved a develop commit reproduces its own green, but did it *after*
committing and ``reset --hard``'d the work away on a gap — discarding a green, paid-for
session (FlowSteward REQ-043 postmortem). REQ-063 re-architects the land path: the check runs
against the **staged tree before the commit**, so a gap is handled non-destructively — the
pure code is committed and its SHA surfaced, the step is left repeatable, nothing is reset.
And an **environment skip** (a test that passed verify but only skips from the bare extract,
its DB/secret absent) is no longer a capture gap.

Real-git teeth (the plan-0021 lesson): a throwaway ``git init`` repo on ``dev``, only
``claude`` faked (``FakeRunner``). The develop "work" is written **uncommitted** into the tree
(the fake runner makes no edits), so the engine commits it for real — exactly the live shape.

* **AC1** (``test_capture_gap_preserves_work_and_surfaces_sha``) — a real source-capture gap
  withholds certification but **preserves** the work commit and surfaces its SHA.
* **AC2** (``test_environment_skip_is_not_a_capture_gap``) — the all-skip shape certifies.
* **AC3** (``test_self_sufficient_green_certifies``) — a self-sufficient green lands ``DONE``,
  the flip riding the one code commit (same-commit discipline); no false positive.
* **AC4** (``test_withhold_recovery_is_honest_and_names_sha``) — the withhold message names the
  preserved SHA and frames the cause as a source file, never "commit the secret".
* Two controls: the validate land stays exempt; the develop land of the *self-sufficient* case.

REQ-072 extends the gate to run in the operator's **declared environment**: the env-file
(``verify.env_file``, default ``.env``) is carried into the tree extract when present — so a
green that legitimately *fails* (not skips) without it, the FlowSteward Postgres-on-extract-
SQLite shape, reproduces and certifies. Honor-when-present (the hermetic path is unchanged),
the withheld diagnosis is environment-honest, and the carried secrets never leak.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import tempfile

from devsteward.build import build_executor
from devsteward.config import Config
from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.git import GitCli
from devsteward.core.ledger import Ledger
from devsteward.core.model import Step, StepStatus
from devsteward.profiles.req import ReqStepSource
from devsteward.profiles.req.checkpoint import PlanArtifactGate, ReqDoneFlipper
from devsteward.profiles.req.verify import ReqVerifier

from conftest import AuthoringRunner, ok_result


# -- scaffold ------------------------------------------------------------------


def _write_req(req_dir: Path, rid: str, test: str, *, status="open"):
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / f"{rid}.md").write_text(
        f"---\n"
        f"id: {rid}\n"
        f'title: "{rid} title"\n'
        f"status: {status}\n"
        f"kind: feature\n"
        f"added: 2026-06-19\n"
        f"completed: null\n"
        f"verified_by: null\n"
        f"depends_on: []\n"
        f"concept_refs: []\n"
        f"scenario_refs: []\n"
        f"supersedes: null\n"
        f"tags: []\n"
        f"---\n\n"
        f"## Context\n\n{rid} context.\n\n"
        f"## Requirement\n\nDo the thing.\n\n"
        "```yaml acceptance\n"
        f"- id: AC1\n"
        f"  text: AC1 holds.\n"
        f'  test: "{test}"\n'
        f"  check: regression\n"
        f"  status: pending\n"
        "```\n\n"
        f"## Notes\n\nNone.\n",
        encoding="utf-8",
    )


def _index(req_dir: Path):
    (req_dir / "REQUIREMENTS_INDEX.md").write_text(
        "# Requirements Index\n\n"
        "| ID | Title | Status | File | Depends on |\n"
        "|----|-------|--------|------|------------|\n"
        "| REQ-001 | REQ-001 title | OPEN | [REQ-001](REQ-001.md) | – |\n",
        encoding="utf-8",
    )


def _scaffold(root: Path, *, test: str):
    req_dir = root / "docs" / "requirements"
    _write_req(req_dir, "REQ-001", test)
    _index(req_dir)
    plans = root / "docs" / "plans"
    plans.mkdir(parents=True, exist_ok=True)
    (plans / "0001-plan.md").write_text("# Plan 0001\n\nCovers REQ-001.\n", encoding="utf-8")
    (root / ".devsteward").mkdir(parents=True, exist_ok=True)
    (root / ".devsteward" / "config.yaml").write_text(
        "accounts:\n  provider: single\n", encoding="utf-8"
    )
    Ledger.init(root, profile="req")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _init_git(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "integrity@devsteward.test")
    _git(root, "config", "user.name", "DevSteward Integrity Test")
    _git(root, "checkout", "-q", "-b", "dev")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "scaffold")


def _head(root: Path) -> str:
    return _git(root, "rev-parse", "HEAD").strip()


def _porcelain(root: Path) -> str:
    return _git(root, "status", "--porcelain").strip()


def _log_shas(root: Path) -> list[str]:
    return _git(root, "log", "--format=%H").split()


def _executor(
    root: Path,
    *,
    env_file: str | None = ".env",
    writes: dict[str, str] | None = None,
    **overrides,
) -> Executor:
    """The shared real-git executor. ``**overrides`` forwards straight to :class:`Executor`
    so a caller can vary one seam (REQ-091's ``announce`` / ``attribution_trailer``) without
    another copy of this construction drifting away from it."""
    req_dir = root / "docs" / "requirements"
    return Executor(
        # REQ-091: a spawn names its model; an unconfigured headless spawn refuses.
        model="test-spawn-model",
        root=root,
        source=ReqStepSource(req_dir),
        verifier=ReqVerifier(cwd=str(root), full_suite=None),
        accounts=SingleAccountProvider(),
        # The session authors its work *during* the run; the whole-tree commit (REQ-079)
        # stages it — the faithful shape of a real develop session.
        runner=AuthoringRunner(writes),
        on_verified=ReqDoneFlipper(req_dir, req_dir / "REQUIREMENTS_INDEX.md"),
        land_gate=PlanArtifactGate(root / "docs" / "plans"),
        production_branch="main",
        integration_branch="dev",
        git=GitCli(root),
        verify_env_file=env_file,
        **overrides,
    )


# A named test that reads a sibling file — green only if that file is present in the cwd.
_DEP_TEST = (
    "from pathlib import Path\n"
    "def test_needs_secret():\n"
    "    assert Path('secret.txt').read_text().strip() == 'load-bearing'\n"
)

# A named test that reads a *tracked* (committed) sibling file — captured by the commit.
_CAPTURED_TEST = (
    "from pathlib import Path\n"
    "def test_reads_committed_data():\n"
    "    assert Path('data.txt').read_text().strip() == 'captured'\n"
)

# An environment-bound test as the real ones are shaped: it skips when a runtime artifact is
# absent. With the artifact present (the session's env) it passes; from a bare extract the
# (gitignored) artifact is never there, so it skips — an environment absence, not a source gap.
_LIVE_LAB_TEST = (
    "from pathlib import Path\n"
    "import pytest\n"
    "def test_over_live_lab_corpus():\n"
    "    if not Path('lab_present.flag').exists():\n"
    "        pytest.skip('live lab absent')\n"
    "    assert True\n"
)


# -- AC1: a capture gap preserves the work and surfaces the SHA ----------------


def test_capture_gap_preserves_work_and_surfaces_sha(tmp_path):
    """AC1: the develop gate passes (the gitignored ``secret.txt`` is in the tree), but the
    recorded commit can't carry it, so the staged-tree check sees the named test go red. The
    land **withholds certification without destroying the work**: the pure code is committed
    (its SHA surfaced and reachable on ``dev``), the REQ stays ``open``, the step is left
    ``FAILED`` (repeatable), and nothing is ``reset --hard``'d."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    (tmp_path / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    _init_git(tmp_path)  # commits the scaffold + .gitignore; the session authors the work

    # The develop session's work, authored during the run (the engine commits it). The
    # load-bearing file exists so the gate is green, yet is gitignored so the commit drops it.
    before_head = _head(tmp_path)
    ex = _executor(tmp_path, writes={
        "tests/test_dep.py": _DEP_TEST,
        "secret.txt": "load-bearing\n",
    })
    res = ex.advance_once()

    # Withheld, not destroyed: a non-stopping VERIFY_FAILED naming a real, reachable work commit.
    assert res.outcome is RunOutcome.VERIFY_FAILED
    assert res.commit and res.commit != before_head
    assert res.commit in _log_shas(tmp_path)  # on the dev history — preserved, not dangling
    assert "test_dep.py" in _git(tmp_path, "show", "--stat", res.commit)
    assert before_head in _log_shas(tmp_path)  # history extended, not rewritten

    # Nothing certified: the REQ is still open, no checkpoint event, a capture_gap event, and
    # the tree is clean at rest (the ledger close was committed).
    assert "status: open" in (tmp_path / "docs" / "requirements" / "REQ-001.md").read_text()
    assert _porcelain(tmp_path) == ""
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.FAILED
    assert not any(e["event"] == "checkpoint" for e in led.events())
    assert any(e["event"] == "capture_gap" for e in led.events())


# -- AC2: an environment skip is not a capture gap ----------------------------


def test_environment_skip_is_not_a_capture_gap(tmp_path):
    """AC2: the named test passes in verify (the gitignored ``lab_present.flag`` is in the
    tree) and only **skips** from the bare extract (the flag, like a DB/secret, is never in the
    commit). That is environment absence, not a source-capture gap, so the develop land
    certifies ``DONE`` — the FlowSteward REQ-043 all-skip shape, no longer discarded."""
    _scaffold(tmp_path, test="python -m pytest tests/test_lab.py")
    (tmp_path / ".gitignore").write_text("lab_present.flag\n", encoding="utf-8")
    _init_git(tmp_path)

    ex = _executor(tmp_path, writes={
        "tests/test_lab.py": _LIVE_LAB_TEST,
        "lab_present.flag": "up\n",  # gitignored env
    })
    res = ex.advance_once()

    assert res.outcome is RunOutcome.DONE
    assert _porcelain(tmp_path) == ""
    assert "status: done" in (tmp_path / "docs" / "requirements" / "REQ-001.md").read_text()
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.DONE
    assert any(e["event"] == "checkpoint" for e in led.events())


# -- AC3: a self-sufficient green certifies (no false positive) ----------------


def test_self_sufficient_green_certifies(tmp_path):
    """AC3: a green depending only on *committed* source (``data.txt`` is tracked) reproduces
    from the extract and lands ``DONE`` — the re-architecture raises no false positive — with
    the ``done`` flip + index sync riding the one code commit (same-commit discipline)."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    _init_git(tmp_path)

    ex = _executor(tmp_path, writes={
        "tests/test_dep.py": _CAPTURED_TEST,
        "data.txt": "captured\n",  # tracked, not ignored
    })
    res = ex.advance_once()

    assert res.outcome is RunOutcome.DONE
    assert _porcelain(tmp_path) == ""
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.DONE
    assert any(e["event"] == "checkpoint" for e in led.events())

    # Same-commit discipline: the one code commit carries the work AND the REQ flip + index.
    shown = _git(tmp_path, "show", "--stat", res.commit)
    assert "data.txt" in shown
    assert "REQ-001.md" in shown
    assert "REQUIREMENTS_INDEX.md" in shown
    assert "status: done" in (tmp_path / "docs" / "requirements" / "REQ-001.md").read_text()


# -- AC4: the withhold message is honest and names the SHA ---------------------


def test_withhold_recovery_is_honest_and_names_sha(tmp_path):
    """AC4: on a real source-capture gap the surfaced detail names the **preserved** work
    commit and frames the cause as an uncaptured *source/test* file — explicitly *never* the
    postmortem's wrong "commit them / fix .gitignore" advice applied to a secret."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    (tmp_path / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    _init_git(tmp_path)

    ex = _executor(tmp_path, writes={
        "tests/test_dep.py": _DEP_TEST,
        "secret.txt": "load-bearing\n",
    })
    res = ex.advance_once()

    assert res.outcome is RunOutcome.VERIFY_FAILED
    msg = res.detail
    assert "does not reproduce its green" in msg
    assert res.commit and res.commit in msg          # names the preserved SHA
    assert "source/test file" in msg                 # frames it as a source file...
    assert "never a secret" in msg                    # ...not "commit the secret"


# -- control: the validate land stays exempt ----------------------------------


def _validate_step(verify: str) -> Step:
    return Step(
        id="REQ-001:validate",
        command="/system-test REQ-001",
        verify=(verify,),
        title="REQ-001 — validate",
        req="REQ-001",
        phase="validate",
    )


def test_validate_land_certifies_despite_live_lab_skip(tmp_path):
    """Control: the commit-integrity check is a develop-land invariant and must not fire on the
    validate land. A validate step's ``verify`` is the ``artifact`` AC test, whose green was
    established against the live lab and skips from a bare extract by design — so the validate
    phase is exempt and certifies ``DONE`` (REQ-050 × REQ-030, preserved by REQ-063)."""
    _scaffold(tmp_path, test="python -m pytest tests/test_lab.py")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_lab.py").write_text(_LIVE_LAB_TEST, encoding="utf-8")
    (tmp_path / ".gitignore").write_text("lab_present.flag\n", encoding="utf-8")
    _init_git(tmp_path)  # commits the test — but never the lab flag (ignored)
    (tmp_path / "lab_present.flag").write_text("up\n", encoding="utf-8")

    ex = _executor(tmp_path)
    res = ex.mechanical_land(_validate_step("python -m pytest tests/test_lab.py"))

    assert res.outcome is RunOutcome.DONE
    assert _porcelain(tmp_path) == ""
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:validate") is StepStatus.DONE
    assert any(e["event"] == "checkpoint" for e in led.events())


# -- REQ-072: the capture gate runs in the operator's declared environment ------


def _env_gated_test(env_name: str = ".env") -> str:
    """A named test whose oracle reads a value the declared (gitignored) env-file carries,
    and **fails** (not skips) when it is absent — the FlowSteward Postgres shape reduced to a
    coupled fixture: without the env-file the bootstrap falls back to the hermetic default,
    which is the wrong engine."""
    return (
        "from pathlib import Path\n"
        "def test_engine_from_declared_env():\n"
        "    engine = 'sqlite-fallback'\n"
        f"    env = Path({env_name!r})\n"
        "    if env.exists():\n"
        "        for line in env.read_text().splitlines():\n"
        "            key, _, value = line.partition('=')\n"
        "            if key == 'DB_ENGINE':\n"
        "                engine = value.strip()\n"
        "    assert engine == 'postgres'\n"
    )


def _tracked_files(root: Path, commit: str) -> list[str]:
    return _git(root, "ls-tree", "-r", "--name-only", commit).split()


def test_declared_env_file_is_carried_into_extract(tmp_path):
    """AC1 (REQ-072): a develop green that passes ONLY because the gitignored ``.env`` is
    present — its named test *fails* without it, so REQ-063's skip exemption cannot apply —
    reproduces in the capture extract (the engine copied the env-file in) and the land
    certifies ``DONE``, with no shell exports and no ``steward repeat``."""
    _scaffold(tmp_path, test="python -m pytest tests/test_env.py")
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    _init_git(tmp_path)

    ex = _executor(tmp_path, writes={
        "tests/test_env.py": _env_gated_test(),
        ".env": "DB_ENGINE=postgres\n",  # gitignored env
    })
    res = ex.advance_once()

    assert res.outcome is RunOutcome.DONE
    assert _porcelain(tmp_path) == ""
    assert "status: done" in (tmp_path / "docs" / "requirements" / "REQ-001.md").read_text()
    led = Ledger(tmp_path)
    assert led.status_of("REQ-001:develop") is StepStatus.DONE
    assert any(e["event"] == "checkpoint" for e in led.events())
    # The carry is into the *ephemeral extract only* — the commit never holds the env-file.
    assert ".env" not in _tracked_files(tmp_path, res.commit)


def test_no_env_file_keeps_hermetic_capture_path(tmp_path):
    """AC2 (REQ-072): honor-when-present. With NO env-file, the capture check runs against
    the bare extract exactly as before — a self-sufficient green certifies, and a genuine
    source/test capture gap (a fail in the extract) is still refused. Carrying an env is
    opt-in-by-presence, never a new precondition."""
    # (a) self-sufficient green, no env-file anywhere → certifies.
    green = tmp_path / "green"
    green.mkdir()
    _scaffold(green, test="python -m pytest tests/test_dep.py")
    _init_git(green)

    res = _executor(green, writes={
        "tests/test_dep.py": _CAPTURED_TEST,
        "data.txt": "captured\n",
    }).advance_once()
    assert res.outcome is RunOutcome.DONE
    assert Ledger(green).status_of("REQ-001:develop") is StepStatus.DONE

    # (b) a genuine source gap, no env-file → still refused (REQ-063's guarantee, intact).
    gap = tmp_path / "gap"
    gap.mkdir()
    _scaffold(gap, test="python -m pytest tests/test_dep.py")
    (gap / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    _init_git(gap)

    res = _executor(gap, writes={
        "tests/test_dep.py": _DEP_TEST,
        "secret.txt": "load-bearing\n",
    }).advance_once()
    assert res.outcome is RunOutcome.VERIFY_FAILED
    led = Ledger(gap)
    assert led.status_of("REQ-001:develop") is StepStatus.FAILED
    assert any(e["event"] == "capture_gap" for e in led.events())


def test_configured_env_file_name_is_honored(tmp_path):
    """AC3 (REQ-072): ``verify.env_file`` names the carried file (default ``.env`` when
    unset; explicit ``null`` disables); a declared-but-absent file is a no-op, not an error;
    and ``build_executor`` wires the config value through to the engine."""
    assert Config(root=tmp_path).verify_env_file == ".env"
    assert Config(root=tmp_path, verify={"env_file": "steward.env"}).verify_env_file == "steward.env"
    assert Config(root=tmp_path, verify={"env_file": None}).verify_env_file is None

    # The custom-named declared file is carried: the env-gated green certifies.
    custom = tmp_path / "custom"
    custom.mkdir()
    _scaffold(custom, test="python -m pytest tests/test_env.py")
    (custom / ".gitignore").write_text("steward.env\n", encoding="utf-8")
    _init_git(custom)

    res = _executor(custom, env_file="steward.env", writes={
        "tests/test_env.py": _env_gated_test("steward.env"),
        "steward.env": "DB_ENGINE=postgres\n",
    }).advance_once()
    assert res.outcome is RunOutcome.DONE
    assert Ledger(custom).status_of("REQ-001:develop") is StepStatus.DONE

    # Declared-but-absent: a no-op — a self-sufficient green still certifies, no error.
    absent = tmp_path / "absent"
    absent.mkdir()
    _scaffold(absent, test="python -m pytest tests/test_dep.py")
    _init_git(absent)

    res = _executor(absent, env_file="steward.env", writes={
        "tests/test_dep.py": _CAPTURED_TEST,
        "data.txt": "captured\n",
    }).advance_once()
    assert res.outcome is RunOutcome.DONE

    # The config value reaches the engine through the standard assembly.
    cfg = Config(
        root=absent, accounts={"provider": "single"}, verify={"env_file": "steward.env"}
    )
    assert build_executor(cfg).verify_env_file == "steward.env"


def test_capture_gap_message_is_environment_honest(tmp_path):
    """AC4 (REQ-072): the withheld-certification message names the preserved work-commit SHA
    and frames the cause as source/test **or** environment (pointing at the env-file carry) —
    the red-herring "the cause is an uncaptured file — track it / fix .gitignore" single-cause
    text is gone, and it never instructs committing a gitignored secret."""
    _scaffold(tmp_path, test="python -m pytest tests/test_dep.py")
    (tmp_path / ".gitignore").write_text("secret.txt\n", encoding="utf-8")
    _init_git(tmp_path)

    res = _executor(tmp_path, writes={
        "tests/test_dep.py": _DEP_TEST,
        "secret.txt": "load-bearing\n",
    }).advance_once()

    assert res.outcome is RunOutcome.VERIFY_FAILED
    msg = res.detail
    assert res.commit and res.commit in msg          # names the preserved SHA
    assert "did not reproduce" in msg
    assert "source/test file" in msg                 # cause 1: an uncaptured source/test ...
    assert "runtime environment" in msg              # ... OR cause 2: a dropped environment
    assert "verify.env_file" in msg                  # points at the carry
    assert "never a secret" in msg                   # never "commit the secret"
    assert "fix .gitignore" not in msg               # the red-herring recovery is gone
    assert "The cause is an uncaptured source/test file" not in msg  # no single-cause claim


def test_env_file_contents_never_leak(tmp_path, monkeypatch):
    """AC5 (REQ-072): the carried env-file's key VALUES never reach the surfaced message,
    the event log, or any persisted artifact — the file is copied only into the ephemeral
    extract dir, which is removed after the run."""
    secret = "s3cr3t-hunter2-XYZZY"
    scratch = tmp_path / "scratch-tmp"
    scratch.mkdir()
    # Pin the in-process tempdir so the extract dir's lifetime is observable.
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    root = tmp_path / "repo"
    root.mkdir()
    _scaffold(root, test="python -m pytest tests/test_dep.py")
    (root / ".gitignore").write_text("secret.txt\n.env\n", encoding="utf-8")
    _init_git(root)
    (root / "tests").mkdir()
    (root / "tests" / "test_dep.py").write_text(_DEP_TEST, encoding="utf-8")
    (root / "secret.txt").write_text("load-bearing\n", encoding="utf-8")  # forces the withhold
    (root / ".env").write_text(f"DB_PASSWORD={secret}\n", encoding="utf-8")  # carried env

    res = _executor(root).advance_once()

    # The gap fires (the env-file WAS carried; secret.txt is genuinely uncaptured) ...
    assert res.outcome is RunOutcome.VERIFY_FAILED
    # ... and the secret value is nowhere: not the message, the ledger, or the git history.
    assert secret not in res.detail
    assert secret not in (root / ".devsteward" / "events.jsonl").read_text(encoding="utf-8")
    assert secret not in (root / ".devsteward" / "state.yaml").read_text(encoding="utf-8")
    assert secret not in _git(root, "log", "-p")
    # The extract dir — the only place the env-file was copied to — is gone after the run.
    assert list(scratch.iterdir()) == []
