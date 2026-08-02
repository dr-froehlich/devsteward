"""Keep a consumer's stamped engine-owned artifacts current with the engine (REQ-036/066).

``steward new`` stamps the engine-owned artifacts — the bundled skills under
``.claude/skills/`` **and** the root ``STEWARD.md`` (the black-box ``steward`` manual) —
**once**; the engine is then upgraded independently while the stamped copies stay frozen,
and the two drift with no signal and no refresh path (REQ-034 Finding 50, REQ-066). This
module is the drift machinery: a provenance manifest (``.devsteward/stamped.lock``) so drift
is *detectable* and tellable apart from intentional customization, a classifier ``steward
status`` renders as a non-blocking signal, and a ``sync`` that refreshes safely.

Three reference points per **tracked artifact**, by sha256 of the file bytes:

* **S** — the *stamped* file in the consumer (e.g. ``.claude/skills/<name>/SKILL.md`` or
  the root ``STEWARD.md``),
* **L** — the *lock* record (the template hash this copy was stamped/synced from),
* **T** — the installed *template* copy (the engine's bundled ``templates/``).

The tracked set is **engine-derived** (REQ-066): read off whatever the installed template
actually ships — the discovered skill directories, the ``STEWARD.md`` it ships, and the
``_templates/req.md`` REQ template (REQ-086) — never a hand-maintained list that can fall out
of step. All three are the same species: engine behaviour that must track the engine, never
per-project content (unlike ``CLAUDE.md``/settings, which REQ-036 Decision 1 deliberately
excludes). This module is pure and git-free; ``templates_root`` is injected so it is testable
without a real install, and ``steward`` passes the package's bundled ``templates/`` plus the
project's ``requirements_dir`` (the one tracked artifact the consumer relocates).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .core.ledger import LEDGER_DIRNAME

#: The provenance manifest, committed under ``.devsteward/`` like the ledger (REQ-066:
#: renamed from ``skills.lock`` now that it records non-skill artifacts too).
LOCK_FILENAME = "stamped.lock"
#: The pre-REQ-066 manifest name, still *read* for back-compat when the new one is absent;
#: the next write migrates it forward (Decision 2) so no existing consumer is stranded.
LEGACY_LOCK_FILENAME = "skills.lock"
#: Where bundled skills live, relative to both a consumer root and a templates root.
SKILLS_RELDIR = Path(".claude") / "skills"
#: The one file that defines a skill (its presence marks a skill directory).
SKILL_FILE = "SKILL.md"
#: Skills the engine keeps for **its own operator** and never ships to a consumer (REQ-084,
#: restoring REQ-024 Decision 2). ``onboard`` migrates an *existing* project under the engine;
#: a stamped project is already onboarded and can only misuse it (its first step re-converts
#: the corpus in place). The skill still lives under ``templates/`` — that directory is also
#: DevSteward's own ``.claude/skills`` through a symlink, so it is the operator's copy — but
#: ``steward new`` does not stamp it and ``sync``/``status`` do not track it. A named
#: exclusion, not a marker: one entry, pinned in both directions by a meta-test.
OPERATOR_ONLY = frozenset({"onboard"})
#: The root-file engine-owned artifact: the black-box ``steward`` manual (REQ-057/066).
MANUAL_FILENAME = "STEWARD.md"
#: The REQ template the stamped ``/intake`` skill writes every new REQ from (REQ-086
#: Finding 2). It is an engine-owned stamped artifact by the same definition as the skills —
#: engine behaviour that must track the engine — and an onboarded project that never received
#: it gets an ``/intake`` referencing a file it does not have, so its very next intake breaks.
#: Unlike every other tracked artifact it does **not** live at the same relative path on both
#: sides: it ships at a fixed path in the template tree but lands under the consumer's
#: configured ``requirements_dir`` (REQ-084) — hence :attr:`Tracked.dstpath`.
REQ_TEMPLATE_RELDIR = Path("_templates")
REQ_TEMPLATE_FILE = "req.md"
#: The lock key, stable wherever the consumer puts its requirements dir.
REQ_TEMPLATE_KEY = "_templates/req.md"
#: The conventional ``requirements_dir`` — the template tree's own layout, and the default
#: for callers that have no :class:`~devsteward.config.Config` to hand.
DEFAULT_REQUIREMENTS_DIR = "docs/requirements"
#: Suffix for the backup a forced refresh leaves before overwriting a customized artifact.
BACKUP_SUFFIX = ".orig"


class Bucket(str, Enum):
    """How a stamped artifact stands relative to its lock baseline and the template."""

    IN_SYNC = "in-sync"
    STALE = "stale"
    CUSTOMIZED = "customized"
    BOTH_MOVED = "both-moved"
    MISSING = "missing"


@dataclass
class Drift:
    """One tracked artifact's standing. ``name`` is its lock key / display name."""

    name: str
    bucket: Bucket

    @property
    def in_sync(self) -> bool:
        return self.bucket is Bucket.IN_SYNC

    @property
    def is_customization(self) -> bool:
        """True when refreshing would overwrite consumer edits (needs ``--force``)."""
        return self.bucket in (Bucket.CUSTOMIZED, Bucket.BOTH_MOVED)


