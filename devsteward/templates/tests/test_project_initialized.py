"""Project initialization — the north star's acceptance check (REQ-001).

This is the one test a freshly bootstrapped project ships with. It does not assert that
the project *works* — on day one there is nothing to work yet. It asserts that project
initialization was genuinely **accomplished**: the requirements scaffolding is coherent,
the ledger is initialized, and no unfilled placeholder survived the bootstrap interview.

**It must stay dependency-free — standard library and pytest only.** The engine's capture
check (REQ-063) re-runs every named acceptance test from a bare ``git archive`` extract of
the committed tree: no virtualenv, no installed project, none of the gitignored local
environment. A check that imports the project, or a YAML library, passes in the working
tree and then fails from the extract — which is exactly the trap this test exists to
replace. That is why the handful of scalar config values below are read with a small line
scanner instead of a real YAML parser: reading three keys by hand is the cheaper price.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Defaults mirror `.devsteward/config.yaml`; a project that moved its docs (REQ-084) is
# honored by reading the real values out of the config below.
DEFAULT_REQUIREMENTS_DIR = "docs/requirements"
DEFAULT_INDEX_FILE = "docs/requirements/REQUIREMENTS_INDEX.md"

# An unfilled bootstrap token, e.g. {{PROJECT_NAME}}. Built from parts so that this file —
# which necessarily *describes* the pattern — cannot match its own scan.
PLACEHOLDER = re.compile(r"\{" * 2 + r"[A-Z_]+" + r"\}" * 2)

REQUIRED_FRONTMATTER_KEYS = ("id", "title", "status", "kind")

TEXT_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".json", ".toml", ".txt", ".cfg", ".ini"}

# Directory names the placeholder scan skips wherever they appear in the path.
# ``_templates`` (nested under the requirements dir) holds the REQ/plan/scenario stencils,
# which keep their tokens on purpose; the rest are not project content.
PLACEHOLDER_SCAN_EXEMPT_NAMES = {".git", ".venv", "__pycache__", "_templates"}

# Path prefixes, relative to the project root, that the scan skips. The bundled skills are
# engine-owned instruction text which *quotes* the very tokens it tells the bootstrap
# session to replace (e.g. "set {{TODAY}} to today's date") — quoting them is correct.
PLACEHOLDER_SCAN_EXEMPT_PREFIXES = ((".claude", "skills"),)


def _config_value(key: str, default: str) -> str:
    """Read one top-level scalar from ``.devsteward/config.yaml`` without a YAML library.

    Only top-level ``key: value`` lines are considered, which is all this test needs and
    all the config uses for these keys. Comments and quotes are stripped.
    """
    config = ROOT / ".devsteward" / "config.yaml"
    if not config.is_file():
        return default
    for line in config.read_text(encoding="utf-8").splitlines():
        if line[:1].isspace() or line.lstrip().startswith("#"):
            continue  # nested or comment — not a top-level key
        name, sep, value = line.partition(":")
        if not sep or name.strip() != key:
            continue
        value = value.split("#", 1)[0].strip().strip("'\"")
        if value:
            return value
    return default


def _frontmatter(path: Path) -> dict[str, str]:
    """Parse a REQ's YAML frontmatter block into flat ``key: value`` strings."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        pytest.fail(f"{path.name} does not open with a `---` frontmatter block")
    _, _, rest = text.partition("---")
    block, sep, _ = rest.partition("\n---")
    if not sep:
        pytest.fail(f"{path.name} has an unterminated frontmatter block")
    fields: dict[str, str] = {}
    for line in block.splitlines():
        if not line.strip() or line[:1].isspace() or line.lstrip().startswith("#"):
            continue
        name, sep, value = line.partition(":")
        if sep:
            fields[name.strip()] = value.split("#", 1)[0].strip().strip("'\"")
    return fields


def _requirements_dir() -> Path:
    return ROOT / _config_value("requirements_dir", DEFAULT_REQUIREMENTS_DIR)


