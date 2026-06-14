"""Headless ``claude -p`` invocation with a watchdog and limit detection.

Generalized from the proven stream-json runner in
``examengineer/convert/run_batch_conversion.py`` + ``Theresa/run_batch.py``: invoke
``claude -p "<command>" --output-format stream-json``, pump the line stream through a
watchdog, classify the outcome (ok / usage-limit / error / timeout), and stop gracefully.

The invocation is injectable (``runner=``) so the executor and tests can drive the loop
without a real ``claude`` on PATH.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class Outcome(str, Enum):
    OK = "ok"
    USAGE_LIMIT = "usage-limit"
    ERROR = "error"
    TIMEOUT = "timeout"
    # The wrapper/launch never produced a real stream-json event and exited non-zero —
    # a broken account wrapper, a bad argv, or no ``claude`` on PATH. Distinct from a
    # mid-task ERROR so a launch that never happened is diagnosable, not a false "failed".
    LAUNCH_FAILURE = "launch-failure"


# Substrings that mark a usage/quota limit. Matched only against Claude's *runtime signal*
# (out-of-band/raw lines and an error terminal result) — never against assistant text or
# tool_result content, which can legitimately quote these words (e.g. a session that reads
# DevSteward's own quota code, or a plan about rate limiting). See _limit_signal_text /
# REQ-016. Kept as a small table (ported from run_batch) so the gate can react, not error.
_LIMIT_MARKERS = (
    "usage limit",
    "rate limit",
    "quota",
    "exceeded your",
    "5-hour limit",
    "claude usage limit reached",
)


@dataclass
class Result:
    outcome: Outcome
    text: str
    raw_lines: list[dict]
    returncode: int | None


# Headless `claude -p` has no interactive approver, so without a permission mode every
# Edit/Write/Bash stalls or is denied and the session does nothing (the silent no-op that
# made dogfooding "succeed" while producing empty commits). The default mirrors the proven
# reference runner (`run_batch.py`); a cautious consumer can soften it via config.
DEFAULT_PERMISSION_MODE = "dangerously-skip"

# Headless runs default to Opus at high effort (REQ-025 D8); a consumer overrides via
# `claude.model`/`claude.effort` config or the `--model`/`--effort` CLI flags. A falsy value
# (``None``/``""``) omits the flag, so attended callers and tests keep claude's own default.
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_EFFORT = "high"


def _permission_argv(mode: str | None) -> list[str]:
    """Map a permission-mode setting to claude CLI flags.

    ``"dangerously-skip"``/``"skip"`` → ``--dangerously-skip-permissions``; any claude
    ``--permission-mode`` value (``bypassPermissions``/``acceptEdits``/``plan``/``default``)
    → ``--permission-mode <value>``; ``None``/``""``/``"ask"`` → no flag (interactive
    default — used by tests and attended setups).
    """
    if not mode or mode == "ask":
        return []
    if mode in ("dangerously-skip", "skip"):
        return ["--dangerously-skip-permissions"]
    return ["--permission-mode", mode]


def _has_stream_event(lines: list[dict]) -> bool:
    """True if any captured line is a genuine parsed stream-json event.

    Non-JSON lines (e.g. a broken wrapper's stderr noise, merged into stdout) are stored
    as ``{"type": "raw", ...}`` by :func:`run_claude`; a run that produced only those, or
    nothing at all, never actually streamed from ``claude``.
    """
    return any(ev.get("type") != "raw" for ev in lines)


def _is_error_result(ev: dict) -> bool:
    """True for an *abnormal* terminal ``result`` event — ``is_error`` set, or a ``subtype``
    other than ``"success"``. A successful result carries the assistant's answer (which may
    mention 'usage limit'/'quota' for an honest reason) and must not be read as a limit."""
    if ev.get("type") != "result":
        return False
    if ev.get("is_error"):
        return True
    subtype = ev.get("subtype")
    return subtype is not None and subtype != "success"


def _limit_signal_text(lines: list[dict]) -> str:
    """The runtime's own out-of-band output, where a usage/rate limit actually surfaces:
    non-JSON ``raw`` lines (stderr/wrapper messages) and the text of an *error* terminal
    result. Deliberately excludes ``assistant`` text and ``tool_result`` content — a session
    that merely reads or writes files mentioning 'usage limit'/'quota' (e.g. DevSteward's own
    source) is not rate-limited. This is the REQ-016 content-vs-signal boundary."""
    parts: list[str] = []
    for ev in lines:
        if ev.get("type") == "raw":
            parts.append(str(ev.get("text", "")))
        elif _is_error_result(ev):
            parts.append(json.dumps(ev))
    return " ".join(parts).lower()


def _classify(lines: list[dict], returncode: int | None, timed_out: bool) -> Outcome:
    if timed_out:
        return Outcome.TIMEOUT
    signal = _limit_signal_text(lines)
    if any(marker in signal for marker in _LIMIT_MARKERS):
        return Outcome.USAGE_LIMIT
    if returncode not in (0, None):
        # A non-zero exit with no stream-json event means ``claude`` never really ran
        # (broken wrapper / bad argv / missing binary) — a launch failure, not ``claude``
        # erroring mid-task after it had begun streaming. This separates the
        # fictional-cswap fingerprint (a launch that never happened) from a real ERROR.
        if not _has_stream_event(lines):
            return Outcome.LAUNCH_FAILURE
        return Outcome.ERROR
    return Outcome.OK


def _extract_text(lines: list[dict]) -> str:
    """Pull the assistant's final text out of the stream-json events."""
    chunks: list[str] = []
    for ev in lines:
        if ev.get("type") == "result" and isinstance(ev.get("result"), str):
            chunks.append(ev["result"])
        elif ev.get("type") == "assistant":
            content = ev.get("message", {}).get("content", [])
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    chunks.append(block.get("text", ""))
    return "\n".join(c for c in chunks if c).strip()


