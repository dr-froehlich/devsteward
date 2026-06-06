"""Parse the hybrid machine-readable REQ format.

A REQ file is Markdown with:

* schema-validated **YAML frontmatter** (``--- ... ---``) — the machine contract;
* prose sections (Context · Decisions · Requirement · Notes) — untouched, rich;
* a single fenced ```` ```yaml acceptance ```` block the verifier can run and track.

This module reads those parts. Frontmatter validation against ``req.schema.json`` lives
in the linter (:mod:`devsteward.cli`), not here — parsing is lenient so the linter can
report precise errors.
"""

from __future__ import annotations

import datetime as _dt
import io
import re
from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML

from ...core.model import AcceptanceCheck

_yaml = YAML()
_yaml.preserve_quotes = True

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n?(.*)$", re.DOTALL)
# Matches a fenced block opened with ```yaml acceptance (allowing 3+ backticks/tildes).
_ACCEPTANCE_RE = re.compile(
    r"(?:^|\n)(`{3,}|~{3,})yaml acceptance[^\n]*\n(.*?)\n\1", re.DOTALL
)

# REQ-NNN derived step phases, in order. The land step carries the acceptance tests.
PHASES = ("design", "build", "land")
# REQ statuses that produce work. draft = not yet ready; terminal statuses = no work.
ACTIVE_STATUSES = {"open", "in-progress", "blocked"}
TERMINAL_STATUSES = {"done", "dropped", "superseded"}


@dataclass
class ReqFile:
    """A parsed requirement file."""

    path: Path
    frontmatter: dict
    body: str
    acceptance: list[AcceptanceCheck] = field(default_factory=list)

    @property
    def id(self) -> str:
        return str(self.frontmatter.get("id", ""))

    @property
    def status(self) -> str:
        return str(self.frontmatter.get("status", ""))

    @property
    def depends_on(self) -> list[str]:
        return list(self.frontmatter.get("depends_on") or [])

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title", ""))

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_STATUSES

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


def _parse_acceptance(body: str) -> list[AcceptanceCheck]:
    m = _ACCEPTANCE_RE.search(body)
    if not m:
        return []
    raw = _yaml.load(io.StringIO(m.group(2))) or []
    checks: list[AcceptanceCheck] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        checks.append(
            AcceptanceCheck(
                id=str(item.get("id", "")),
                text=str(item.get("text", "")),
                test=str(item.get("test", "")),
                status=str(item.get("status", "pending")),
            )
        )
    return checks


def _normalize_dates(value):
    """YAML types unquoted ``2026-06-06`` as a ``date``; the format wants ISO strings.

    Coerce date/datetime values to ``YYYY-MM-DD`` so the whole system (schema, ledger,
    display) sees consistent strings, while REQ authors keep writing natural unquoted
    dates.
    """
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()[:10]
    if isinstance(value, dict):
        return {k: _normalize_dates(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalize_dates(v) for v in value]
    return value


def parse_req(path: Path) -> ReqFile:
    """Parse a single REQ file. Raises ValueError if frontmatter is missing/unparseable."""
    text = Path(path).read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(f"{path}: missing YAML frontmatter (expected leading '---' block)")
    try:
        frontmatter = _yaml.load(io.StringIO(m.group(1))) or {}
    except Exception as exc:  # noqa: BLE001 — surfaced verbatim by the linter
        raise ValueError(f"{path}: invalid YAML frontmatter: {exc}") from exc
    body = m.group(2)
    return ReqFile(
        path=Path(path),
        frontmatter=_normalize_dates(dict(frontmatter)),
        body=body,
        acceptance=_parse_acceptance(body),
    )


def load_reqs(req_dir: Path) -> list[ReqFile]:
    """Parse every ``REQ-*.md`` in ``req_dir`` (skipping ``.tmpl`` and template stubs)."""
    reqs: list[ReqFile] = []
    for p in sorted(Path(req_dir).glob("REQ-*.md")):
        if p.name.endswith(".tmpl") or p.stem == "REQ-xxx":
            continue
        reqs.append(parse_req(p))
    return reqs


def update_acceptance_status(path: Path, statuses: dict[str, str]) -> None:
    """Write back engine-owned ``status:`` values into a REQ's acceptance block.

    ``statuses`` maps AC id → ``pending|pass|fail``. Edits are surgical (line-level) so
    the surrounding prose and formatting are preserved.
    """
    text = Path(path).read_text(encoding="utf-8")
    m = _ACCEPTANCE_RE.search(text)
    if not m:
        return
    block = m.group(2)
    data = _yaml.load(io.StringIO(block)) or []
    changed = False
    for item in data:
        if isinstance(item, dict) and item.get("id") in statuses:
            item["status"] = statuses[item["id"]]
            changed = True
    if not changed:
        return
    out = io.StringIO()
    _yaml.dump(data, out)
    new_text = text[: m.start(2)] + out.getvalue().rstrip("\n") + text[m.end(2) :]
    Path(path).write_text(new_text, encoding="utf-8")
