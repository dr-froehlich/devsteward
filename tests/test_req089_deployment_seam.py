"""REQ-089 — the remote-host deployment seam.

One seam, four workstreams: get code onto a remote host, prove it there, and fix what the
proof finds without paying for the proof twice.

* **AC1** the four doctrine surfaces state the mid-phase grant on the **attended** axis and
  no longer fence it to `concept: true` — the *removal* is asserted, so an additive-only edit
  reds.
* **AC3** `steward gate` previews the develop verdict and mutates nothing.
* **AC4** `steward rework` carries prior green ACs forward (REQ-075's machinery, which
  `rework` never used) and `_pending_revalidate` consumes a scope-bearing `rework`.
* **AC5/AC6** the CLI is flat and no owned surface still names a two-word form.

Hermetic (REQ-064 screen): no lab, no network, no `claude`. The doctrine tests read the
**template** paths — those are what `steward new` / `steward sync` stamp, and the repo's own
`.claude/skills/` are hardlinks to them.

`-k` selector tokens (`doctrine`, `gate_previews`, `carries_green`, `flat`, `two_word`) are
disjoint from the module name (REQ-080's selector lesson).
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from types import SimpleNamespace

import click
import pytest
from click.testing import CliRunner

from devsteward.cli import main as cli_main
from devsteward.config import Config
from devsteward.core.ledger import Ledger
from devsteward.core.model import Decision, StepStatus
from devsteward.lifecycle import rework
from devsteward.profiles.req.validate import _pending_revalidate

from conftest import write_index
from test_system_test_phase import _REGRESSION, _write_plan, _write_req

_REPO = Path(__file__).resolve().parents[1]
_TEMPLATES = _REPO / "devsteward" / "templates"
_ADVANCE = _TEMPLATES / ".claude" / "skills" / "advance" / "SKILL.md"
_INTAKE = _TEMPLATES / ".claude" / "skills" / "intake" / "SKILL.md"
_MANUAL_MD = _TEMPLATES / "STEWARD.md"
_HANDBOOK_METHOD = _REPO / "devsteward" / "handbook" / "_00-method.qmd"


# -- AC1: the doctrine surfaces -------------------------------------------------


def _norm(path: Path) -> str:
    """The file as one whitespace-collapsed lowercase string, so an assertion about *wording*
    is not an assertion about where the author wrapped the line."""
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8")).lower()


def test_doctrine_surfaces_state_the_attended_rule():
    """AC1: each of the four surfaces carries the new rule AND has shed the stale absolute.

    The removals are what make this disconfirmable — REQ-071 wrote the right rule on the
    wrong axis, so a surface that merely *adds* the attended grant beside the old
    `concept: true` fence still leaves a session reading a contradiction.
    """
    advance = _norm(_ADVANCE)
    # (a) /advance — the attended grant, its round-trip trigger, plain git as the mechanism,
    # checkpoint still terminal, batch still absolute.
    assert "attended grant" in advance
    assert "round-trip through external infrastructure" in advance
    assert "plain `git` commits by the session" in advance
    assert "`steward checkpoint` is the terminal act" in advance
    assert "*(batch)* do **not** commit" in advance
    # …and the enumerated-exception framing is gone.
    assert "one sanctioned exception" not in advance
    assert "mid-phase commits during an *empirical* `concept: true` phase" not in advance
    # No surviving sentence fences mid-phase committing to a concept phase: every mention of
    # committing/pushing mid-phase must sit in an attended-keyed clause, not a flag-keyed one.
    assert "such a phase may legitimately **commit, push, and deploy" not in advance
    # The deploy-shaped proof is a develop-session obligation, not the validator's.
    assert "proof that needs a deploy belongs in *this* session" in advance
    assert "no repair loop" in advance

    # (b) /intake — names the deploy-shaped case, keeps "grant, not a restriction".
    intake = _norm(_INTAKE)
    assert "grant, not a restriction" in intake
    assert "the deploy-shaped case" in intake
    assert "belongs in the **develop session**" in intake

    # (c) STEWARD.md — the parenthetical is gone; the attended rule stands in its place.
    manual = _norm(_MANUAL_MD)
    assert "one exception: an *empirical* `concept: true` phase may commit mid-phase" not in manual
    assert "the one grant is attended" in manual
    assert "round-trip through external infrastructure" in manual
    assert "never commits" in manual  # the batch prohibition survives

    # (d) handbook rule 4 — restated on the attended axis.
    method = _norm(_HANDBOOK_METHOD)
    assert "the concept phase iterates until the deliverable is frozen." not in method
    assert "work that needs the real world iterates — attended" in method
    assert "keyed on **attended**" in method


# -- AC3: `steward gate` --------------------------------------------------------

_GATE_CONFIG = """\
profile: req
accounts:
  provider: single