def in_claude_session() -> bool:
    """True when this process is already running inside a Claude Code session.

    The harness exports ``CLAUDECODE=1`` for every session it drives. REQ-034 Decision 6
    forbids spawning Claude from within Claude, so the guided-validation **bring-up** path
    consults this and refuses when set — pointing the human at a plain terminal tab or the
    in-session skill instead. Forbidding the nested spawn dissolves the postmortem's
    Finding 4 (an in-session spawn forks the ambient session and wedges a pty) at the root.
    """
    return bool(os.environ.get("CLAUDECODE"))


def run_claude_interactive(
    command: str,
    *,
    argv_prefix: list[str] | None = None,
    cwd: str | None = None,
    env: dict | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> int:
    """Bring up an **interactive** ``claude`` session attached to the terminal and wait.

    The *editor pattern* (REQ-034 Decision 6) — how ``git`` brings up ``$EDITOR``: inherit
    the parent's TTY (no stdio redirection), run in the foreground, and ``wait`` for the
    human to finish. Deliberately **not** ``claude -p`` (no ``--output-format
    stream-json``), and **not** detached (no ``start_new_session``): the human drives this
    session live, so it must own the terminal. ``command`` is the initial prompt (e.g. a
    ``/system-test`` invocation); the session continues interactively from there.

    Returns the child's exit code. Callers MUST guard :func:`in_claude_session` first —
    Claude is never spawned from within Claude.
    """
    argv = list(argv_prefix or ["claude"]) + [command]
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    run_env = dict(os.environ if env is None else env)
    # Inherit the parent's stdin/stdout/stderr (the TTY) — the whole point of the editor
    # pattern. subprocess.run with no stdio kwargs inherits by default.
    completed = subprocess.run(argv, cwd=cwd, env=run_env)
    return completed.returncode


def run_claude(
    command: str,
    *,
    argv_prefix: list[str] | None = None,
    cwd: str | None = None,
    env: dict | None = None,
    timeout: float = 1800.0,
    unattended: bool = True,
    permission_mode: str | None = DEFAULT_PERMISSION_MODE,
    model: str | None = DEFAULT_MODEL,
    effort: str | None = DEFAULT_EFFORT,
    on_event: Callable[[dict], None] | None = None,
    on_spawn: Callable[["subprocess.Popen"], None] | None = None,
) -> Result:
    """Invoke ``claude -p <command>`` headless and classify the outcome.

    When ``unattended`` is set, ``DEVSTEWARD_UNATTENDED=1`` is exported so skills know to
    park-and-surface at forks instead of blocking on AskUserQuestion.

    ``permission_mode`` controls how the non-interactive session is allowed to act on the
    repo (see :func:`_permission_argv`); the default lets it edit files autonomously, which
    a headless run cannot do otherwise.

    ``on_event`` is called with each parsed stream-json event as it arrives, so an
    attended caller can render live progress instead of staring at a silent terminal.

    ``model``/``effort`` append ``--model``/``--effort`` flags (defaults Opus / high); a
    falsy value omits the flag. ``on_spawn`` is called with the live ``Popen`` right after
    launch so a driver can register the child with its :class:`~devsteward.core.stop.
    StopController` for two-level graceful stop — ``start_new_session=True`` puts ``claude``
    in its own process group so the engine's SIGINT is not forwarded to the child (REQ-025).
    """
    argv = list(argv_prefix or ["claude"]) + [
        "-p",
        command,
        "--output-format",
        "stream-json",
        "--verbose",
    ] + _permission_argv(permission_mode)
    if model:
        argv += ["--model", model]
    if effort:
        argv += ["--effort", effort]
    run_env = dict(os.environ if env is None else env)
    if unattended:
        run_env["DEVSTEWARD_UNATTENDED"] = "1"

    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=run_env,
        # A headless child must not inherit the driver's stdin: an attended `steward
        # validate` reads its sign-off answers there *after* the session (REQ-030), and
        # an inheriting child swallows them.
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    if on_spawn is not None:
        on_spawn(proc)
    lines: list[dict] = []
    deadline = time.monotonic() + timeout
    timed_out = False
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            if time.monotonic() > deadline:
                timed_out = True
                proc.terminate()
                break
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                ev = {"type": "raw", "text": line}
            lines.append(ev)
            if on_event is not None:
                on_event(ev)
        returncode = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        returncode = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
            returncode = proc.wait()

    outcome = _classify(lines, returncode, timed_out)
    return Result(outcome=outcome, text=_extract_text(lines), raw_lines=lines, returncode=returncode)
