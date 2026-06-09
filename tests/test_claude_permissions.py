"""REQ-014 — headless ``claude -p`` runs with a permission mode so it can actually edit.

A headless session has no interactive approver: without a permission flag every
Edit/Write/Bash stalls and the run silently does nothing (the no-op that let dogfooding
"succeed" with empty commits). These hermetic tests prove the flag is built into the
invocation and threaded from config through the executor; the real proof that edits now
land is the opt-in reality gate (REQ-013).
"""

from __future__ import annotations

import sys

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.claude import _permission_argv, run_claude
from devsteward.core.executor import Executor
from devsteward.core.model import Step
from devsteward.core.verify import CommandVerifier

from conftest import FakeRunner, ListStepSource, RecordingCommitter, ok_result

# A stand-in for `claude` that echoes the argv it was handed back as a stream-json result,
# so a test can assert which permission flag run_claude appended.
_ARGV_ECHO = (
    "import json, sys\n"
    'print(json.dumps({"type": "result", "subtype": "success", '
    '"result": " ".join(sys.argv[1:])}))\n'
)


def test_permission_argv_mapping():
    """AC1: the mode→flag mapping covers the autonomous, structured, and off cases."""
    assert _permission_argv("dangerously-skip") == ["--dangerously-skip-permissions"]
    assert _permission_argv("skip") == ["--dangerously-skip-permissions"]
    assert _permission_argv("bypassPermissions") == ["--permission-mode", "bypassPermissions"]
    assert _permission_argv("acceptEdits") == ["--permission-mode", "acceptEdits"]
    assert _permission_argv("ask") == []
    assert _permission_argv(None) == []
    assert _permission_argv("") == []


def test_run_claude_appends_permission_flag_by_default():
    """AC2: the default invocation carries --dangerously-skip-permissions; 'ask' carries none."""
    res = run_claude("/advance", argv_prefix=[sys.executable, "-c", _ARGV_ECHO])
    assert "--dangerously-skip-permissions" in res.text

    soft = run_claude("/advance", argv_prefix=[sys.executable, "-c", _ARGV_ECHO],
                      permission_mode="bypassPermissions")
    assert "--permission-mode bypassPermissions" in soft.text

    off = run_claude("/advance", argv_prefix=[sys.executable, "-c", _ARGV_ECHO],
                     permission_mode="ask")
    assert "--dangerously-skip-permissions" not in off.text
    assert "--permission-mode" not in off.text


def test_executor_threads_permission_mode_to_runner(project):
    """AC3: the executor passes its configured permission_mode into every runner call."""
    step = Step(id="REQ-X:build", command="/advance REQ-X build", verify=())
    runner = FakeRunner(default=ok_result())
    ex = Executor(
        root=project,
        source=ListStepSource([step]),
        verifier=CommandVerifier(cwd=str(project)),
        accounts=SingleAccountProvider(),
        runner=runner,
        committer=RecordingCommitter(),
        permission_mode="bypassPermissions",
    )
    ex.run_step(step)
    assert runner.calls[-1]["permission_mode"] == "bypassPermissions"
