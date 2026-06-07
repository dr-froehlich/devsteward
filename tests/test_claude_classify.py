"""REQ-012 AC3 — ``_classify`` separates a *launch failure* (claude never started:
non-zero exit, zero stream-json events) from a genuine mid-task ERROR, so a broken
account wrapper or bad argv is diagnosable instead of an opaque false "failed"."""

from devsteward.core.claude import Outcome, run_claude


def test_launch_failure_distinct():
    # A wrapper that dies before claude ever emits a stream-json line: non-zero exit,
    # only stderr noise (merged into stdout, captured as a raw line). This is the
    # fictional-cswap fingerprint — a launch that never happened.
    launch = run_claude(
        "/advance REQ-X build",
        argv_prefix=[
            "python",
            "-c",
            "import sys; sys.stderr.write('error: unrecognized arguments: exec\\n'); "
            "sys.exit(2)",
        ],
    )
    assert launch.outcome is Outcome.LAUNCH_FAILURE
    assert launch.returncode == 2

    # claude itself erroring mid-task: it streamed a real stream-json event first, then
    # exited non-zero. That stays a plain ERROR — work began, then failed.
    midtask = run_claude(
        "/advance REQ-X build",
        argv_prefix=[
            "python",
            "-c",
            "import json, sys; "
            "print(json.dumps({'type': 'assistant', 'message': {'content': "
            "[{'type': 'text', 'text': 'working on it'}]}})); "
            "sys.exit(1)",
        ],
    )
    assert midtask.outcome is Outcome.ERROR

    # A clean run with no output and exit 0 is still OK (no false launch failure).
    fine = run_claude(
        "/advance REQ-X build",
        argv_prefix=["python", "-c", "pass"],
    )
    assert fine.outcome is Outcome.OK
