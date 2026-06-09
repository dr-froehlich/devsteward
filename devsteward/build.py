"""Assemble an :class:`Executor` from a project's config (profile, verifier, accounts)."""

from __future__ import annotations

from .config import Config
from .core.accounts import CswapAccountProvider, SingleAccountProvider
from .core.executor import Executor
from .core.git import GitCli
from .core.verify import CommandVerifier
from .profiles.generic import GenericStepSource
from .profiles.req import ReqStepSource
from .profiles.req.checkpoint import ReqDoneFlipper
from .profiles.req.verify import ReqVerifier


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


def build_verifier(cfg: Config):
    # The REQ profile gives the guarantee teeth at land (a land step must run real
    # acceptance tests); the generic profile keeps the plain run-named-tests verifier.
    if cfg.profile == "generic":
        return CommandVerifier(cwd=str(cfg.root))
    return ReqVerifier(cwd=str(cfg.root))


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
        model=cfg.model if model is None else model,
        effort=cfg.effort if effort is None else effort,
        stop=stop,
        production_branch=cfg.production_branch,
        integration_branch=cfg.integration_branch,
        feature_branch_template=cfg.feature_branch_template,
        git=GitCli(cfg.root),
        on_verified=build_on_verified(cfg),
    )
