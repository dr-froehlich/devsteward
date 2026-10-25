"""REQ-095 — the ``process.develop`` key is retired.

``develop: split`` promised a phase the engine never had. Its only reader set
``Step.attended`` with a design-review reason; ``concept: true`` set the same flag from the
``elif`` below *and* added a real land gate, so split was a strict subset of concept that
contributed nothing. The key is removed from the engine and from every live doc surface.

What must **not** happen is a migration: ``steward lint`` schema-validates every REQ
including ``done`` ones and reads the *packaged* schema, so a hard enum removal would red
125 REQs across 7 repos at once through the shared pipx engine. Unlike REQ-083's config
seam — where ``data.get(...)`` gave tolerance for free — the ``process`` block is
``additionalProperties: false``, so tolerance here is declared on purpose and pinned below.
"""

from __future__ import annotations

import json
from pathlib import Path

import devsteward
from devsteward.config import Config
from devsteward.core.executor import RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Step
from devsteward.lint import lint
from devsteward.profiles.req.checkpoint import ConceptArtifactGate
from devsteward.profiles.req.reqfile import PROCESS_DEFAULTS, parse_req
from devsteward.profiles.req.source import ReqStepSource

from conftest import ok_result, write_index, write_req
from test_phase_model import FakeRunner, _executor, _write_plan

PACKAGE = Path(devsteward.__file__).parent

# Binary/compiled artifacts carry no doctrine and are not source we edit.
_SKIP_DIRS = {"__pycache__", ".git"}
_SKIP_SUFFIXES = {".pyc", ".pyo", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ico"}


def _package_files() -> list[Path]:
    return [
        p
        for p in PACKAGE.rglob("*")
        if p.is_file()
        and p.suffix.lower() not in _SKIP_SUFFIXES
        and not _SKIP_DIRS & set(p.relative_to(PACKAGE).parts)
    ]


def _cfg(tmp_path) -> Config:
    return Config(root=tmp_path, requirements_dir="reqs",
                  index_file="reqs/REQUIREMENTS_INDEX.md")


def _develop_step(rid: str) -> Step:
    return Step(id=f"{rid}:develop", command="x", req=rid, phase="develop")


# -- AC1 — the engine has no reader of process.develop ------------------------


def test_legacy_split_req_is_not_attended(tmp_path):
    """A REQ declaring only ``develop: split`` derives a **non-attended** develop step, and
    an unattended ``steward run`` *lands* it instead of parking it.

    This is the behavioural proof that the reader is gone: before REQ-095 the same REQ
    parked with "needs an attended design review" and no session was ever spawned for it.
    """
    req_dir = tmp_path / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open", process={"develop": "split"})
    write_index(req_dir, [("REQ-001", "legacy split", "OPEN", "–")])
    _write_plan(tmp_path, "REQ-001")

    step = {s.id: s for s in ReqStepSource(req_dir).steps()}["REQ-001:develop"]
    assert step.attended is False
    assert step.attended_reason == ""

    Ledger.init(tmp_path)
    runner = FakeRunner(default=ok_result())
    results = _executor(tmp_path, runner=runner).run()

    assert {r.step.id: r.outcome for r in results}["REQ-001:develop"] is RunOutcome.DONE
    # a develop session really was spawned for it — not parked, not skipped
    assert any("REQ-001" in c["command"] for c in runner.calls)


# -- AC2 — concept is untouched by the if/elif collapse -----------------------


def test_concept_still_parks_and_gates(tmp_path):
    """Deleting the ``split`` branch above it regresses neither half of ``concept: true``:
    the step is still attended (batch parks it, naming the concept need), and the concept
    land gate still refuses a REQ with no deliverable.

    The park reason is now always the concept one — the message a both-flags REQ could
    never reach while ``split`` shadowed it in the ``if``/``elif``.
    """
    req_dir = tmp_path / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open",
              process={"concept": True}, concept_refs=["docs/concepts/REQ-001.md"])
    # a REQ that declares BOTH now reports the concept need, not the design-review one
    write_req(req_dir, "REQ-002", status="open",
              process={"concept": True, "develop": "split"})
    write_index(req_dir, [("REQ-001", "concept", "OPEN", "–"),
                          ("REQ-002", "both flags", "OPEN", "–")])

    by_id = {s.id: s for s in ReqStepSource(req_dir).steps()}
    for rid in ("REQ-001", "REQ-002"):
        step = by_id[f"{rid}:develop"]
        assert step.attended is True
        assert "concept" in step.attended_reason
        assert "design review" not in step.attended_reason

    # the land gate half is untouched: no deliverable → refusal; deliverable → admitted
    gate = ConceptArtifactGate(tmp_path / "docs" / "concepts", req_dir)
    step = _develop_step("REQ-001")
    assert gate(step) is not None

    concepts = tmp_path / "docs" / "concepts"
    concepts.mkdir(parents=True, exist_ok=True)
    (concepts / "REQ-001.md").write_text("# concept\n", encoding="utf-8")
    assert gate(step) is None

    # batch parks the attended step rather than spawning a session for it
    _write_plan(tmp_path, "REQ-001")
    Ledger.init(tmp_path)
    runner = FakeRunner(default=ok_result())
    results = _executor(tmp_path, runner=runner).run()
    assert {r.step.id: r.outcome for r in results}["REQ-001:develop"] is RunOutcome.PARKED
    assert all("REQ-001" not in c["command"] for c in runner.calls)