#: Back-compat alias — REQ-036 named the per-artifact record ``SkillDrift``.
SkillDrift = Drift


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
    """The engine-owned skill names the installed template **ships**, sorted.

    Operator-only skills (:data:`OPERATOR_ONLY`) are excluded: they live in the template
    tree because it doubles as DevSteward's own skill path, but they are never stamped
    into or tracked for a consumer (REQ-084)."""
    d = _template_skills_dir(templates_root)
    if not d.is_dir():
        return []
    return sorted(
        p.name
        for p in d.iterdir()
        if (p / SKILL_FILE).is_file() and p.name not in OPERATOR_ONLY
    )


def is_operator_only(rel: Path) -> bool:
    """True for a template path inside an operator-only skill directory (REQ-084).

    ``rel`` is relative to the templates root, so ``steward new``'s stamp can drop the
    whole directory — the skill dir itself and every file under it."""
    parts = Path(rel).parts
    depth = len(SKILLS_RELDIR.parts)
    return (
        parts[:depth] == SKILLS_RELDIR.parts
        and len(parts) > depth
        and parts[depth] in OPERATOR_ONLY
    )


def stamped_skill_file(root: Path, name: str) -> Path:
    return Path(root) / SKILLS_RELDIR / name / SKILL_FILE


def template_skill_file(templates_root: Path, name: str) -> Path:
    return _template_skills_dir(templates_root) / name / SKILL_FILE


@dataclass(frozen=True)
class Tracked:
    """An engine-owned stamped artifact (REQ-066).

    ``key`` is its identity in the lock and in drift/status output; ``relpath`` is its path
    relative to the **templates** root and ``dstpath`` its path relative to the **consumer**
    root. For the skills and the manual the stamping is a same-relative-path byte copy and the
    two are equal, which is why ``dstpath`` defaults to ``relpath``; the REQ template (REQ-086)
    is the one artifact whose destination is relocated by the consumer's ``requirements_dir``.
    """

    key: str
    relpath: Path
    dstpath: Path | None = None

    @property
    def consumer_relpath(self) -> Path:
        return self.relpath if self.dstpath is None else self.dstpath


def req_template_dst(requirements_dir: str = DEFAULT_REQUIREMENTS_DIR) -> Path:
    """Where the REQ template lands in a consumer whose corpus lives at ``requirements_dir``."""
    return Path(requirements_dir) / REQ_TEMPLATE_RELDIR / REQ_TEMPLATE_FILE


def tracked_artifacts(
    templates_root: Path, requirements_dir: str = DEFAULT_REQUIREMENTS_DIR
) -> list[Tracked]:
    """Every engine-owned stamped artifact the installed template ships, **engine-derived**.

    The bundled skills (discovered ``.claude/skills/<name>/SKILL.md`` directories), the root
    ``STEWARD.md``, and the REQ template ``_templates/req.md`` — each **iff the template ships
    it**, never a hand-maintained list (REQ-066, preserving REQ-036's engine-derived
    guarantee). The set covers a discovered-directory form (skills), a named root-file form
    (the manual), and a *relocated* form (the REQ template, which lands under the consumer's
    configured ``requirements_dir`` — REQ-084/086).
    """
    root = Path(templates_root)
    arts = [
        Tracked(name, SKILLS_RELDIR / name / SKILL_FILE)
        for name in bundled_skill_names(root)
    ]
    if (root / MANUAL_FILENAME).is_file():
        arts.append(Tracked(MANUAL_FILENAME, Path(MANUAL_FILENAME)))
    tmpl_src = req_template_dst(DEFAULT_REQUIREMENTS_DIR)  # fixed inside the template tree
    if (root / tmpl_src).is_file():
        arts.append(
            Tracked(REQ_TEMPLATE_KEY, tmpl_src, req_template_dst(requirements_dir))
        )
    return arts


# -- the lock manifest --------------------------------------------------------


def lock_path(root: Path) -> Path:
    return Path(root) / LEDGER_DIRNAME / LOCK_FILENAME


def legacy_lock_path(root: Path) -> Path:
    """The pre-REQ-066 ``skills.lock`` location, read for back-compat (Decision 2)."""
    return Path(root) / LEDGER_DIRNAME / LEGACY_LOCK_FILENAME


def read_lock(root: Path) -> dict[str, str]:
    """The ``{artifact-key: sha256}`` map, or ``{}`` when no lock exists yet.

    Reads ``stamped.lock`` if present; otherwise falls back to a legacy ``skills.lock`` so a
    consumer's recorded provenance survives the REQ-066 rename (no project is stranded). The
    legacy file is migrated forward on the next :func:`write_lock`.
    """
    p = lock_path(root)
    if not p.is_file():
        p = legacy_lock_path(root)
        if not p.is_file():
            return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return dict(data) if isinstance(data, dict) else {}


