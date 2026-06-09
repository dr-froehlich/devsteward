"""The live-progress seam: ``run_claude`` must emit each stream-json event as it lands,
and the CLI printer must render the common event shapes. Guards the fix for the silent
``steward advance`` (no visible confirmation that anything is happening)."""

import sys

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
        argv_prefix=[sys.executable, "-c", _FAKE_CLAUDE],
        on_event=seen.append,
    )
    # Every parsed event reached the callback, in order, as it arrived.
    assert [e["type"] for e in seen] == ["system", "assistant", "result"]
    # …and the classification/extraction still work on the same run.
    assert res.outcome is Outcome.OK
    assert res.text.endswith("done")


def test_run_claude_silent_when_no_callback():
    # The default path stays byte-for-byte as before (no callback, full buffer).
    res = run_claude("cmd", argv_prefix=[sys.executable, "-c", _FAKE_CLAUDE])
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


def test_new_session_and_model_effort(monkeypatch):
    """REQ-025 AC8: run_claude spawns claude in its own session (so a parent SIGINT is not
    forwarded to the child) and passes --model/--effort defaulting to opus / high."""
    import json as _json

    from devsteward.core import claude as claude_mod

    captured = {}

    class _FakePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            captured["kwargs"] = kwargs
            self.stdout = iter(
                [_json.dumps({"type": "result", "subtype": "success", "result": "x"}) + "\n"]
            )
            self._done = False

        def wait(self, timeout=None):
            self._done = True
            return 0

        def poll(self):
            return 0 if self._done else None

        def kill(self):
            self._done = True

        def terminate(self):
            self._done = True

    monkeypatch.setattr(claude_mod.subprocess, "Popen", _FakePopen)
    spawned = []
    res = run_claude("/advance REQ-X build", on_spawn=spawned.append)

    assert res.outcome is Outcome.OK
    assert captured["kwargs"].get("start_new_session") is True
    argv = captured["argv"]
    assert argv[argv.index("--model") + 1] == "claude-opus-4-8"
    assert argv[argv.index("--effort") + 1] == "high"
    assert len(spawned) == 1  # the driver got the live child to register for graceful stop


def test_model_effort_omitted_when_falsy(monkeypatch):
    """A falsy model/effort omits the flag (attended callers / tests keep claude's default)."""
    import json as _json

    from devsteward.core import claude as claude_mod

    captured = {}

    class _FakePopen:
        def __init__(self, argv, **kwargs):
            captured["argv"] = argv
            self.stdout = iter(
                [_json.dumps({"type": "result", "subtype": "success", "result": "x"}) + "\n"]
            )
            self._done = False

        def wait(self, timeout=None):
            self._done = True
            return 0

        def poll(self):
            return 0 if self._done else None

        def kill(self):
            self._done = True

        def terminate(self):
            self._done = True

    monkeypatch.setattr(claude_mod.subprocess, "Popen", _FakePopen)
    run_claude("cmd", model=None, effort="")
    assert "--model" not in captured["argv"] and "--effort" not in captured["argv"]
