"""Development checks run by `fly check`."""

import subprocess
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class CheckStep:
    name: str
    argv: list[str]


def build_check_steps(fast: bool) -> list[CheckStep]:
    marker = "not live and not e2e" if fast else "not live"
    return [
        CheckStep("ruff format", ["uv", "run", "ruff", "format", "--check", "."]),
        CheckStep("ruff lint", ["uv", "run", "ruff", "check", "."]),
        CheckStep("mypy", ["uv", "run", "mypy"]),
        CheckStep("import-linter", ["uv", "run", "lint-imports"]),
        CheckStep("pytest", ["uv", "run", "pytest", "-q", "-m", marker]),
    ]


def subprocess_runner(argv: list[str]) -> int:
    return subprocess.run(argv, check=False).returncode


def run_check_steps(
    steps: list[CheckStep],
    runner: Callable[[list[str]], int] = subprocess_runner,
) -> int:
    """Run every step, print its result and return how many failed."""
    failures = 0
    for step in steps:
        if runner(step.argv) == 0:
            print(f"✓ {step.name}")
        else:
            print(f"✗ {step.name}")
            failures += 1
    return failures