# -- AC3 — legacy tolerance is structural -------------------------------------


def test_legacy_develop_key_lints_green_and_is_ignored(tmp_path):
    """A REQ still carrying ``develop: split`` or ``develop: fused`` lints **green**, and
    ``ReqFile.process`` defaults no ``develop`` key of its own.

    The schema keeps the property *declared* (``process`` is ``additionalProperties:
    false``, so removing it would invalidate every REQ that ever declared a develop mode —
    18 of the 19 ``split`` declarers are terminal history). The value survives as inert
    frontmatter: it merges through untouched and nothing reads it.
    """
    req_dir = tmp_path / "reqs"
    write_req(req_dir, "REQ-001", status="open", process={"develop": "split"})
    write_req(req_dir, "REQ-002", status="done", process={"develop": "fused"})
    write_index(req_dir, [("REQ-001", "legacy split", "OPEN", "–"),
                          ("REQ-002", "legacy fused", "DONE", "–")])

    assert lint(_cfg(tmp_path)) == []

    # the engine defaults no develop mode, so a REQ that declares none has none —
    # there is nothing for a reader to read.
    assert "develop" not in PROCESS_DEFAULTS
    write_req(req_dir, "REQ-003", status="open")
    assert "develop" not in parse_req(req_dir / "REQ-003.md").process

    # a declared legacy value passes through unchanged rather than being scrubbed:
    # tolerance without a migration, which is the whole point.
    assert parse_req(req_dir / "REQ-001.md").process["develop"] == "split"
    assert parse_req(req_dir / "REQ-002.md").process["develop"] == "fused"


# -- AC4 — no live develop declaration ships ----------------------------------


def test_no_live_develop_declaration_in_package(tmp_path):
    """Nothing we ship presents a develop mode as a live process declaration.

    The sweep is the REQ-083 guard shape: a reference reintroduced by a template or
    handbook edit is exactly how the retired key would creep back. The two schema files'
    legacy ``description`` lines are the *only* permitted mentions — there the key must
    stay declared to do its tolerance job, so it must also say why (REQ-095 decision 7).
    """
    schema_names = {"req.schema.json"}
    banned = ("develop: split", "develop: fused", "split develop", "design review")

    hits: list[str] = []
    for path in _package_files():
        if path.name in schema_names:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            low = line.lower()
            if any(token in low for token in banned):
                hits.append(f"devsteward/{path.relative_to(PACKAGE)}:{lineno}: {line.strip()}")

    assert not hits, (
        "a retired develop-mode declaration crept back into the package:\n" + "\n".join(hits)
    )

    # The schema carries it only as a retired key, never as a live declaration.
    # REQ-096 deleted the stamped duplicate, so there is one schema to check.
    schema = json.loads((PACKAGE / "schema" / "req.schema.json").read_text(encoding="utf-8"))
    develop = schema["properties"]["process"]["properties"]["develop"]
    assert "RETIRED" in develop["description"]
    assert "REQ-095" in develop["description"]
    # historical values stay valid; a typo still fails schema
    assert set(develop["enum"]) == {"fused", "split"}


# -- AC5 — the shipped CLAUDE.md.tmpl concept bullet is accurate --------------


def test_claude_tmpl_concept_path_bullet_is_accurate():
    """The stamped CLAUDE.md told every consumer the concept doc *must* be a flat path and
    that the land gate enforces it. Both claims were false: ``ConceptArtifactGate`` accepts
    a non-empty ``<concepts_dir>/REQ-NNN/`` bundle (REQ-067) and the directory is
    configurable (REQ-084)."""
    raw = (PACKAGE / "templates" / "CLAUDE.md.tmpl").read_text(encoding="utf-8")
    # Prose wraps; a doc guard must not break on a reflow.
    tmpl = " ".join(raw.split())

    assert "REQ-NNN/" in tmpl and "bundle directory" in tmpl
    assert "concept_refs:" in tmpl
    assert "concepts_dir" in tmpl
    # the false claims are gone
    assert "not a subdirectory" not in tmpl
    assert "must** be written at the flat path" not in tmpl


# -- AC6 — REQ-071's phase-model fork restated without a flag -----------------


def test_phase_model_rule_restated_without_a_flag():
    """All three doctrine surfaces offer the real fork — the concept session authors the
    target ACs post-freeze, or a named downstream REQ owns them — and none names a flag.

    ``develop: split`` never created a post-freeze phase, so the old fork named a fiction;
    in all eight concept+split REQs the same attended session did both. REQ-071's actual
    teaching (no imported acceptance bar) is untouched.
    """
    surfaces = {
        "STEWARD.md": PACKAGE / "templates" / "STEWARD.md",
        "_00-method.qmd": PACKAGE / "handbook" / "_00-method.qmd",
        "intake": PACKAGE / "templates" / ".claude" / "skills" / "intake" / "SKILL.md",
    }
    for name, path in surfaces.items():
        # Prose wraps; a doc guard must not break on a reflow.
        doc = " ".join(path.read_text(encoding="utf-8").split())
        assert "the concept session itself authors the target ACs" in doc, name
        assert "downstream REQ" in doc, name
        assert "never carry the downstream REQ's" in doc, name
        assert "develop: split" not in doc, name
