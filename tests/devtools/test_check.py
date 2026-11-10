from flytrip.devtools.check import CheckStep, build_check_steps, run_check_steps


def test_fast_steps_skip_e2e_and_live():
    steps = build_check_steps(fast=True)
    assert [s.name for s in steps] == [
        "ruff format",
        "ruff lint",
        "mypy",
        "import-linter",
        "pytest",
    ]
    assert steps[0].argv == ["uv", "run", "ruff", "format", "--check", "."]
    assert steps[1].argv == ["uv", "run", "ruff", "check", "."]
    assert steps[2].argv == ["uv", "run", "mypy"]
    assert steps[3].argv == ["uv", "run", "lint-imports"]
    assert steps[4].argv == ["uv", "run", "pytest", "-q", "-m", "not live and not e2e"]


def test_full_steps_include_e2e():
    assert build_check_steps(fast=False)[-1].argv == ["uv", "run", "pytest", "-q", "-m", "not live"]


def test_run_counts_failures_and_runs_all_steps():
    codes, seen = iter([0, 1, 0]), []
    steps = [CheckStep("a", ["a"]), CheckStep("b", ["b"]), CheckStep("c", ["c"])]
    assert run_check_steps(steps, runner=lambda argv: seen.append(argv) or next(codes)) == 1
    assert seen == [["a"], ["b"], ["c"]]
