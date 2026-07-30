"""Assemble an :class:`Executor` from a project's config (profile, verifier, accounts)."""

from __future__ import annotations

from .config import Config
from .core.accounts import ClauderAccountProvider, SingleAccountProvider
from .core.executor import Executor
from .core.git import GitCli
from .core.verify import CommandVerifier, _pytest_targets
from .profiles.generic import GenericStepSource
from .profiles.req import ReqStepSource
from .profiles.req.reqfile import load_reqs
from .profiles.req.checkpoint import (
    CompositeLandGate,
    ConceptArtifactGate,
    PlanArtifactGate,
    ReqDoneFlipper,
)
from .profiles.req.validate import ReqValidateRoutine
from .profiles.req.verify import ReqVerifier

#: REQ-029 Decision 3 (adopted plan 0011): a red develop gate gets two engine-spawned
#: repair sessions before the step parks for a human.
REPAIR_BUDGET = 2


def build_step_source(cfg: Config):
    if cfg.profile == "generic":
        return GenericStepSource()
    return ReqStepSource(cfg.req_dir)


def build_on_verified(cfg: Config):
    """The REQ profile owns the verify-gated terminal flip (REQ → ``done``); the generic
    profile has no content status to flip."""
    if cfg.profile == "generic":
        return None
    return ReqDoneFlipper(cfg.req_dir, cfg.index_path)


def build_land_gate(cfg: Config):
    """The REQ profile refuses the mechanical land when no plan names the REQ (REQ-029
    Decision 6) and, when a REQ declared ``process.concept``, when no concept doc names it
    (REQ-039); the generic profile has no artifact discipline."""
    if cfg.profile == "generic":
        return None
    return CompositeLandGate(
        PlanArtifactGate(cfg.plans_path, cfg.plans_dir),
        ConceptArtifactGate(cfg.concepts_path, cfg.req_dir, cfg.concepts_dir),
    )


def build_validate_runner(cfg: Config):
    """The REQ profile's System-Test routine (REQ-030); the generic profile has no
    validation phase."""
    if cfg.profile == "generic":
        return None
    return ReqValidateRoutine(cfg.req_dir, python=cfg.verify_python)


def _validation_nodeids(cfg: Config) -> tuple[str, ...]:
    """The project-wide ``artifact``/``manual`` acceptance node-ids (REQ-068 Decision 2).

    The develop full-suite gate deselects these so a one-time validation of an already-done
    REQ never runs in a later REQ's develop gate. The set is the lane a test *declares*,
    derived from frontmatter the engine already parses — not a hand-edited ``-m`` marker
    expression. Every element is a genuine pytest node-id: :func:`_pytest_targets` keeps only
    real targets (``file.py`` / ``file.py::test``) and yields nothing for a ``manual:`` AC's
    human prose, so a criterion that merely *mentions* pytest can never inject a bare word like
    ``tests`` that ``--deselect`` would read as the whole ``tests/`` tree (REQ-070).
    """
    nodeids: list[str] = []
    for req in load_reqs(cfg.req_dir):
        for ac in req.acceptance:
            if ac.check in ("artifact", "manual") and ac.test:
                nodeids.extend(_pytest_targets(ac.test))
    # Stable, de-duplicated order.
    return tuple(dict.fromkeys(nodeids))


def build_verifier(cfg: Config):
    # The REQ profile gives the guarantee teeth at land (a land step must run real
    # acceptance tests, no skip/zero-collection passes, the full suite is clean, and the
    # project env is resolved — REQ-028); the generic profile keeps the plain verifier.
    if cfg.profile == "generic":
        return CommandVerifier(cwd=str(cfg.root))
    return ReqVerifier(
        cwd=str(cfg.root),
        full_suite=cfg.verify_full_suite,
        python=cfg.verify_python,
        exclude_nodeids=_validation_nodeids(cfg),
    )


def build_accounts(
    cfg: Config,
    pin: int | None = None,
    *,
    threshold: float | None = None,
    announce=None,
    should_stop=None,
):
    provider = (cfg.accounts or {}).get("provider", "clauder")
    if provider == "single":
        return SingleAccountProvider()
    # REQ-058: the budget gate delegates to the external `clauder` CLI. The legacy `cswap`
    # provider value maps here too — DevSteward no longer drives cswap directly. REQ-061
    # reconnects the operator pin (renamed `--use` → `--pin`): when `pin` is set it is
    # forwarded as `clauder gate --pin N` (admit on account N alone, to drain its 7d window);
    # when None the gate is the REQ-058 combined-budget default unchanged.
    return ClauderAccountProvider(
        threshold=cfg.threshold if threshold is None else threshold,
        pin=pin,
        announce=announce,
        should_stop=should_stop,
    )


def build_executor(
    cfg: Config,
    *,
    pin: int | None = None,
    threshold: float | None = None,
    model: str | None = None,
    effort: str | None = None,
    announce=None,
    stop=None,
    autocommit: bool = True,
) -> Executor:
    # Per-step-kind (model, effort) (REQ-029 Decision 4). A CLI --model/--effort override
    # wins for the develop session (the primary); repair keeps its configured default.
    develop_model, develop_effort = cfg.step_claude("develop")
    if model is not None:
        develop_model = model
    if effort is not None:
        develop_effort = effort
    step_claude = {
        "develop": (develop_model, develop_effort),
        "repair": cfg.step_claude("repair"),
        "validate": cfg.step_claude("validate"),
    }
    # The generic profile has no repair/land discipline; only the REQ profile spawns repairs.
    repair_budget = 0 if cfg.profile == "generic" else REPAIR_BUDGET
    return Executor(
        root=cfg.root,
        source=build_step_source(cfg),
        verifier=build_verifier(cfg),
        accounts=build_accounts(
            cfg,
            pin=pin,
            threshold=threshold,
            announce=announce,
            should_stop=(stop.should_stop if stop is not None else None),
        ),
        autocommit=autocommit,
        permission_mode=(cfg.claude or {}).get("permission_mode", "dangerously-skip"),
        model=develop_model,
        effort=develop_effort,
        stop=stop,
        production_branch=cfg.production_branch,
        integration_branch=cfg.integration_branch,
        git=GitCli(cfg.root),
        on_verified=build_on_verified(cfg),
        land_gate=build_land_gate(cfg),
        step_claude=step_claude,
        repair_budget=repair_budget,
        validate_runner=build_validate_runner(cfg),
        verify_env_file=cfg.verify_env_file,
    )
