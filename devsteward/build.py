"""Assemble an :class:`Executor` from a project's config (profile, verifier, accounts)."""

from __future__ import annotations

from .config import Config
from .core.accounts import CswapAccountProvider, SingleAccountProvider
from .core.executor import Executor
from .core.verify import CommandVerifier
from .profiles.generic import GenericStepSource
from .profiles.req import ReqStepSource
from .profiles.req.verify import ReqVerifier


def build_step_source(cfg: Config):
    if cfg.profile == "generic":
        return GenericStepSource()
    return ReqStepSource(cfg.req_dir)


def build_verifier(cfg: Config):
    # The REQ profile gives the guarantee teeth at land (a land step must run real
    # acceptance tests); the generic profile keeps the plain run-named-tests verifier.
    if cfg.profile == "generic":
        return CommandVerifier(cwd=str(cfg.root))
    return ReqVerifier(cwd=str(cfg.root))


def build_accounts(cfg: Config, use: int | None = None):
    provider = (cfg.accounts or {}).get("provider", "cswap")
    if provider == "single":
        return SingleAccountProvider()
    return CswapAccountProvider(use=use)


def build_executor(cfg: Config, *, use: int | None = None, autocommit: bool = True) -> Executor:
    return Executor(
        root=cfg.root,
        source=build_step_source(cfg),
        verifier=build_verifier(cfg),
        accounts=build_accounts(cfg, use=use),
        autocommit=autocommit,
        permission_mode=(cfg.claude or {}).get("permission_mode", "dangerously-skip"),
        production_branch=cfg.production_branch,
    )
