# Reels — Local Twitch VOD Highlights Pipeline

100% local CLI to turn long Twitch gameplay VODs into ranked highlights and export clips for **YouTube (16:9)** and **Instagram Reels (9:16)**. No cloud APIs.

Optimized for **RTX 3060 12GB**, **32GB RAM**, **i5-13400F**, and **Ollama** for vision-language scoring.

**Documentação detalhada (etapas do pipeline, consumo de CPU/GPU, como a IA escolhe os cortes):** [docs/GUIA_DO_PROJETO.md](docs/GUIA_DO_PROJETO.md)

## Features

- **Modes:** `auto` (heuristic + VLM with fallback), `gaming` (heuristic only), `multimodal` (Ollama on prefiltered windows)
- **Signals:** audio RMS peaks, motion score (OpenCV), PySceneDetect cuts, faster-whisper keywords
- **VLM:** Ollama `qwen2.5vl:7b` on candidate windows only (saves hours on 6h VODs)
- **Export:** FFmpeg cuts from **original** VOD; analysis uses source video + extracted WAV (no 720p re-encode by default)
- **Checkpoint:** `state.json` + per-window VLM JSON for `--resume`

## Requirements

### System

```bash
sudo apt update
sudo apt install -y ffmpeg
```

- **CUDA** for faster-whisper (optional; see WSL CUDA below)
- **Ollama** on host (Windows or Linux)

### Ollama models (one-time)

```bash
ollama pull qwen2.5vl:7b
ollama pull llama3.2:3b
```

Lighter alternatives: `llava:7b`, `moondream`.

### Python

```bash
cd /path/to/reels
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## WSL2 — Whisper CUDA (`libcublas.so.12`)

Your GPU is already visible via `nvidia-smi`. Python still needs **libcublas.so.12** for faster-whisper.

### Install (recommended, no sudo)

```bash
cd /path/to/reels
bash scripts/install_cuda_wsl.sh
# or: pip install -e ".[cuda]"
```

The reels app sets `LD_LIBRARY_PATH` automatically from those pip packages before Whisper runs.

Restart the server after install:

```bash
reels serve
```

### If CUDA still fails

The pipeline **falls back to CPU** automatically (slower). To force CPU:

```bash
export REELS_WHISPER_DEVICE=cpu
```

### Optional: full CUDA toolkit (sudo)

```bash
bash scripts/install_cuda_wsl_apt.sh
source ~/.bashrc
```

## Ollama (Windows app + reels no WSL)

O **reels** usa só o host do arquivo de config — **não lê** `OLLAMA_HOST` do terminal (evita conflito com o export do WSL→Windows).

Padrão em [`config/twitch_gaming.yaml`](config/twitch_gaming.yaml):

```yaml
ollama:
  host: http://127.0.0.1:11434