def _index_file() -> Path:
    return ROOT / _config_value("index_file", DEFAULT_INDEX_FILE)


def test_north_star_exists_and_is_well_formed() -> None:
    """REQ-001 is present in the configured requirements dir with usable frontmatter."""
    req = _requirements_dir() / "REQ-001.md"
    assert req.is_file(), (
        f"the north star is missing at {req.relative_to(ROOT)} — a bootstrapped project "
        f"always has REQ-001"
    )
    fields = _frontmatter(req)
    missing = [key for key in REQUIRED_FRONTMATTER_KEYS if key not in fields]
    assert not missing, f"REQ-001 frontmatter is missing {missing}"
    assert fields["id"] == "REQ-001", f"REQ-001.md declares id {fields['id']!r}"


def test_index_row_agrees_with_the_north_star() -> None:
    """The index ↔ frontmatter pair — the single source of truth for status — is in sync."""
    index = _index_file()
    assert index.is_file(), f"the requirements index is missing at {index.relative_to(ROOT)}"

    row = next(
        (
            line
            for line in index.read_text(encoding="utf-8").splitlines()
            if line.lstrip().startswith("| REQ-001 ")
        ),
        None,
    )
    assert row is not None, "the requirements index has no row for REQ-001"

    cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
    assert len(cells) >= 3, f"the REQ-001 index row is malformed: {row!r}"

    frontmatter_status = _frontmatter(_requirements_dir() / "REQ-001.md")["status"]
    assert cells[2].lower() == frontmatter_status.lower(), (
        f"index says REQ-001 is {cells[2]!r} but its frontmatter says "
        f"{frontmatter_status!r} — the pair must move in the same commit"
    )


def test_ledger_is_initialized() -> None:
    """The engine's ledger exists and names a profile — `steward init` really ran."""
    ledger_dir = ROOT / ".devsteward"
    if not ledger_dir.exists():
        # No `.devsteward/` *at all* means this is not a project checkout — most often a
        # reduced copy of the tree that another test made to run the suite against (a real
        # pattern: such copies routinely omit the ledger on purpose). There is no
        # initialization to judge here. Note the narrowness: once the directory exists, a
        # missing state.yaml below is a hard failure, because that is a real half-set-up
        # project rather than a deliberate partial copy.
        pytest.skip("no .devsteward/ — not a project checkout, nothing to assert")

    config = ledger_dir / "config.yaml"
    state = ledger_dir / "state.yaml"
    assert config.is_file(), ".devsteward/config.yaml is missing — the project has no config"
    assert state.is_file(), ".devsteward/state.yaml is missing — the ledger was never initialized"

    profile = _config_value("profile", "")
    assert profile, ".devsteward/config.yaml declares no profile"
    assert "version" in state.read_text(encoding="utf-8"), (
        ".devsteward/state.yaml has no `version` key — it is not a ledger the engine wrote"
    )


def test_no_bootstrap_placeholder_survives() -> None:
    """Every placeholder token the interview was meant to fill is gone.

    See the two ``PLACEHOLDER_SCAN_EXEMPT_*`` constants for what legitimately keeps
    tokens. This file is exempt too, because it defines the pattern it searches for.
    """
    self_path = Path(__file__).resolve()
    survivors: list[str] = []

    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix not in TEXT_SUFFIXES:
            continue
        parts = path.relative_to(ROOT).parts
        if PLACEHOLDER_SCAN_EXEMPT_NAMES.intersection(parts):
            continue
        if any(
            parts[: len(prefix)] == prefix for prefix in PLACEHOLDER_SCAN_EXEMPT_PREFIXES
        ):
            continue
        if path.resolve() == self_path:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for token in sorted(set(PLACEHOLDER.findall(text))):
            survivors.append(f"{path.relative_to(ROOT)}: {token}")

    assert not survivors, (
        "unfilled bootstrap placeholders survive — initialization did not finish:\n  "
        + "\n  ".join(survivors)
    )
