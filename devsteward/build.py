"""Assemble an :class:`Executor` from a project's config (profile, verifier, accounts)."""

from __future__ import annotations

from .config import Config
from .core.accounts import CswapAccountProvider, SingleAccountProvider
from .core.executor import Executor
from .core.git import GitCli
from .core.verify import CommandVerifier
from .profiles.generic import GenericStepSource
from .profiles.req import ReqStepSource
from .profiles.req.checkpoint import PlanArtifactGate, ReqDoneFlipper
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
    Decision 6); the generic profile has no plan discipline."""
    if cfg.profile == "generic":
        return None
    return PlanArtifactGate(cfg.plans_dir)


def build_validate_runner(cfg: Config):
    """The REQ profile's System-Test routine (REQ-030); the generic profile has no
    validation phase."""
    if cfg.profile == "generic":
        return None
    return ReqValidateRoutine(cfg.req_dir, python=cfg.verify_python)


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
    )


def build_accounts(
    cfg: Config,
    use: int | None = None,
    *,
    threshold: float | None = None,
    announce=None,
    should_stop=None,
):
    provider = (cfg.accounts or {}).get("provider", "cswap")
    if provider == "single":
        return SingleAccountProvider()
    return CswapAccountProvider(
        use=use,
        threshold=cfg.threshold if threshold is None else threshold,
        announce=announce,
        should_stop=should_stop,
    )


def build_executor(
    cfg: Config,
    *,
    use: int | None = None,
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
            use=use,
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
    )
