import io
import json
import subprocess
import sys

from flytrip.devtools import hooks
from flytrip.devtools.hooks import post_edit_commands, should_run_stop_check, summarize_failure


def test_post_edit_formats_python_files():
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "src/flytrip/core/models.py"}}
    assert post_edit_commands(payload) == [
        ["uv", "run", "ruff", "format", "src/flytrip/core/models.py"],
        ["uv", "run", "ruff", "check", "--fix", "src/flytrip/core/models.py"],
    ]


def test_post_edit_ignores_other_files():
    payload = {"tool_name": "Write", "tool_input": {"file_path": "docs/setup.md"}}
    assert post_edit_commands(payload) == []


def test_stop_check_skips_when_hook_already_active():
    assert should_run_stop_check({"stop_hook_active": True}) is False
    assert should_run_stop_check({"stop_hook_active": False}) is True


def test_summarize_keeps_last_lines():
    out = "\n".join(f"line {i}" for i in range(100))
    expected = [f"line {i}" for i in range(60, 100)]
    assert summarize_failure(out, max_lines=40).splitlines() == expected


def _completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, "")


def _fake_runner(monkeypatch, results):
    calls: list[list[str]] = []

    def fake(argv):
        calls.append(argv)
        return results.pop(0)

    monkeypatch.setattr(hooks, "_run", fake)
    return calls


EDIT = {"tool_name": "Edit", "tool_input": {"file_path": "a.py"}}


def test_run_post_edit_fails_with_ruff_errors(monkeypatch, capsys):
    calls = _fake_runner(monkeypatch, [_completed(0), _completed(1, "E501 too long")])
    assert hooks.run_post_edit(EDIT) == 2
    assert len(calls) == 2
    assert "E501 too long" in capsys.readouterr().err


def test_run_post_edit_clean_returns_zero(monkeypatch, capsys):
    _fake_runner(monkeypatch, [_completed(0), _completed(0)])
    assert hooks.run_post_edit(EDIT) == 0
    assert capsys.readouterr().err == ""


def test_run_stop_skips_check_when_hook_active(monkeypatch):
    calls = _fake_runner(monkeypatch, [])
    assert hooks.run_stop({"stop_hook_active": True}) == 0
    assert calls == []


def test_run_stop_reports_failure(monkeypatch, capsys):
    out = "\n".join(f"line {i}" for i in range(100))
    calls = _fake_runner(monkeypatch, [_completed(1, out)])
    assert hooks.run_stop({}) == 2
    assert calls == [["uv", "run", "fly", "check", "--fast"]]
    err = capsys.readouterr().err
    assert "line 99" in err
    assert "line 0\n" not in err


def test_run_stop_passes(monkeypatch):
    _fake_runner(monkeypatch, [_completed(0, "ok")])
    assert hooks.run_stop({}) == 0


def test_main_survives_invalid_json(monkeypatch):
    calls = _fake_runner(monkeypatch, [_completed(0)])
    monkeypatch.setattr(sys, "stdin", _stdin(b"not json"))
    assert hooks.main(["stop"]) == 0
    assert len(calls) == 1


def _stdin(raw: bytes, encoding: str = "cp1252") -> io.TextIOWrapper:
    """A stdin whose text layer uses the Windows code page, like a console would."""
    return io.TextIOWrapper(io.BytesIO(raw), encoding=encoding)


def test_main_reads_the_payload_as_utf8_whatever_the_console_encoding(monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr(hooks, "run_post_edit", lambda payload: seen.append(payload) or 0)
    raw = json.dumps({"tool_input": {"file_path": "señal.py"}}, ensure_ascii=False).encode()
    monkeypatch.setattr(sys, "stdin", _stdin(raw))
    assert hooks.main(["post-edit"]) == 0
    assert seen == [{"tool_input": {"file_path": "señal.py"}}]


def test_main_survives_bytes_that_are_not_utf8(monkeypatch):
    calls = _fake_runner(monkeypatch, [_completed(0)])
    monkeypatch.setattr(sys, "stdin", _stdin(bytes([0xFF, 0xFE, 0x7B])))
    assert hooks.main(["stop"]) == 0
    assert len(calls) == 1


def test_post_edit_ignores_python_files_outside_the_project(tmp_path):
    outside = {"tool_input": {"file_path": str(tmp_path / "scratch.py")}}
    assert post_edit_commands(outside) == []
    relative = {"cwd": str(tmp_path), "tool_input": {"file_path": "scratch.py"}}
    assert post_edit_commands(relative) == []
    escaping = {"tool_input": {"file_path": "../elsewhere/scratch.py"}}
    assert post_edit_commands(escaping) == []


def test_post_edit_formats_absolute_paths_inside_the_project():
    inside = str(hooks.PROJECT_ROOT / "src" / "flytrip" / "core" / "models.py")
    commands = post_edit_commands({"tool_input": {"file_path": inside}})
    assert commands[0] == ["uv", "run", "ruff", "format", inside]


def test_main_rejects_unknown_mode():
    assert hooks.main(["nope"]) == 1


def test_run_decodes_utf8_output():
    code = "import sys; sys.stdout.buffer.write('\\u2713 ok'.encode('utf-8'))"
    result = hooks._run([sys.executable, "-c", code])
    assert result.stdout == "✓ ok"
