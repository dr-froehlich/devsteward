"""Locate a consumer project and load its ``.devsteward/config.yaml``.

Per-project configuration lives in the consumer repo (the engine is shared and pinned).
The engine walks up from the cwd to find the ``.devsteward/`` directory, so ``steward``
works from any subdirectory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ruamel.yaml import YAML

from .core.ledger import LEDGER_DIRNAME

_yaml = YAML()

CONFIG_FILE = "config.yaml"


class ProjectNotFound(Exception):
    """Raised when no ``.devsteward/`` directory is found at or above the cwd."""


def find_root(start: Path | None = None) -> Path:
    """Walk up from ``start`` (default cwd) to the dir containing ``.devsteward/``."""
    cur = Path(start or Path.cwd()).resolve()
    for cand in [cur, *cur.parents]:
        if (cand / LEDGER_DIRNAME).is_dir():
            return cand
    raise ProjectNotFound(
        f"no {LEDGER_DIRNAME}/ found at or above {cur} — run `steward new` or `/bootstrap` first"
    )


@dataclass
class Config:
    root: Path
    profile: str = "req"
    requirements_dir: str = "docs/requirements"
    index_file: str = "docs/requirements/REQUIREMENTS_INDEX.md"
    roadmap_file: str = "docs/requirements/ROADMAP.md"
    accounts: dict = field(default_factory=lambda: {"provider": "cswap"})
    claude: dict = field(default_factory=lambda: {"permission_mode": "dangerously-skip"})
    git: dict = field(
        default_factory=lambda: {
            "production_branch": "main",
            "integration_branch": "dev",
            "feature_branch": "req-{num}-{slug}",
        }
    )
    raw: dict = field(default_factory=dict)

    @property
    def req_dir(self) -> Path:
        return self.root / self.requirements_dir

    @property
    def production_branch(self) -> str:
        return (self.git or {}).get("production_branch", "main")

    @property
    def integration_branch(self) -> str:
        return (self.git or {}).get("integration_branch", "dev")

    @property
    def feature_branch_template(self) -> str:
        """Name template for an auto-managed implementation branch (REQ-020).

        Formatted with ``num`` (the REQ id sans ``REQ-`` prefix, keeping any lettered
        suffix) and ``slug``; default ``req-{num}-{slug}`` (e.g. ``req-020-...``).
        """
        return (self.git or {}).get("feature_branch", "req-{num}-{slug}")

    @property
    def index_path(self) -> Path:
        return self.root / self.index_file

    @property
    def roadmap_path(self) -> Path:
        return self.root / self.roadmap_file


def load_config(root: Path | None = None) -> Config:
    root = Path(root) if root is not None else find_root()
    cfg_path = root / LEDGER_DIRNAME / CONFIG_FILE
    data: dict = {}
    if cfg_path.exists():
        with cfg_path.open("r", encoding="utf-8") as fh:
            data = _yaml.load(fh) or {}
    return Config(
        root=root,
        profile=data.get("profile", "req"),
        requirements_dir=data.get("requirements_dir", "docs/requirements"),
        index_file=data.get("index_file", "docs/requirements/REQUIREMENTS_INDEX.md"),
        roadmap_file=data.get("roadmap_file", "docs/requirements/ROADMAP.md"),
        accounts=data.get("accounts", {"provider": "cswap"}),
        claude=data.get("claude", {"permission_mode": "dangerously-skip"}),
        git=data.get("git", {}),
        raw=data,
    )
