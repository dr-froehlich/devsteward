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

# REQ-090: the per-step-kind model/effort policy (REQ-029 Decision 4 — a cold repair restart
# and the System Tester's procedure-following, REQ-030 Decision 2, don't need the top model)
# lives in the **stamped config**, not here. No model identifier belongs in a Python module:
# it would couple DevSteward's releases to Anthropic's, and it made the *global* default
# invisible while the per-step overrides were configurable — backwards. A project sets both
# levels in `.devsteward/config.yaml`; unset means claude's own default.


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
    plans_dir: str = "docs/plans"
    concepts_dir: str = "docs/concepts"
    accounts: dict = field(default_factory=lambda: {"provider": "clauder", "threshold": 70})
    claude: dict = field(
        default_factory=lambda: {
            "permission_mode": "dangerously-skip",
            "effort": "high",
        }
    )
    git: dict = field(
        default_factory=lambda: {
            "production_branch": "main",
            "integration_branch": "dev",
        }
    )
    verify: dict = field(default_factory=dict)
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
    def threshold(self) -> float:
        """Fixed quota gate (REQ-025): a fraction (``0.70``) or percent (``70``), default 70."""
        return (self.accounts or {}).get("threshold", 70)

    @property
    def model(self) -> str | None:
        """The configured model, or ``None`` when the project sets none (REQ-090).

        ``None`` is not a placeholder for a hidden default — it *is* the behaviour: the
        engine omits ``--model`` and the spawned session uses claude's own default. The
        stamped config ships this key filled in and visible, so a project normally answers
        here rather than inheriting anything.
        """
        return (self.claude or {}).get("model") or None

    @property
    def effort(self) -> str:
        return (self.claude or {}).get("effort", "high")

    def step_claude(self, kind: str) -> tuple[str | None, str | None]:
        """The ``(model, effort)`` for a session of ``kind`` (REQ-029 Decision 4).

        Precedence (REQ-090): a project's ``claude.steps.<kind>`` override → the flat
        ``claude.model``/``claude.effort``. There is no built-in third tier — both levels
        are config, so what a step spawns with is readable in one file. A kind the config
        doesn't name inherits the flat values; a model absent from both yields ``None``,
        and the engine omits ``--model``.
        """
        merged: dict = {}
        steps = (self.claude or {}).get("steps", {})
        if isinstance(steps, dict) and isinstance(steps.get(kind), dict):
            for key, value in steps[kind].items():
                if value is not None:
                    merged[key] = value
        return merged.get("model") or self.model, merged.get("effort") or self.effort

    @property
    def verify_full_suite(self) -> str | None:
        """The full project suite the land gate runs (REQ-028 AC3); default ``python -m
        pytest`` at the repo root. Set ``verify.full_suite`` to ``null`` to disable it."""
        return (self.verify or {}).get("full_suite", "python -m pytest")

    @property
    def verify_python(self) -> str | None:
        """Optional explicit interpreter the land gate runs tests under (REQ-028 AC4).

        A configured-but-unusable interpreter is a hard error, not a fall-through. Unset
        (the default) means discover: project venv, then ``sys.executable``."""
        return (self.verify or {}).get("python")

    @property
    def verify_env_file(self) -> str | None:
        """The operator's declared env-file the capture self-check carries into its tree
        extract (REQ-072). Default ``.env``; a project that names its environment in a
        differently-named file sets ``verify.env_file``; explicit ``null`` disables the
        carry. Honor-when-present: an absent file is a no-op, never an error."""
        return (self.verify or {}).get("env_file", ".env")

    @property
    def attribution_trailer(self) -> bool:
        """Whether engine commits carry the ``Assisted-by:`` trailer (REQ-091 Decision 12).

        Default on. A repo whose contributor policy bans AI trailers sets
        ``attribution_trailer: false`` (or ``null``, the same disabling convention
        ``verify.full_suite`` uses) and gets commits with no attribution trailer of any kind —
        not an empty one, not an ``unknown`` one. There is deliberately **no** seam for the
        trailer's key or format: one boolean answers the real need (comply without patching
        the engine), while a configurable format would only make history non-uniform across
        consumers for no gain."""
        return bool(self.raw.get("attribution_trailer", True))

    @property
    def plans_path(self) -> Path:
        """Where plan artifacts live (REQ-029 Decision 6 — the mechanical land refuses to
        land a REQ no plan here names), resolved under the repo root.

        Configurable since REQ-084 (``plans_dir``), like ``requirements_dir`` before it: a
        project whose ``docs/`` is owned by a docs generator (recipes publishes it with
        mkdocs) must be able to keep the engine's artifacts out of that tree. Defaults to
        the conventional ``docs/plans/``."""
        return self.root / self.plans_dir

    @property
    def concepts_path(self) -> Path:
        """Where concept docs live (REQ-039 — when a REQ declares ``process.concept``, the
        develop land refuses to land it unless the deliverable exists and the REQ's
        ``concept_refs`` reference it), resolved under the repo root. Configurable since
        REQ-084 (``concepts_dir``); defaults to ``docs/concepts/``."""
        return self.root / self.concepts_dir

    @property
    def index_path(self) -> Path:
        return self.root / self.index_file


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
        plans_dir=data.get("plans_dir", "docs/plans"),
        concepts_dir=data.get("concepts_dir", "docs/concepts"),
        accounts=data.get("accounts", {"provider": "clauder"}),
        claude=data.get("claude", {"permission_mode": "dangerously-skip"}),
        git=data.get("git", {}),
        verify=data.get("verify", {}),
        raw=data,
    )
