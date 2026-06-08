"""REQ-016 — usage-limit detection trusts the runtime signal, not echoed content.

``_classify`` used to serialize the *entire* stream-json and substring-match the limit
markers anywhere in it, so a session whose tool_result/assistant content quoted the words
"usage limit"/"rate limit"/"quota" (e.g. a step that reads DevSteward's own quota code) was
misread as a quota stop — the engine then reset a *completed* step to PENDING and discarded
the work (this dropped REQ-011:design). The fix scans only the runtime's own out-of-band
signal: raw/stderr lines and an *error* terminal result.
"""

from __future__ import annotations

from devsteward.core.accounts import SingleAccountProvider
from devsteward.core.claude import Outcome, Result, _classify, _extract_text
from devsteward.core.executor import Executor, RunOutcome
from devsteward.core.ledger import Ledger
from devsteward.core.model import Step, StepStatus
from devsteward.core.verify import CommandVerifier

from conftest import FakeRunner, ListStepSource, RecordingCommitter


def test_markers_in_content_are_not_a_limit():
    """A completed session whose only marker hits are in content it read or produced
    (tool_result file contents, assistant narration, the successful result text) is OK."""
    lines = [
        {"type": "system", "subtype": "init", "model": "opus"},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text":
             "Reading executor.py to see where RunOutcome.LIMIT / the usage limit lives."},
        ]}},
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "content":
             '_LIMIT_MARKERS = ("usage limit", "rate limit", "quota", "exceeded your")'},
        ]}},
        {"type": "result", "subtype": "success", "is_error": False,
         "result": "Wrote the plan; the guard sits next to the usage limit handling."},
    ]
    # The exact REQ-011:design fingerprint: markers everywhere except the runtime signal.
    assert _classify(lines, 0, False) is Outcome.OK


def test_runtime_limit_signal_still_detected():
    """A genuine limit — reported out-of-band (stderr → raw line) or as an error terminal
    result — is still USAGE_LIMIT, so the run stops and the step stays PENDING."""
    # (a) the CLI/wrapper prints the limit out of band (stderr, merged in as a raw line).
    raw = [{"type": "raw", "text": "Claude usage limit reached — resets at 6pm"}]
    assert _classify(raw, 1, False) is Outcome.USAGE_LIMIT

    # (b) the terminal result event is itself an error carrying the limit message.
    err = [
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "starting the build"}]}},
        {"type": "result", "subtype": "error_during_execution", "is_error": True,
         "result": "rate limit exceeded — please wait and retry"},
    ]
    assert _classify(err, 0, False) is Outcome.USAGE_LIMIT


def test_executor_no_false_limit_on_marker_content(project):
    """End to end: given the dropped-REQ-011 stream (markers only in read/produced content,
    a successful result), the executor verifies, commits, and advances to DONE — it does not
    reset the step to PENDING as the old whole-blob scan made it do."""
    lines = [
        {"type": "user", "message": {"content": [
            {"type": "tool_result", "content":
             '_LIMIT_MARKERS = ("usage limit", "rate limit", "quota")'},
        ]}},
        {"type": "result", "subtype": "success", "is_error": False,
         "result": "Done — added the guard beside the usage limit handling."},
    ]
    outcome = _classify(lines, 0, False)
    assert outcome is Outcome.OK  # the unit guarantee, restated at the boundary

    result = Result(outcome=outcome, text=_extract_text(lines), raw_lines=lines, returncode=0)
    step = Step(id="REQ-016:land", command="/advance REQ-016 land", verify=("true",))
    committer = RecordingCommitter()
    ex = Executor(
        root=project,
        source=ListStepSource([step]),
        verifier=CommandVerifier(cwd=str(project)),
        accounts=SingleAccountProvider(),
        runner=FakeRunner(default=result),
        committer=committer,
    )

    res = ex.run_step(step)
    assert res.outcome is RunOutcome.DONE
    assert committer.committed == ["REQ-016:land"]
    assert Ledger(project).status_of("REQ-016:land") is StepStatus.DONE
