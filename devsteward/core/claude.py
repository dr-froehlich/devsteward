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


# Substrings that mark a usage/quota limit in Claude's headless output. Kept as a small
# table (ported from run_batch) so the adaptive gate can react instead of erroring.
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


def _classify(lines: list[dict], returncode: int | None, timed_out: bool) -> Outcome:
    if timed_out:
        return Outcome.TIMEOUT
    blob = json.dumps(lines).lower()
    if any(marker in blob for marker in _LIMIT_MARKERS):
        return Outcome.USAGE_LIMIT
    if returncode not in (0, None):
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


def run_claude(
    command: str,
    *,
    argv_prefix: list[str] | None = None,
    cwd: str | None = None,
    env: dict | None = None,
    timeout: float = 1800.0,
    unattended: bool = True,
    on_event: Callable[[dict], None] | None = None,
) -> Result:
    """Invoke ``claude -p <command>`` headless and classify the outcome.

    When ``unattended`` is set, ``DEVSTEWARD_UNATTENDED=1`` is exported so skills know to
    park-and-surface at forks instead of blocking on AskUserQuestion.

    ``on_event`` is called with each parsed stream-json event as it arrives, so an
    attended caller can render live progress instead of staring at a silent terminal.
    """
    argv = list(argv_prefix or ["claude"]) + [
        "-p",
        command,
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    run_env = dict(os.environ if env is None else env)
    if unattended:
        run_env["DEVSTEWARD_UNATTENDED"] = "1"

    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=run_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
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
