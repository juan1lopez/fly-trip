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
