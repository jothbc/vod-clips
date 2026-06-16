# Reels

Local video studio for long VODs. Pick a **feature** in the UI and the matching
workflow runs entirely on your machine — no cloud APIs.

Features:

1. **Gerar Reels** — score the VOD in time windows (audio, motion, speech, keywords),
   **list highlights for review**, then cut the selected ones from the **original**
   file into **YouTube (16:9)** and **Reels/TikTok (9:16)** clips.
2. **Limpar vídeo** — transcribe with word timestamps, cut **silences** between speech
   and **LLM-detected mistakes/retakes**, review the edit list, and render **one**
   corrected video in 16:9 and 9:16.
3. **Em breve** — placeholder for the next feature.

Highlights are **heuristic + Whisper only** by default (the VLM is off — it was the
main source of WSL freezes). See [docs/WSL.md](docs/WSL.md) for memory tips on heavy VODs.

Detailed pipeline guide (stages, CPU/GPU usage, how cuts are chosen): [docs/GUIA_DO_PROJETO.md](docs/GUIA_DO_PROJETO.md) *(Portuguese)*.

## Features

- **Pluggable workflows:** each top-level feature lives in `src/reels/features/` and is
  selected from the UI (`GET /api/features`); dispatched by `JobManager`.
- **Highlights:** audio peaks, motion (OpenCV), Whisper keywords (scene detection is
  off by default; VLM dropped from the default path).
- **Clean video:** silence EDL + local LLM (`llama3.2:3b`) mistake detection → single
  re-rendered video.
- **Review-then-render:** nothing heavy is encoded until you confirm (clips or final video).
- **Cancel everything:** Stop button for analysis/export/render, Cancel button for uploads.
- **Export:** FFmpeg from source MP4; optional NVENC.
- **Web UI:** upload VOD or download a Twitch URL, progress (SSE), review, gallery.
- **Stability:** opt-in preview remux, thread caps, chunked Whisper — tuned for WSL.

## Prerequisites

| Requirement | Notes |
|-------------|--------|
| **FFmpeg** | `sudo apt install ffmpeg` (or equivalent) |
| **Python 3.10+** | venv recommended |
| **Ollama** | Only for the **Limpar vídeo** LLM step (highlights no longer need it) |
| **NVIDIA GPU** | Optional — faster Whisper + NVENC export |

Pull the clean-video LLM once (only needed for **Limpar vídeo**):

```bash
ollama pull llama3.2:3b
```

## Installation (Windows or Linux)

Cross-platform guide and Windows migration plan: [docs/CROSS_PLATFORM.md](docs/CROSS_PLATFORM.md).

```bash
# Linux / WSL / macOS
./check.sh          # what is missing?
./install.sh        # .venv + pip extras
./dev.sh            # API + web UI
```

```powershell
# Windows (PowerShell, project root)
.\check.ps1
.\install.ps1
.\dev.ps1
```

Manual install:

```bash
git clone <repository-url>
cd reels
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,cuda,twitch]"
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

**Easiest (no `source .venv/bin/activate`):**

```bash
./dev.sh
```

Opens the API and Vite UI together. API only: `./start.sh` (same as `reels serve` using `.venv`).

**Manual (two terminals)**

```bash
source .venv/bin/activate
reels serve
```

```bash
cd web
npm install
npm run dev
```

If you run `reels` or `python3 -m reels.cli` from outside the venv, the CLI re-execs into `.venv` automatically when it finds the project root (set `REELS_NO_VENV_REEXEC=1` to disable).

Open http://127.0.0.1:5173 — upload an MP4, **download a Twitch VOD URL**, start a job, watch progress, preview clips.

**Twitch VOD download:** paste a URL like `https://www.twitch.tv/videos/1234567890` and click **Baixar da Twitch**. Requires [yt-dlp](https://github.com/yt-dlp/yt-dlp) (`pip install yt-dlp` or `pip install -e ".[twitch]"`). yt-dlp resolves the HLS master playlist (`.m3u8`) and merges all `.ts` segments into one MP4 in `temp/vods/`.

**Custom API port:** if you run `reels serve --port 8080` (not 8000), create `web/.env.local`:

```bash
VITE_API_BASE=http://127.0.0.1:8080
```

Restart `npm run dev` after changing env vars. See `web/.env.example`.

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

- `cleanup.yaml` — clean-video preset (silence thresholds, LLM model, formats)

Notable keys:

| Key | Effect |
|-----|--------|
| `proxy.video_mode` | `audio_only` (default): extract WAV only, analyze source video |
| `proxy.make_preview` | `false` (default): serve original via HTTP range; `true` remuxes a faststart preview |
| `analysis.scene_detection` | `false` (default): skip the full-decode scene pass (WSL-friendly) |
| `analysis.window_seconds` | Scoring window size (default 30s) |
| `hardware.ffmpeg_threads` / `opencv_threads` | Cap CPU threads so heavy passes don't freeze WSL (0 = auto) |
| `hardware.whisper_chunk_minutes` | Split Whisper into N-minute chunks (caps RAM, enables cancel) |
| `clip.pre_pad_seconds` / `post_pad_seconds` | Padding around each highlight |
| `cleanup.min_gap_seconds` / `pad_seconds` | Silence cut threshold + air kept around speech |
| `cleanup.llm_model` / `use_llm` | Clean-video LLM (`llama3.2:3b`) and toggle |
| `ollama.host` | Ollama API base URL |

## Project layout

```
config/             YAML presets (default, twitch_gaming, cleanup, export_profiles)
prompts/            LLM/VLM prompt templates (incl. cleanup_mistakes.txt)
docs/               Extended documentation (GUIA, WSL)
src/reels/          Python package (CLI, pipeline, API)
src/reels/features/ Pluggable workflows: base, registry, reels, cleanup
web/src/features/   Frontend views: ReelsView, CleanupView
tests/              pytest
```

## Development

```bash
pytest -q
```

## License

MIT
