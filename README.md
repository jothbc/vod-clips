# Reels

Local pipeline that turns long Twitch gameplay VODs into ranked highlights and exports clips for **YouTube (16:9)** and **Instagram Reels (9:16)**. Runs entirely on your machine — no cloud APIs.

**How it works:** the VOD is scored in time windows (audio, motion, scenes, speech, optional vision model). Top windows become `start`/`end` timestamps; FFmpeg cuts the **original** file at those times.

Detailed pipeline guide (stages, CPU/GPU usage, how cuts are chosen): [docs/GUIA_DO_PROJETO.md](docs/GUIA_DO_PROJETO.md) *(Portuguese)*.

## Features

- **Modes:** `auto` (heuristic + VLM, with fallback), `gaming` (heuristic only), `multimodal` (VLM on prefiltered windows)
- **Signals:** audio peaks, motion (OpenCV), scene cuts (PySceneDetect), Whisper keywords
- **VLM:** Ollama on candidate windows only (not the full VOD)
- **Export:** FFmpeg from source MP4; optional NVENC
- **Web UI:** upload VOD, progress (SSE), clip gallery
- **Resume:** checkpoints in `state.json` and per-window VLM JSON

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| **FFmpeg** | `sudo apt install ffmpeg` (or equivalent) |
| **Python 3.10+** | venv recommended |
| **Ollama** | For `auto` / `multimodal`; optional for `gaming` |
| **NVIDIA GPU** | Optional — faster Whisper + NVENC export |

Pull models once:

```bash
ollama pull qwen2.5vl:7b
ollama pull llama3.2:3b
```

## Installation

```bash
git clone <repository-url>
cd reels
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

**Whisper on GPU (optional):** install CUDA libs for faster-whisper:

```bash
pip install -e ".[cuda]"
# or: bash scripts/install_cuda_wsl.sh
```

If CUDA is unavailable, transcription falls back to CPU automatically. Force CPU: `export REELS_WHISPER_DEVICE=cpu`.

**Ollama URL:** set `ollama.host` in `config/twitch_gaming.yaml` (default `http://127.0.0.1:11434`). The app does **not** read `OLLAMA_HOST` from the shell. Verify with:

```bash
curl http://127.0.0.1:11434/api/tags
```

## Quick start (CLI)

From the project root (so `config/` resolves):

```bash
reels run ./my_vod.mp4 --preset twitch_gaming --mode auto
```

Output directory (default: `<vod_stem>_reels/`):

| Path | Description |
|------|-------------|
| `highlights.json` | Ranked moments with `start` / `end` (seconds) |
| `youtube/*.mp4` | 1920×1080 |
| `reels/*.mp4` | 1080×1920 (max duration in preset) |

```bash
# Analysis only (no export)
reels analyze ./my_vod.mp4 --preset twitch_gaming --mode gaming -o output/vod/

# Resume after interrupt
reels analyze ./my_vod.mp4 --mode auto --resume -o output/vod/

# Export from existing highlights.json
reels export ./my_vod.mp4 --highlights output/vod/highlights.json --use-nvenc
```

Common flags: `--mode`, `--preset`, `--max-clips`, `--resume`, `--use-nvenc`, `--cleanup`.

## Web UI

**Terminal 1 — API**

```bash
source .venv/bin/activate
reels serve
```

**Terminal 2 — frontend (development)**

```bash
cd web
npm install
npm run dev
```

Open http://127.0.0.1:5173 — upload an MP4, start a job, watch progress, preview clips.

**Production (single port):** `cd web && npm run build`, then `reels serve` serves the UI at http://127.0.0.1:8000.

Uploads and job outputs live under `temp/` (gitignored). Use **Clear** in the UI or `POST /api/jobs/{id}/clear` to remove temp files.

Only one job runs at a time. The server binds to `127.0.0.1` only.

### Logs

| Path | Purpose |
|------|---------|
| `temp/logs/reels.log` | Backend log |
| `temp/outputs/<job_id>/job_error.log` | Traceback for a failed job |

## Configuration

Presets live in `config/`:

- `twitch_gaming.yaml` — gaming keywords, clip limits, Ollama models
- `default.yaml` — baseline settings
- `export_profiles.yaml` — YouTube / Reels encode profiles

Notable keys:

| Key | Effect |
|-----|--------|
| `proxy.video_mode` | `audio_only` (default): extract WAV only, analyze source video |
| `analysis.window_seconds` | Scoring window size (default 30s) |
| `clip.pre_pad_seconds` / `post_pad_seconds` | Padding around each highlight |
| `ollama.host` | Ollama API base URL |

## Project layout

```
config/     YAML presets
prompts/    VLM prompt templates
docs/       Extended documentation
src/reels/  Python package (CLI, pipeline, API)
web/        React + Vite UI
tests/      pytest
```

## Development

```bash
pytest -q
```

## License

MIT