def write_lock(root: Path, mapping: dict[str, str]) -> None:
    p = lock_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(dict(sorted(mapping.items())), indent=2, sort_keys=True)
    p.write_text(body + "\n", encoding="utf-8")
    # Forward-migrate (Decision 2): once the authoritative ``stamped.lock`` is written, drop
    # the legacy ``skills.lock`` so there is exactly one manifest — no second name to confuse
    # the next reader, and the migrated provenance is fully preserved in the new file.
    legacy = legacy_lock_path(root)
    if legacy.is_file() and legacy != p:
        legacy.unlink()


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


def classify(
    root: Path,
    templates_root: Path,
    requirements_dir: str = DEFAULT_REQUIREMENTS_DIR,
) -> list[Drift]:
    """Bucket every engine-owned stamped artifact for ``root`` against the installed template."""
    lock = read_lock(root)
    out: list[Drift] = []
    for art in tracked_artifacts(templates_root, requirements_dir):
        s = _sha256(Path(root) / art.consumer_relpath)
        t = _sha256(Path(templates_root) / art.relpath)
        out.append(Drift(art.key, _bucket(s, lock.get(art.key), t)))
    return out


def drift(
    root: Path,
    templates_root: Path,
    requirements_dir: str = DEFAULT_REQUIREMENTS_DIR,
) -> list[Drift]:
    """Only the non-in-sync artifacts — what ``steward status`` reports."""
    return [d for d in classify(root, templates_root, requirements_dir) if not d.in_sync]


# -- seeding & sync -----------------------------------------------------------


def seed_lock(
    root: Path,
    templates_root: Path,
    requirements_dir: str = DEFAULT_REQUIREMENTS_DIR,
) -> dict[str, str]:
    """Record each tracked artifact's source template hash (``steward new`` baseline)."""
    mapping = {
        art.key: h
        for art in tracked_artifacts(templates_root, requirements_dir)
        if (h := _sha256(Path(templates_root) / art.relpath)) is not None
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


def _refresh(root: Path, templates_root: Path, art: Tracked) -> None:
    """Byte-copy the installed template's artifact over the stamped copy."""
    src = Path(templates_root) / art.relpath
    dst = Path(root) / art.consumer_relpath
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())


def sync(
    root: Path,
    templates_root: Path,
    requirements_dir: str = DEFAULT_REQUIREMENTS_DIR,
    *,
    force: bool = False,
) -> SyncResult:
    """Refresh stale/missing tracked artifacts to byte-match the template, re-record the lock.

    ``stale`` (and a not-yet-stamped ``missing``) artifacts are refreshed and the lock
    updated — so a consumer lacking ``STEWARD.md``, or an onboarded project lacking the
    ``_templates/req.md`` its stamped ``/intake`` writes new REQs from (REQ-086), *acquires*
    it through the same path. ``requirements_dir`` says where that template lands — pass the
    project's configured value (REQ-084) or the conventional default.
    A ``customized``/``both-moved`` artifact is **refused** untouched unless ``force`` is
    given, in which case its current bytes are backed up to ``<name>.orig`` before the
    refresh and the lock is re-recorded (Decision 4 — never a silent clobber, never a prose
    merge).
    """
    arts = {a.key: a for a in tracked_artifacts(templates_root, requirements_dir)}
    lock = read_lock(root)
    result = SyncResult()
    for d in classify(root, templates_root, requirements_dir):
        art = arts[d.name]
        if d.bucket is Bucket.IN_SYNC:
            result.unchanged.append(d.name)
            # Backfill provenance for an in-sync artifact that has no (or a stale) lock
            # baseline. A legacy consumer stamped before lock-seeding (or one synced
            # while only some artifacts drifted) must end *fully* locked — otherwise these
            # untouched artifacts carry no baseline and will later mis-bucket as
            # ``customized`` (no lock) the moment the template advances, the very
            # conflation Decision 2/5 records the lock to prevent. S == T here, so the
            # template hash is the truthful record.
            if (h := _sha256(Path(templates_root) / art.relpath)) is not None:
                lock[d.name] = h
            continue
        if d.is_customization and not force:
            result.refused.append(d.name)
            continue
        if d.is_customization:  # force: back the consumer's copy up first
            current = Path(root) / art.consumer_relpath
            backup = current.with_name(current.name + BACKUP_SUFFIX)
            backup.write_bytes(current.read_bytes())
            result.backups[d.name] = str(backup)
            result.forced.append(d.name)
        else:  # stale or missing — safe refresh
            result.synced.append(d.name)
        _refresh(root, templates_root, art)
        h = _sha256(Path(templates_root) / art.relpath)
        if h is not None:
            lock[d.name] = h
    # REQ-084: the manifest records the *currently tracked* artifacts and nothing else.
    # When the engine retires an artifact (``onboard`` leaving ``templates/``), its key
    # would otherwise sit in every consumer's lock forever — a provenance baseline for a
    # file the engine no longer owns. Pruning is bookkeeping only: the consumer's copy on
    # disk is left untouched, theirs to keep or delete.
    write_lock(root, {key: h for key, h in lock.items() if key in arts})
    return result
