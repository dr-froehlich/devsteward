"""The commit attribution trailer (REQ-091).

An engine-made commit **discloses** that a model assisted; it does not claim the model
co-authored. The distinction is not cosmetic:

* A **co-authorship** trailer asserts authorship. A model holds no copyright, signs no CLA and
  cannot certify a DCO, so the assertion is false whatever name sits in the field — and GitHub
  only parses that key at all when it carries a resolvable address, which was never more than
  a parser sop for an account that does not exist. (The retired key is named in REQ-091, not
  here: live engine source must not carry a string a reader could mistake for an instruction.)
* ``Assisted-by:`` states an observable fact about how the commit was produced. It takes no
  email, and the human stays the sole ``Author:``.

The shape is the Linux kernel's (``Documentation/process/coding-assistants.rst``, 2025-12-23):
``Assisted-by: AGENT_NAME:MODEL_VERSION``. OpenTelemetry, LLVM and Fedora converged on the
same key. The version half is verbatim the string in ``.devsteward/config.yaml``, so no
model identifier and no display-name table enters this module — REQ-090's rule holds here.

Where the version comes from, in order:

1. the model the engine itself resolved for the session it spawned — accurate by
   construction, since the engine chose it;
2. ``DEVSTEWARD_ASSISTED_BY``, exported by an attended session for a ``steward checkpoint``
   subprocess that cannot otherwise see what drives it (no model variable exists — only
   ``CLAUDECODE``, ``CLAUDE_CODE_SESSION_ID``, ``CLAUDE_EFFORT``, ``AI_AGENT``);
3. ``unknown``.

Step 3 is the load-bearing one. A gap is **stated**, never blanked: dropping the version to
leave a bare ``Assisted-by: Claude`` would rebuild the exact failure this replaces — it reads
as a claim while hiding whether the version was unknown or merely never plumbed. And a
missing identity never blocks a commit; stranding finished, verified work over a label is a
far worse outcome than an honest ``unknown`` in the log.
"""

from __future__ import annotations

import os
from typing import Mapping

#: The trailer key. Takes **no** email — see the module docstring.
TRAILER_KEY = "Assisted-by"

#: The agent half of ``AGENT_NAME:MODEL_VERSION``. A tool name, not a model identifier.
AGENT = "Claude"

#: The version half when no identity reached the engine. Said out loud, never omitted.
UNKNOWN = "unknown"

#: The env var an attended session exports so a ``steward`` subprocess can name its driver.
IDENTITY_ENV = "DEVSTEWARD_ASSISTED_BY"

#: Characters that disqualify a supplied identity outright. An address must never enter this
#: trailer (that was defect 3 of the retired form), and a newline would forge a trailer block.
#: A disqualified value falls back to ``unknown`` rather than being silently scrubbed into
#: something that looks authoritative — a malformed identity is precisely what unknown is for.
_FORBIDDEN = ("@", "<", ">", "\n", "\r")


def identity(spawn_model: str | None = None, env: Mapping[str, str] | None = None) -> str:
    """The ``AGENT:MODEL_VERSION`` value for this commit.

    ``spawn_model`` is the model the engine resolved for the session it spawned, or ``None``
    for an attended commit where nothing was spawned. Falls through to ``IDENTITY_ENV`` and
    then to ``AGENT:unknown``; never returns a bare agent name.
    """
    version = (spawn_model or "").strip()
    if not version:
        source = os.environ if env is None else env
        version = (source.get(IDENTITY_ENV) or "").strip()
    if not version or any(ch in version for ch in _FORBIDDEN):
        return f"{AGENT}:{UNKNOWN}"
    # A session may export either the bare model id or the full agent-qualified form; both
    # arrive at one shape so history stays uniform.
    return version if ":" in version else f"{AGENT}:{version}"


def trailer(spawn_model: str | None = None, env: Mapping[str, str] | None = None) -> str:
    """The full trailer line: ``Assisted-by: <agent>:<version>``.

    No example model id here or anywhere else in this module — REQ-090's rule covers prose as
    surely as code, and a "helpful" illustrative version string is exactly how the last one
    outlived its model by two generations."""
    return f"{TRAILER_KEY}: {identity(spawn_model, env)}"


def sign(
    message: str,
    *,
    spawn_model: str | None = None,
    enabled: bool = True,
    env: Mapping[str, str] | None = None,
) -> str:
    """``message`` with the attribution trailer appended, or untouched when disabled.

    ``enabled=False`` (``attribution_trailer: false`` in the project config) means *no*
    attribution trailer at all — not an empty one and not an ``unknown`` one. Some repos ban
    AI trailers by contributor policy, and complying must not require patching the engine.
    """
    if not enabled:
        return message
    return f"{message}\n\n{trailer(spawn_model, env)}"
