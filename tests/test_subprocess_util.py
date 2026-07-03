"""Tests for subprocess utility helpers."""

from reels.subprocess_util import explain_returncode, verify_tool


def test_explain_returncode_memory():
    msg = explain_returncode(0xC0000017)
    assert msg is not None
    assert "0xC0000017" in msg or "memory" in msg.lower()


def test_explain_returncode_ok():
    assert explain_returncode(0) is None


def test_verify_tool_ffmpeg():
    assert verify_tool("ffmpeg") is True
