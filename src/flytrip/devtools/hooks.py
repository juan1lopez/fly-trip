"""Claude Code hooks: format after each edit and run the fast check on stop."""

import json
import subprocess
import sys
from typing import Any


def post_edit_commands(payload: dict[str, Any]) -> list[list[str]]:
    """Commands to run after an edit tool touched a file (only Python files)."""
    path = (payload.get("tool_input") or {}).get("file_path")
    if not isinstance(path, str) or not path.endswith(".py"):
        return []
    return [
        ["uv", "run", "ruff", "format", path],
        ["uv", "run", "ruff", "check", "--fix", path],
    ]


def should_run_stop_check(payload: dict[str, Any]) -> bool:
    """Skip the check when the stop hook already forced the agent to continue."""
    return not payload.get("stop_hook_active", False)


def summarize_failure(output: str, max_lines: int = 40) -> str:
    """Keep only the last lines of a failing command's output."""
    return "\n".join(output.splitlines()[-max_lines:])


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True, check=False)


def run_post_edit(payload: dict[str, Any]) -> int:
    last: subprocess.CompletedProcess[str] | None = None
    for argv in post_edit_commands(payload):
        last = _run(argv)
    if last is not None and last.returncode != 0:
        print(summarize_failure(last.stdout + last.stderr), file=sys.stderr)
        return 2
    return 0


def run_stop(payload: dict[str, Any]) -> int:
    if not should_run_stop_check(payload):
        return 0
    result = _run(["uv", "run", "fly", "check", "--fast"])
    if result.returncode != 0:
        print(summarize_failure(result.stdout + result.stderr), file=sys.stderr)
        return 2
    return 0


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("post-edit", "stop"):
        print("uso: python -m flytrip.devtools.hooks {post-edit|stop}", file=sys.stderr)
        return 1
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        payload = {}
    return run_post_edit(payload) if argv[0] == "post-edit" else run_stop(payload)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
