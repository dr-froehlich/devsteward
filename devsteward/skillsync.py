"""Keep a consumer's stamped bundled skills current with the installed engine (REQ-036).

``steward new`` stamps the engine-owned skills under ``.claude/skills/`` **once**; the
engine is then upgraded independently while the stamped copies stay frozen, and the two
drift with no signal and no refresh path (REQ-034 Finding 50). This module is the drift
machinery: a provenance manifest (``.devsteward/skills.lock``) so drift is *detectable*
and tellable apart from intentional customization, a classifier ``steward status`` renders
as a non-blocking signal, and a ``sync`` that refreshes safely.

Three reference points per bundled skill, by sha256 of the file bytes:

* **S** — the *stamped* file in the consumer (``.claude/skills/<name>/SKILL.md``),
* **L** — the *lock* record (the template hash this copy was stamped/synced from),
* **T** — the installed *template* copy (the engine's bundled ``templates/``).

The bundled set is **engine-derived** — read off whatever the installed template actually
ships under ``.claude/skills/`` — never a hand-maintained list that can fall out of step.
This module is pure and git-free; ``templates_root`` is injected so it is testable without
a real install, and ``steward`` passes the package's bundled ``templates/``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .core.ledger import LEDGER_DIRNAME

#: The provenance manifest, committed under ``.devsteward/`` like the ledger.
LOCK_FILENAME = "skills.lock"
#: Where bundled skills live, relative to both a consumer root and a templates root.
SKILLS_RELDIR = Path(".claude") / "skills"
#: The one file that defines a skill (its presence marks a skill directory).
SKILL_FILE = "SKILL.md"
#: Suffix for the backup a forced refresh leaves before overwriting a customized skill.
BACKUP_SUFFIX = ".orig"


class Bucket(str, Enum):
    """How a stamped skill stands relative to its lock baseline and the template."""

    IN_SYNC = "in-sync"
    STALE = "stale"
    CUSTOMIZED = "customized"
    BOTH_MOVED = "both-moved"
    MISSING = "missing"


@dataclass
class SkillDrift:
    name: str
    bucket: Bucket

    @property
    def in_sync(self) -> bool:
        return self.bucket is Bucket.IN_SYNC

    @property
    def is_customization(self) -> bool:
        """True when refreshing would overwrite consumer edits (needs ``--force``)."""
        return self.bucket in (Bucket.CUSTOMIZED, Bucket.BOTH_MOVED)


# -- hashing & paths ----------------------------------------------------------


def _sha256(path: Path) -> str | None:
    """The sha256 hex of ``path``'s bytes, or ``None`` when it does not exist."""
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _template_skills_dir(templates_root: Path) -> Path:
    return Path(templates_root) / SKILLS_RELDIR


def bundled_skill_names(templates_root: Path) -> list[str]:
    """The engine-owned skill names the installed template ships, sorted."""
    d = _template_skills_dir(templates_root)
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.iterdir() if (p / SKILL_FILE).is_file())


def stamped_skill_file(root: Path, name: str) -> Path:
    return Path(root) / SKILLS_RELDIR / name / SKILL_FILE


def template_skill_file(templates_root: Path, name: str) -> Path:
    return _template_skills_dir(templates_root) / name / SKILL_FILE


# -- the lock manifest --------------------------------------------------------


def lock_path(root: Path) -> Path:
    return Path(root) / LEDGER_DIRNAME / LOCK_FILENAME


def read_lock(root: Path) -> dict[str, str]:
    """The ``{skill-name: sha256}`` map, or ``{}`` when no lock exists yet."""
    p = lock_path(root)
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, dict) else {}


def write_lock(root: Path, mapping: dict[str, str]) -> None:
    p = lock_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(dict(sorted(mapping.items())), indent=2, sort_keys=True)
    p.write_text(body + "\n", encoding="utf-8")


# -- classification -----------------------------------------------------------


