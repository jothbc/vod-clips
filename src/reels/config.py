"""Load and merge YAML configuration presets."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

AnalysisMode = Literal["auto", "gaming", "multimodal"]

def get_config_dir() -> Path:
    """Resolve config/ for editable install or when run from project root."""
    candidates = [
        Path(__file__).resolve().parents[2] / "config",
        Path.cwd() / "config",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    raise FileNotFoundError(
        "config/ not found. Run from the reels project root or set cwd accordingly."
    )


CONFIG_DIR = get_config_dir()
_PKG_ROOT = CONFIG_DIR.parent


class HardwareConfig(BaseModel):
    whisper_device: str = "cuda"
    whisper_model: str = "medium"
    whisper_compute_type: str = "float16"
    ffmpeg_video_encoder: str = "libx264"
    proxy_height: int = 720
    motion_sample_height: int = 480
    max_workers: int = 2


class OllamaConfig(BaseModel):
    # Default: localhost inside WSL (WSL2 forwards to Windows Ollama on the same port).
    # Reels ignores shell OLLAMA_HOST — change host here if needed.
    host: str = "http://127.0.0.1:11434"
    vision_model: str = "qwen2.5vl:7b"
    merge_model: str = "llama3.2:3b"
    timeout_seconds: int = 120

    def resolved_host(self) -> str:
        """Always use host from reels YAML; do not read OLLAMA_HOST from the shell."""
        return self.host.rstrip("/")


class HeuristicWeights(BaseModel):
    audio: float = 0.35
    motion: float = 0.30
    scene_density: float = 0.15
    keywords: float = 0.20


class HybridWeights(BaseModel):
    heuristic: float = 0.4
    vlm: float = 0.6


class AnalysisConfig(BaseModel):
    mode: AnalysisMode = "auto"
    window_seconds: int = 30
    prefilter_top_percent: float = 15.0
    max_vlm_windows: int = 80
    heuristic_weights: HeuristicWeights = Field(default_factory=HeuristicWeights)
    hybrid_weights: HybridWeights = Field(default_factory=HybridWeights)
    silence_rms_threshold: float = 0.02
    silence_motion_threshold: float = 0.05


class ClipConfig(BaseModel):
    pre_pad_seconds: float = 3.0
    post_pad_seconds: float = 5.0
    min_duration: float = 15.0
    max_duration_youtube: float = 600.0
    max_duration_reels: float = 90.0
    ideal_reels_duration: float = 45.0
    max_clips: int = 15
    merge_gap_seconds: float = 10.0
    dedupe_overlap_ratio: float = 0.5


class ProxyConfig(BaseModel):
    # audio_only: extract WAV only, analyze original (fastest for 1080p VODs).
    # transcode: scale to proxy_height + libx264 (legacy, uses more CPU upfront).
    # copy: remux video stream without re-encode when source is already H.264.
    video_mode: str = "audio_only"
    video_bitrate: str = "2M"
    audio_sample_rate: int = 16000
    min_free_disk_multiplier: float = 2.0


class PathsConfig(BaseModel):
    prompts_dir: str = "prompts"


class AppConfig(BaseModel):
    preset: str = "default"
    hardware: HardwareConfig = Field(default_factory=HardwareConfig)
    ollama: OllamaConfig = Field(default_factory=OllamaConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    clip: ClipConfig = Field(default_factory=ClipConfig)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    keywords: list[str] = Field(default_factory=list)
    paths: PathsConfig = Field(default_factory=PathsConfig)


class ExportProfile(BaseModel):
    width: int
    height: int
    aspect: str
    video_codec: str = "libx264"
    nvenc_codec: str = "h264_nvenc"
    nvenc_preset: str = "p5"
    nvenc_cq: int = 20
    crf: int = 23
    preset: str = "medium"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    max_duration: float = 600.0
    crop_mode: str | None = None


class ExportProfiles(BaseModel):
    youtube: ExportProfile
    reels: ExportProfile


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(preset: str = "default") -> AppConfig:
    default_path = CONFIG_DIR / "default.yaml"
    data = load_yaml(default_path)
    preset_path = CONFIG_DIR / f"{preset}.yaml"
    if preset_path.exists() and preset != "default":
        data = _deep_merge(data, load_yaml(preset_path))
    return AppConfig.model_validate(data)


def load_export_profiles() -> ExportProfiles:
    path = CONFIG_DIR / "export_profiles.yaml"
    return ExportProfiles.model_validate(load_yaml(path))


def prompts_path(config: AppConfig, name: str) -> Path:
    rel = Path(config.paths.prompts_dir)
    if rel.is_absolute():
        return rel / name
    return _PKG_ROOT / rel / name
