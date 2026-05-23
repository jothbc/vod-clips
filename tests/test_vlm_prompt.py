"""VLM prompt must not break on JSON braces in template."""

from pathlib import Path

from reels.vlm.ollama import _fill_prompt


def test_prompt_fill_no_keyerror():
    template = Path("prompts/twitch_highlight_window.txt").read_text(encoding="utf-8")
    filled = _fill_prompt(
        template,
        duration=30.5,
        start=100.0,
        end=130.5,
        transcript="test line",
    )
    assert '"score"' in filled
    assert "{duration}" not in filled
    assert "test line" in filled