def _bucket(stamped: str | None, lock: str | None, template: str | None) -> Bucket:
    """Classify one skill from its three hashes (Decision 2 / AC4 matrix).

    ``in-sync`` is keyed on *stamped matches the installed template* (S == T) rather than
    strictly S==L==T: a stamped copy that already byte-matches the template needs no
    action, and this keeps the lock-less cases honest — DevSteward's own hardlinked repo
    skills stay quiet, and a no-lock copy that *differs* from the template falls through to
    ``customized`` (the conservative, no-clobber bucket) rather than a guessed ``stale``.
    """
    if stamped is None:
        return Bucket.MISSING
    if template is not None and stamped == template:
        return Bucket.IN_SYNC
    if lock is None:
        return Bucket.CUSTOMIZED  # differs from template, no baseline → don't clobber
    if stamped == lock:
        return Bucket.STALE  # untouched since stamp, template advanced
    if template == lock:
        return Bucket.CUSTOMIZED  # stamped edited, template unchanged
    return Bucket.BOTH_MOVED


def classify(root: Path, templates_root: Path) -> list[SkillDrift]:
    """Bucket every engine-owned bundled skill for ``root`` against the installed template."""
    lock = read_lock(root)
    out: list[SkillDrift] = []
    for name in bundled_skill_names(templates_root):
        s = _sha256(stamped_skill_file(root, name))
        t = _sha256(template_skill_file(templates_root, name))
        out.append(SkillDrift(name, _bucket(s, lock.get(name), t)))
    return out


def drift(root: Path, templates_root: Path) -> list[SkillDrift]:
    """Only the non-in-sync skills — what ``steward status`` reports."""
    return [d for d in classify(root, templates_root) if not d.in_sync]


# -- seeding & sync -----------------------------------------------------------


def seed_lock(root: Path, templates_root: Path) -> dict[str, str]:
    """Record each bundled skill's source template hash (``steward new`` baseline)."""
    mapping = {
        name: h
        for name in bundled_skill_names(templates_root)
        if (h := _sha256(template_skill_file(templates_root, name))) is not None
    }
    write_lock(root, mapping)
    return mapping


@dataclass
class SyncResult:
    synced: list[str] = field(default_factory=list)      # stale/missing → refreshed
    forced: list[str] = field(default_factory=list)      # customized refreshed under --force
    refused: list[str] = field(default_factory=list)     # customized, no --force
    unchanged: list[str] = field(default_factory=list)   # in-sync, nothing to do
    backups: dict[str, str] = field(default_factory=dict)  # name → .orig path

    @property
    def changed(self) -> bool:
        return bool(self.synced or self.forced)


def _refresh(root: Path, templates_root: Path, name: str) -> None:
    """Byte-copy the installed template's skill over the stamped copy."""
    src = template_skill_file(templates_root, name)
    dst = stamped_skill_file(root, name)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


def sync(root: Path, templates_root: Path, *, force: bool = False) -> SyncResult:
    """Refresh stale bundled skills to byte-match the template and re-record the lock.

    ``stale`` (and a not-yet-stamped ``missing``) skills are refreshed and the lock
    updated. A ``customized``/``both-moved`` skill is **refused** untouched unless
    ``force`` is given, in which case its current bytes are backed up to ``SKILL.md.orig``
    before the refresh and the lock is re-recorded (Decision 4 — never a silent clobber,
    never a prose merge).
    """
    lock = read_lock(root)
    result = SyncResult()
    for d in classify(root, templates_root):
        if d.bucket is Bucket.IN_SYNC:
            result.unchanged.append(d.name)
            continue
        if d.is_customization and not force:
            result.refused.append(d.name)
            continue
        if d.is_customization:  # force: back the consumer's copy up first
            current = stamped_skill_file(root, d.name)
            backup = current.with_name(current.name + BACKUP_SUFFIX)
            backup.write_bytes(current.read_bytes())
            result.backups[d.name] = str(backup)
            result.forced.append(d.name)
        else:  # stale or missing — safe refresh
            result.synced.append(d.name)
        _refresh(root, templates_root, d.name)
        h = _sha256(template_skill_file(templates_root, d.name))
        if h is not None:
            lock[d.name] = h
    write_lock(root, lock)
    return result
