from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_claude_md_is_a_short_map():
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 100
    for needle in ["uv run fly check", "docs/architecture.md", "docs/sources/", "tests/fixtures/"]:
        assert needle in text


def test_agents_md_points_to_claude_md():
    assert "CLAUDE.md" in (ROOT / "AGENTS.md").read_text(encoding="utf-8")
