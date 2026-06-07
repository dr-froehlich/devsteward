"""The live-progress seam: ``run_claude`` must emit each stream-json event as it lands,
and the CLI printer must render the common event shapes. Guards the fix for the silent
``steward advance`` (no visible confirmation that anything is happening)."""

from devsteward.core.claude import Outcome, run_claude

# A stand-in for `claude`: ignores the appended -p/--output-format args and just prints
# the stream-json lines a real headless session would, one per line.
_FAKE_CLAUDE = (
    "import json\n"
    'print(json.dumps({"type": "system", "subtype": "init", "model": "x"}))\n'
    'print(json.dumps({"type": "assistant", "message": {"content": '
    '[{"type": "text", "text": "thinking"}, '
    '{"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}]}}))\n'
    'print(json.dumps({"type": "result", "subtype": "success", "result": "done"}))\n'
)


def test_run_claude_emits_events_live():
    seen: list[dict] = []
    res = run_claude(
        "/advance REQ-X design",
        argv_prefix=["python", "-c", _FAKE_CLAUDE],
        on_event=seen.append,
    )
    # Every parsed event reached the callback, in order, as it arrived.
    assert [e["type"] for e in seen] == ["system", "assistant", "result"]
    # …and the classification/extraction still work on the same run.
    assert res.outcome is Outcome.OK
    assert res.text.endswith("done")


def test_run_claude_silent_when_no_callback():
    # The default path stays byte-for-byte as before (no callback, full buffer).
    res = run_claude("cmd", argv_prefix=["python", "-c", _FAKE_CLAUDE])
    assert res.outcome is Outcome.OK
    assert len(res.raw_lines) == 3


def test_stream_printer_renders_text_and_tools(capsys):
    from devsteward.cli import _stream_printer

    emit = _stream_printer()
    emit({"type": "system", "subtype": "init", "model": "opus"})
    emit({"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}})
    emit({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": "/x/y.py"}}]}})
    emit({"type": "result", "subtype": "success", "duration_ms": 2000})

    err = capsys.readouterr().err
    assert "claude session started" in err
    assert "hello" in err
    assert "Read" in err and "/x/y.py" in err
    assert "claude session ended" in err