git:
  production_branch: main
  integration_branch: dev
verify:
  full_suite: "true"
"""

_PASSING = "def test_ok():\n    assert True\n"
_FAILING = "def test_ok():\n    assert False, 'the named behaviour regressed'\n"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True
    ).stdout


def _gate_project(root: Path, body: str) -> None:
    """A real on-disk project whose REQ-001 names one runnable regression test."""
    req_dir = root / "docs" / "requirements"
    ac = {
        "id": "AC1",
        "test": "python -m pytest -p no:cacheprovider tests/test_thing.py::test_ok",
        "check": "regression",
    }
    _write_req(req_dir, "REQ-001", [ac], status="open")
    write_index(req_dir, [("REQ-001", "REQ-001 title", "OPEN", "–")])
    _write_plan(root, "REQ-001")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_thing.py").write_text(body, encoding="utf-8")
    # Test droppings the gate does not own — kept out of `git status` so the read-only
    # assertion is about the *gate*, not about pytest's cache.
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n.pytest_cache/\n", encoding="utf-8")
    Ledger.init(root)
    (root / ".devsteward" / "config.yaml").write_text(_GATE_CONFIG, encoding="utf-8")
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "gate@devsteward.test")
    _git(root, "config", "user.name", "Gate Test")
    _git(root, "checkout", "-q", "-b", "dev")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "scaffold")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path) -> dict:
    """Everything AC3 requires to be byte-identical across a `gate` run.

    ``--no-optional-locks`` matters: a plain ``git status`` refreshes the index stat cache and
    **rewrites `.git/index`** as a side effect, so the probe would report its own mtime bump as
    the gate's mutation. The flag makes the observation read-only, which is the only way to
    measure a read-only contract honestly.
    """
    index_mtime = (root / ".git" / "index").stat().st_mtime_ns
    return {
        "state": _sha(root / ".devsteward" / "state.yaml"),
        "events": _sha(root / ".devsteward" / "events.jsonl"),
        "req": _sha(root / "docs" / "requirements" / "REQ-001.md"),
        "head": _git(root, "--no-optional-locks", "rev-parse", "HEAD"),
        "porcelain": _git(root, "--no-optional-locks", "status", "--porcelain"),
        "index": _sha(root / ".git" / "index"),
        "index_mtime": index_mtime,
        "evidence": sorted(
            str(p.relative_to(root))
            for p in (root / ".devsteward").rglob("*")
            if "evidence" in p.parts
        ),
    }


@pytest.mark.parametrize(
    "body, expect_green", [(_PASSING, True), (_FAILING, False)], ids=["green", "red"]
)
def test_gate_previews_verdict_and_mutates_nothing(tmp_path, monkeypatch, body, expect_green):
    """AC3: `steward gate` reports the real verdict and leaves HEAD, the working tree, the
    git index, the ledger and the REQ file byte-identical — in both directions.

    The read-only half is the load-bearing one: a preview that quietly staged the tree (the
    REQ-063 capture check's `git add -A`) would be a mutation wearing a preview's name, and
    that staging path is where REQ-077/079/088 all found defects. So the check is a full
    before/after snapshot, not an inspection of what `gate`'s code happens to call.
    """
    _gate_project(tmp_path, body)
    monkeypatch.chdir(tmp_path)

    before = _snapshot(tmp_path)
    res = CliRunner().invoke(cli_main, ["gate", "REQ-001", "develop"])
    after = _snapshot(tmp_path)

    if expect_green:
        assert res.exit_code == 0, res.output
        assert "GREEN" in res.output
    else:
        assert res.exit_code != 0, res.output
        assert "RED" in res.output
        # The failing test is named, so the operator knows what to fix without re-running.
        assert "tests/test_thing.py::test_ok" in res.output

    assert after == before, "steward gate mutated project state"
    assert not (tmp_path / ".devsteward" / "evidence").exists()  # no evidence dir minted

    # AC3/requirement 8: the output says which gate this is — a green preview is not a
    # promise that the land will succeed.
    out = res.output.lower()
    assert "*verify* gate" in out
    assert "capture check" in out
    assert "not a promise that `steward checkpoint` will land" in out


def test_gate_previews_the_cursor_step_when_no_target_named(tmp_path, monkeypatch):
    """AC3 shape: `steward gate` with no argument previews the cursor step, like
    `steward checkpoint` — the same resolver, so the preview and the close it previews can
    never disagree about which step they mean."""
    _gate_project(tmp_path, _PASSING)
    monkeypatch.chdir(tmp_path)
    led = Ledger(tmp_path)
    led.set_cursor("REQ-001:develop")
    led.save()

    before = _snapshot(tmp_path)
    res = CliRunner().invoke(cli_main, ["gate"])

    assert res.exit_code == 0, res.output
    assert "REQ-001:develop" in res.output
    assert _snapshot(tmp_path) == before


# -- AC4: rework carries prior sign-offs ----------------------------------------


def _seed_red_with_mixed_results(root: Path):
    """An in-flight REQ-001 parked on a red validation that recorded one green `artifact`
    AC, one green `manual` AC (with its sign-off) and one red `artifact` AC — the operator's
    real case: a long walkthrough already passed, one thing is broken."""
    req_dir = root / "docs" / "requirements"
    acs = [
        _REGRESSION,
        {"id": "AC2", "test": "true", "check": "artifact"},
        {"id": "AC3", "test": "manual: reviewer walks the deploy", "check": "manual"},
        {"id": "AC4", "test": "false", "check": "artifact"},
    ]
    _write_req(req_dir, "REQ-001", acs, status="open")
    write_index(req_dir, [("REQ-001", "t", "OPEN", "–")])
    _write_plan(root, "REQ-001")
    Ledger.init(root)
    led = Ledger(root)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.save()

    src_rel = ".devsteward/evidence/REQ-001/20260806T090000Z"
    src = root / src_rel
    src.mkdir(parents=True)
    (src / "capture.txt").write_text("deploy walkthrough log\n", encoding="utf-8")
    signoff = {
        "ac": "AC3", "approved": True, "reviewer": "Petra",
        "scope": "walked the remote deploy end to end", "date": "2026-08-06",
    }
    led.append_event(
        "validation", step="REQ-001:validate", req="REQ-001", ok=False,
        driver="interactive", rerun=False, evidence=src_rel,
        results=[
            {"ac": "AC2", "check": "artifact", "ok": True, "detail": "[0] true"},
            {"ac": "AC3", "check": "manual", "ok": True, "detail": "sign-off by Petra"},
            {"ac": "AC4", "check": "artifact", "ok": False, "detail": "[1] false"},
        ],
        artifacts=[], signoffs=[signoff],
    )
    dec = Decision(
        id=led.next_decision_id(), step="REQ-001:validate",
        question="REQ-001 validation red — needs a human", req="REQ-001",
    )
    led.park_decision(dec)
    return led, src_rel


def test_rework_carries_green_acs_forward(tmp_path):
    """AC4: `rework` still reopens develop, **and** writes REQ-075's scope + carry.

    `revalidate` carried green one-offs forward but left develop `DONE` (no gate for a code
    fix); `rework` was the right route for a code fix but never called `_scope_revalidation`
    at all, so every `artifact`/`manual` AC was re-walked from scratch. Both halves are
    asserted here — the write (the event) and the read (`_pending_revalidate`) — because
    either alone is inert.
    """
    led, src_rel = _seed_red_with_mixed_results(tmp_path)

    res = rework(Config(root=tmp_path), led, "REQ-001")

    # The rework contract is unchanged: develop reopens for the fix.
    assert led.status_of("REQ-001:develop") is StepStatus.RECOVER
    assert led.status_of("REQ-001:validate") is StepStatus.PENDING

    # Only the red AC re-opens; both greens carry, each with its provenance.
    assert res.scope == ["AC4"]
    carried = {c["ac"]: c for c in res.carried}
    assert set(carried) == {"AC2", "AC3"}
    for entry in carried.values():
        assert entry["source_evidence"] == src_rel
        assert entry["source_event"] is not None  # the originating validation event's ts
    assert carried["AC3"]["signoff"]["reviewer"] == "Petra"

    # The same thing is on the persisted event, not only in the return value.
    fresh = Ledger(tmp_path)
    ev = [e for e in fresh.events() if e["event"] == "rework"][-1]
    assert ev["scope"] == ["AC4"]
    assert {c["ac"] for c in ev["carried"]} == {"AC2", "AC3"}
    assert ev["evidence"] == src_rel  # the existing repair-context field is untouched

    # The read half: the consumption side recognises a scope-bearing `rework`.
    pending = _pending_revalidate(fresh, "REQ-001")
    assert pending is not None and pending["event"] == "rework"
    assert pending["scope"] == ["AC4"]


def test_rework_carry_is_inert_without_the_consuming_read(tmp_path, monkeypatch):
    """AC4 disconfirmability: with the `_pending_revalidate` read reverted to REQ-075's
    `revalidate`-only match, the very same written event is invisible — nothing populates
    `ctx.reval`, so `_carry_forward` never runs and every AC is re-walked.

    This is the half that would silently do nothing if forgotten: data written and never
    consumed reads exactly like a working feature until someone re-walks an hour of manual QA.
    """
    led, _ = _seed_red_with_mixed_results(tmp_path)
    rework(Config(root=tmp_path), led, "REQ-001")
    fresh = Ledger(tmp_path)
    assert _pending_revalidate(fresh, "REQ-001") is not None

    monkeypatch.setattr(
        "devsteward.profiles.req.validate._SCOPING_EVENTS", ("revalidate",)
    )
    assert _pending_revalidate(fresh, "REQ-001") is None


def test_rework_carry_degenerates_to_a_full_rerun(tmp_path):
    """AC4 degenerate cases (requirement 12) are unchanged: a red validation with no green
    AC records no scope, so the re-validation is a full re-run exactly as before REQ-089."""
    req_dir = tmp_path / "docs" / "requirements"
    _write_req(
        req_dir, "REQ-001",
        [_REGRESSION, {"id": "AC2", "test": "false", "check": "artifact"}], status="open",
    )
    write_index(req_dir, [("REQ-001", "t", "OPEN", "–")])
    Ledger.init(tmp_path)
    led = Ledger(tmp_path)
    led.set_status("REQ-001:develop", StepStatus.DONE)
    led.save()
    led.append_event(
        "validation", step="REQ-001:validate", req="REQ-001", ok=False,
        driver="interactive", rerun=False, evidence=".devsteward/evidence/REQ-001/x",
        results=[{"ac": "AC2", "check": "artifact", "ok": False, "detail": "[1] false"}],
        artifacts=[], signoffs=[],
    )
    led.park_decision(Decision(
        id=led.next_decision_id(), step="REQ-001:validate", question="red", req="REQ-001",
    ))

    res = rework(Config(root=tmp_path), led, "REQ-001")

    assert res.scope is None and res.carried is None
    ev = [e for e in Ledger(tmp_path).events() if e["event"] == "rework"][-1]
    assert "scope" not in ev and "carried" not in ev
    assert _pending_revalidate(Ledger(tmp_path), "REQ-001") is None


# -- AC5: the CLI is flat and discoverable --------------------------------------

_FLAT_COMMANDS = ("validate-start", "validate-record", "decision-list", "decision-answer")


def _walk(group: click.Group, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], click.Command]:
    """Every command in the tree, keyed by the words needed to invoke it."""
    found: dict[tuple[str, ...], click.Command] = {}
    for name, cmd in group.commands.items():
        path = (*prefix, name)
        found[path] = cmd
        if isinstance(cmd, click.Group):
            found.update(_walk(cmd, path))
    return found


def test_cli_is_flat_and_discoverable():
    """AC5: every invocable command is one word deep, with declared arguments.

    `steward validate start` was the one command in the CLI designed to be run *mid-phase*
    and the least discoverable thing in it — a hand-parsed `nargs=-1` variadic, so walking
    click's own command tree printed only `steward validate <words>` and the `[start|record]`
    in the help text was a hand-written metavar. Nothing introspectable said the verbs
    existed.
    """
    tree = _walk(cli_main)

    for name in _FLAT_COMMANDS:
        assert (name,) in tree, f"{name} is not a top-level command"

    # No command stands a verb up in a variadic positional (the wart that hid start/record).
    for path, cmd in tree.items():
        for param in cmd.params:
            if isinstance(param, click.Argument):
                assert param.nargs != -1, f"{' '.join(path)} declares a variadic positional"

    runner = CliRunner()
    # Shape A is untouched; the two-word forms are hard-renamed away (Decision 9).
    assert runner.invoke(cli_main, ["validate", "--help"]).exit_code == 0
    assert runner.invoke(cli_main, ["validate", "start", "REQ-001"]).exit_code != 0
    assert runner.invoke(cli_main, ["decision", "list"]).exit_code != 0

    # One `--help` shows everything — no second `--help` needed to discover a verb.
    top = runner.invoke(cli_main, ["--help"])
    assert top.exit_code == 0
    for (path, _cmd) in tree.items():
        assert len(path) == 1, f"{' '.join(path)} is nested — not visible in one --help"
        assert path[0] in top.output, f"{path[0]} missing from `steward --help`"


# -- AC6: no owned surface names a two-word form --------------------------------

_TWO_WORD = re.compile(r"steward\s+(validate|decision)\s+(start|record|list|answer)\b")

#: Append-only history — read by the AC's *rationale* ("which are append-only history"), not
#: only its enumeration: the per-REQ record of what was true when a REQ landed. A landed REQ
#: file, its index row (lint-locked to that REQ's frontmatter title, so REQ-081's title still
#: names the verbs REQ-081 shipped), the postmortem reports, and the **plan** each landed REQ
#: was built from. Rewriting any of them would falsify the record. Everything else under
#: `docs/` is instructional and is scanned.
_HISTORY = ("docs/reports/", "docs/plans/")


def _is_history(rel: str) -> bool:
    if rel.startswith(_HISTORY):
        return True
    return bool(re.match(r"docs/requirements/(REQ-\d+|REQUIREMENTS_INDEX)", rel))


def test_no_surface_names_a_two_word_command():
    """AC6: nothing a reader could follow as an instruction still names a dead command.

    The hard rename (Decision 9) has no alias and no deprecation window, so any surviving
    `steward validate start` is a no-such-command error waiting for whoever types it.
    """
    roots = [
        _TEMPLATES / ".claude" / "skills",
        _MANUAL_MD,
        _REPO / "devsteward" / "handbook",
        _REPO / "docs",
    ]
    offenders: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file()]
        for path in paths:
            rel = path.relative_to(_REPO).as_posix()
            if _is_history(rel):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for match in _TWO_WORD.finditer(text):
                line = text[: match.start()].count("\n") + 1
                offenders.append(f"{rel}:{line}: {match.group(0)!r}")

    assert not offenders, "two-word command form(s) still named:\n" + "\n".join(offenders)
