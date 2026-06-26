"""REQ-039 — the concept phase, the lightweight way.

`process.concept: true` makes the single ``develop`` step **attended** (no separate phase,
CLI verb, or skill); the concept session *is* that attended develop session. The engine's
firewall is a develop **land-gate** mirroring the ``docs/plans/`` rule: when — and only when —
a REQ declared a concept phase, the mechanical land refuses unless ``docs/concepts/REQ-NNN.md``
exists and the REQ's ``concept_refs`` reference it. A REQ without the flag is untouched.
"""

from __future__ import annotations

from devsteward.core.model import Step
from devsteward.profiles.req.checkpoint import ConceptArtifactGate
from devsteward.profiles.req.source import ReqStepSource

from conftest import write_req


def _develop_step(req_id: str) -> Step:
    return Step(id=f"{req_id}:develop", command=f"steward advance {req_id} develop",
                req=req_id, phase="develop")


def _write_concept_doc(root, req_id: str) -> None:
    concepts = root / "docs" / "concepts"
    concepts.mkdir(parents=True, exist_ok=True)
    (concepts / f"{req_id}.md").write_text(f"# {req_id} concept\n", encoding="utf-8")


def _write_concept_bundle(root, req_id: str, name: str = "concept.md") -> None:
    """A non-empty concept *bundle directory* ``docs/concepts/REQ-NNN/`` (REQ-067) — the
    natural home for a committed prototype's several files."""
    bundle = root / "docs" / "concepts" / req_id
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / name).write_text(f"# {req_id} concept bundle\n", encoding="utf-8")


# -- AC1 — concept makes develop attended; no separate concept step ------------


def test_concept_makes_develop_attended_no_separate_step(tmp_path):
    """A REQ with ``process.concept: true`` yields exactly one ``develop`` step, marked
    *attended* (so batch parks it naming the attended need) — there is **no** ``:concept``
    step. A REQ without the flag has a plain, non-attended develop step."""
    req_dir = tmp_path / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open", process={"concept": True})
    write_req(req_dir, "REQ-002", status="open")
    by_id = {s.id: s for s in ReqStepSource(req_dir).steps()}

    assert set(by_id) == {"REQ-001:develop", "REQ-002:develop"}  # no :concept step
    assert by_id["REQ-001:develop"].attended is True
    assert "concept" in by_id["REQ-001:develop"].attended_reason
    assert by_id["REQ-002:develop"].attended is False


# -- AC2 — the concept doc is required at land --------------------------------


def test_concept_doc_required_at_land(tmp_path):
    """When a REQ declared a concept phase, the land refuses unless
    ``docs/concepts/REQ-NNN.md`` exists; with the (linked) doc present it admits."""
    req_dir = tmp_path / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open", process={"concept": True},
              concept_refs=["docs/concepts/REQ-001.md"])
    gate = ConceptArtifactGate(tmp_path / "docs" / "concepts", req_dir)
    step = _develop_step("REQ-001")

    refusal = gate(step)
    assert refusal is not None and "no" in refusal and "REQ-001.md" in refusal

    _write_concept_doc(tmp_path, "REQ-001")
    assert gate(step) is None  # doc present and linked → admitted


# -- AC3 — the doc must be linked in concept_refs -----------------------------


def test_concept_doc_must_be_linked_in_concept_refs(tmp_path):
    """The land also refuses when the concept doc exists but the REQ's ``concept_refs`` does
    not reference it; once linked it admits."""
    req_dir = tmp_path / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open", process={"concept": True})  # refs empty
    _write_concept_doc(tmp_path, "REQ-001")
    gate = ConceptArtifactGate(tmp_path / "docs" / "concepts", req_dir)
    step = _develop_step("REQ-001")

    refusal = gate(step)
    assert refusal is not None and "concept_refs" in refusal

    write_req(req_dir, "REQ-001", status="open", process={"concept": True},
              concept_refs=["docs/concepts/REQ-001.md"])
    assert gate(step) is None


# -- AC4 — a REQ without the flag is never gated ------------------------------


def test_no_concept_flag_not_gated(tmp_path):
    """A REQ that did not declare a concept phase lands with no ``docs/concepts/`` file —
    the concept gate never fires for it (a generic/phase-less step is likewise untouched)."""
    req_dir = tmp_path / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open")  # no process.concept, no concept doc
    gate = ConceptArtifactGate(tmp_path / "docs" / "concepts", req_dir)

    assert gate(_develop_step("REQ-001")) is None
    assert gate(Step(id="generic", command="noop")) is None  # no req → not gated


# == REQ-067 — a committed prototype bundle directory satisfies the gate =======


def test_concept_bundle_directory_satisfies_gate(tmp_path):
    """REQ-067 AC1 — a concept deliverable that is a non-empty bundle directory
    ``docs/concepts/REQ-NNN/`` (with *no* flat ``REQ-NNN.md``) satisfies the existence check,
    and a ``concept_refs`` entry pointing inside it satisfies the link check → admitted."""
    req_dir = tmp_path / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open", process={"concept": True},
              concept_refs=["docs/concepts/REQ-001/concept.md"])
    _write_concept_bundle(tmp_path, "REQ-001")  # docs/concepts/REQ-001/concept.md, no flat file
    gate = ConceptArtifactGate(tmp_path / "docs" / "concepts", req_dir)

    assert not (tmp_path / "docs" / "concepts" / "REQ-001.md").exists()  # bundle only
    assert gate(_develop_step("REQ-001")) is None


def test_flat_form_admits_and_absent_or_empty_bundle_refused(tmp_path):
    """REQ-067 AC2 — back-compat + the negatives: the flat ``REQ-NNN.md`` form still admits;
    a concept REQ with neither a flat file nor a bundle dir is refused; and an *empty* bundle
    directory does not satisfy the existence check."""
    req_dir = tmp_path / "docs" / "requirements"
    concepts = tmp_path / "docs" / "concepts"
    gate = ConceptArtifactGate(concepts, req_dir)

    # flat form still admits (REQ-039 back-compat)
    write_req(req_dir, "REQ-001", status="open", process={"concept": True},
              concept_refs=["docs/concepts/REQ-001.md"])
    _write_concept_doc(tmp_path, "REQ-001")
    assert gate(_develop_step("REQ-001")) is None

    # neither a flat file nor a bundle directory → refused
    write_req(req_dir, "REQ-002", status="open", process={"concept": True},
              concept_refs=["docs/concepts/REQ-002/concept.md"])
    assert gate(_develop_step("REQ-002")) is not None

    # an empty bundle directory is not "non-empty" → still refused
    (concepts / "REQ-002").mkdir(parents=True, exist_ok=True)
    assert gate(_develop_step("REQ-002")) is not None


def test_concept_bundle_must_be_linked_in_concept_refs(tmp_path):
    """REQ-067 AC3 — the link discipline holds for the bundle form: a present, non-empty
    bundle directory whose path is *not* in ``concept_refs`` is refused (naming concept_refs);
    once a ref points inside the directory it admits."""
    req_dir = tmp_path / "docs" / "requirements"
    write_req(req_dir, "REQ-001", status="open", process={"concept": True})  # refs empty
    _write_concept_bundle(tmp_path, "REQ-001")
    gate = ConceptArtifactGate(tmp_path / "docs" / "concepts", req_dir)
    step = _develop_step("REQ-001")

    refusal = gate(step)
    assert refusal is not None and "concept_refs" in refusal

    write_req(req_dir, "REQ-001", status="open", process={"concept": True},
              concept_refs=["docs/concepts/REQ-001/concept.md"])
    assert gate(step) is None
