"""ASS subtitle generation and captioned video rendering."""

from __future__ import annotations

import subprocess
from pathlib import Path

from reels.caption_fonts import resolve_font_path
from reels.config import AppConfig, CaptionsConfig
from reels.export import require_ffmpeg
from reels.models import CaptionsDocument


def _ass_time(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _hex_to_ass_bgr(hex_color: str) -> str:
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return "&H00FFFFFF"
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"&H00{b:02X}{g:02X}{r:02X}"


def write_ass_file(
    doc: CaptionsDocument,
    ass_path: Path | str,
    *,
    video_width: int,
    video_height: int,
    font_family: str,
    config: CaptionsConfig,
) -> None:
    """Write an ASS file with karaoke \\k tags for word highlighting."""
    ass_path = Path(ass_path)
    ass_path.parent.mkdir(parents=True, exist_ok=True)

    font_size = max(24, int(video_height * config.font_size_ratio))
    margin_v = int(video_height * config.bottom_margin_ratio)
    primary = _hex_to_ass_bgr(config.primary_colour)
    highlight = _hex_to_ass_bgr(config.highlight_colour)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_width}
PlayResY: {video_height}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_family},{font_size},{primary},{highlight},&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{config.outline_size},0,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    lines = [header]
    for seg in doc.segments:
        start = _ass_time(seg.start)
        end = _ass_time(seg.end)
        if seg.words:
            parts: list[str] = []
            for word in seg.words:
                duration_cs = max(1, int(round((word.end - word.start) * 100)))
                text = str(word.word).replace("{", "\\{").replace("}", "\\}")
                parts.append(f"{{\\k{duration_cs}}}{text}")
            dialogue_text = " ".join(parts)
        else:
            dialogue_text = seg.text.replace("{", "\\{").replace("}", "\\}")
        lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{dialogue_text}\n"
        )

    ass_path.write_text("".join(lines), encoding="utf-8")


def render_captioned_video(
    source_video: Path,
    ass_path: Path,
    output_path: Path,
    *,
    font_id: str,
    config: AppConfig,
    use_nvenc: bool = False,
) -> None:
    """Burn ASS subtitles into the source video via ffmpeg."""
    require_ffmpeg()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    font_path = resolve_font_path(font_id)
    fonts_dir = font_path.parent if font_path else None

    ass_escaped = str(ass_path).replace("\\", "/").replace(":", "\\:")
    vf = f"ass='{ass_escaped}'"
    if fonts_dir:
        fonts_escaped = str(fonts_dir).replace("\\", "/").replace(":", "\\:")
        vf = f"ass='{ass_escaped}:fontsdir={fonts_escaped}'"

    codec = config.hardware.ffmpeg_video_encoder
    enc_args: list[str] = ["-crf", "23", "-preset", "medium"]
    if use_nvenc or codec == "h264_nvenc":
        codec = "h264_nvenc"
        enc_args = ["-preset", "p5", "-cq", "20"]

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_video),
        "-vf",
        vf,
        "-c:v",
        codec,
        *enc_args,
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Caption render failed: {result.stderr[-1500:]}")
