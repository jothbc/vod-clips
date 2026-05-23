"""RMS-based audio peak detection on proxy WAV."""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from reels.models import WindowScore


def load_wav_mono(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wf:
        rate = wf.getframerate()
        n_channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    dtype = np.int16 if sampwidth == 2 else np.int8
    audio = np.frombuffer(raw, dtype=dtype).astype(np.float32)
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)
    audio /= np.iinfo(dtype).max
    return audio, rate


def compute_rms_windows(
    audio: np.ndarray,
    sample_rate: int,
    window_seconds: float,
    hop_seconds: float | None = None,
) -> list[tuple[float, float, float]]:
    """Return (start, end, rms) per window."""
    hop = hop_seconds or window_seconds
    win_samples = int(window_seconds * sample_rate)
    hop_samples = int(hop * sample_rate)
    if win_samples <= 0:
        return []

    results: list[tuple[float, float, float]] = []
    for start in range(0, len(audio) - win_samples + 1, hop_samples):
        chunk = audio[start : start + win_samples]
        rms = float(np.sqrt(np.mean(chunk**2) + 1e-12))
        t0 = start / sample_rate
        t1 = (start + win_samples) / sample_rate
        results.append((t0, t1, rms))
    return results


def normalize_scores(values: list[float]) -> list[float]:
    if not values:
        return []
    arr = np.array(values, dtype=np.float64)
    lo, hi = arr.min(), arr.max()
    if hi - lo < 1e-9:
        return [0.0] * len(values)
    return ((arr - lo) / (hi - lo)).tolist()


def compute_audio_scores(
    wav_path: Path,
    window_seconds: float,
    duration: float,
) -> dict[tuple[float, float], float]:
    """Map window (start, end) -> normalized audio score."""
    audio, rate = load_wav_mono(wav_path)
    windows = compute_rms_windows(audio, rate, window_seconds)
    if not windows:
        return {}

    rms_vals = [w[2] for w in windows]
    norm = normalize_scores(rms_vals)
    return {(w[0], w[1]): s for w, s in zip(windows, norm)}


def apply_silence_penalty(
    scores: dict[tuple[float, float], float],
    motion: dict[tuple[float, float], float],
    rms_threshold: float,
    motion_threshold: float,
    raw_rms: dict[tuple[float, float], float] | None = None,
) -> dict[tuple[float, float], float]:
    """Penalize windows with low audio and low motion (loot/menu/AFK)."""
    out: dict[tuple[float, float], float] = {}
    for key, score in scores.items():
        m = motion.get(key, 0.0)
        if raw_rms and key in raw_rms:
            if raw_rms[key] < rms_threshold and m < motion_threshold:
                out[key] = score * 0.1
                continue
        out[key] = score
    return out