```

No WSL2, `127.0.0.1:11434` costuma encaminhar para o Ollama do **Windows** com o app aberto. Você continua usando o Ollama no Windows no dia a dia; o reels só fala com `localhost` por dentro do WSL.

Verifique antes de rodar o job:

```bash
curl http://127.0.0.1:11434/api/tags
```

Se não responder, abra o Ollama no Windows ou rode `ollama serve` no WSL.

**Não use** no terminal do reels:

```bash
export OLLAMA_HOST=http://$(grep nameserver ...)  # isso quebrava o projeto
```

Para mudar a URL, edite `ollama.host` no YAML (não variáveis de ambiente).

## Quick start — first Twitch VOD

1. Download your VOD as `.mp4` (e.g. with `yt-dlp` — outside this repo).
2. Ensure enough free disk for exports (with default `proxy.video_mode: audio_only`, no duplicate 720p file).
3. Run from the project root (so `config/` is found):

```bash
reels run ./my_vod.mp4 --preset twitch_gaming --mode auto
```

Output: `./my_vod_reels/` (or `-o output/vod/`)

- `highlights.json` — ranked moments
- `youtube/*.mp4` — 1920×1080
- `reels/*.mp4` — 1080×1920, max 90s

### Analyze only (no export)

```bash
# Fast — no Ollama
reels analyze ./my_vod.mp4 --mode gaming -o output/vod/

# Multimodal / auto
reels analyze ./my_vod.mp4 --preset twitch_gaming --mode auto --resume
```

### Export from existing highlights

```bash
reels export ./my_vod.mp4 --highlights output/vod/highlights.json --use-nvenc
```

### Useful flags

| Flag | Description |
|------|-------------|
| `--mode auto\|gaming\|multimodal` | Analysis strategy |
| `--preset twitch_gaming` | Gaming pads, keywords, NVENC default |
| `--max-clips 15` | Limit output clips |
| `--resume` | Continue after interrupt |
| `--use-nvenc` | GPU encode on RTX 3060 |
| `--cleanup` | Delete proxy WAV/MP4 after `run` |
| `--ollama-model qwen2.5vl:7b` | Override VLM |

## Expected runtime (order of magnitude)

~4h Twitch VOD @ 1080p on i5-13400F + RTX 3060, mode `auto`:

| Step | Time |
|------|------|
| Audio extract (proxy) | 2–8 min |
| Heuristic pass | 15–30 min |
| Whisper `medium` CUDA | 30–60 min |
| Ollama ~60–100 windows | 1–2 h |
| Export 15 clips × 2 formats | 10–20 min |

**Total ~2–4 h.** Use `gaming` mode to skip VLM (~1 h analysis).

**VRAM:** Whisper and Ollama run **sequentially** to avoid OOM on 12GB.

### Proxy / analysis video (`config/*.yaml` → `proxy.video_mode`)

| Mode | What it does |
|------|----------------|
| `audio_only` (default) | FFmpeg extracts 16 kHz WAV only; motion, scenes, and VLM read your **1080p source**. Skips the old 720p `libx264` pass (~10–20 min saved). |
| `copy` | Remux H.264 with `-c copy` (no re-encode) into `*_proxy.mp4` for faster seeks on some files. |
| `transcode` | Legacy: scale to `hardware.proxy_height` (720p) + `libx264` — smaller temp file, slower upfront CPU. |

Going to **1080p transcode** instead of 720p would **not** speed things up; it encodes more pixels. Prefer `audio_only` for typical Twitch MP4s.

## Project layout

```
config/          default.yaml, twitch_gaming.yaml, export_profiles.yaml
prompts/         VLM prompt templates
src/reels/       Python package (cli, pipeline, api, jobs)
web/             React + Vite UI
tests/           pytest (merge/dedupe, API)
```

## Web UI (local)

Browser UI: pick a **local VOD path**, watch live progress (SSE), preview YouTube/Reels clips.

### Terminal 1 — API

```bash
source .venv/bin/activate
# Ollama: use config host http://127.0.0.1:11434 (do not export OLLAMA_HOST here)
reels serve
```

### Terminal 2 — frontend (dev)

```bash
cd web
npm install
npm run dev
```

Open **http://127.0.0.1:5173**, paste your VOD path (e.g. `/mnt/c/Users/you/Videos/vod.mp4`), click **Start processing**.

Production (single port): `cd web && npm run build` then `reels serve` serves `web/dist` at http://127.0.0.1:8000.

| UI | API |
|----|-----|
| **Escolher vídeo** — upload com barra de progresso (qualquer tamanho, stream para disco) | `POST /api/upload` → `temp/vods/` |
| Start job | `POST /api/jobs` → saída em `temp/outputs/{job_id}/` |
| **Clear** — apaga VOD + clipes do job | `POST /api/jobs/{id}/clear` |

Ideal para **WSL**: o vídeo no Windows é enviado pelo navegador para `temp/` dentro do projeto Linux.
| Progress bar + phase stepper | `GET /api/jobs/{id}/events` (SSE) |
| Clip previews | `GET /api/jobs/{id}/clips` + `/media/...` |

Only one job runs at a time. Bind is **127.0.0.1** only (local machine).

## Logs (debugging failed jobs)

When a web job fails, check:

| File | Content |
|------|---------|
| `temp/logs/reels.log` | All backend errors (rotates on each `reels serve`) |
| `temp/outputs/<job_id>/job_error.log` | Traceback for that job |
| API | `GET /api/jobs/<job_id>/error-log` |

Terminal running `reels serve` also prints WARNING/ERROR lines.

## Development

```bash
pytest -q
reels analyze ./sample.mp4 --mode gaming
```

## Hardware notes (your PC)

- **Whisper:** `medium` + `float16` on CUDA — good balance on 3060
- **Export:** `--use-nvenc` or preset `twitch_gaming` (`h264_nvenc`, `-preset p5 -cq 20`)
- **Disk:** 20–50 GB VODs need hundreds of GB free for proxy + exports; use `--cleanup` when done

## Limitations

- No game API integration — highlights approximate **high intensity + streamer reaction**, not guaranteed kills
- VLM quality depends on Ollama model and HUD-heavy frames
- First run downloads Whisper weights

## License

MIT
