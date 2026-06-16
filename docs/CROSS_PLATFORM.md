# Cross-platform setup (Windows & Linux)

Action plan to run Reels natively on **Windows** or **Linux** (including WSL), with the same workflow: **check → install → start**.

## Goals

1. **OS-independent core** — Python package, FFmpeg, optional CUDA, Node for the web UI.
2. **Explicit environment checks** before long VOD jobs (fail fast with clear fixes).
3. **One install path per OS** that creates `.venv`, installs pip extras, and prints missing system tools.
4. **Start scripts** that pick the right venv binary (`bin/reels` vs `Scripts\reels.exe`).

## Current state

| Area | Linux / WSL | Windows native |
|------|-------------|----------------|
| Docs | `docs/WSL.md`, README (bash-first) | Not documented |
| Start | `start.sh`, `dev.sh` | — |
| CUDA helper | `scripts/install_cuda_wsl.sh` (LD_LIBRARY_PATH) | Needs PATH + pip `[cuda]` |
| `cuda_env.py` | `libcublas.so.12` | Needs `cublas64_12.dll` |
| GPU encode | NVENC via WSL `dxg` (unstable) | NVENC direct (preferred) |
| Ollama | Often on Windows host + WSL forward | `localhost:11434` native |

## Phases

### Phase 1 — Tooling (this PR)

- [x] `scripts/env_check.py` — cross-platform checker (Python, venv, FFmpeg, NVENC, Node, Ollama, CUDA, yt-dlp).
- [x] `scripts/install_deps.py` — venv + `pip install -e ".[dev,cuda,twitch]"`; print OS-specific system install hints.
- [x] Root wrappers: `check.sh` / `check.ps1`, `install.sh` / `install.ps1`.
- [x] `start.ps1`, `dev.ps1` — Windows equivalents of `start.sh` / `dev.sh`.
- [x] `cuda_env.py` — Windows DLL path (PATH) + Linux (LD_LIBRARY_PATH).
- [x] README section pointing to this doc.

**Usage**

```bash
# Linux / WSL / macOS
./check.sh
./install.sh
./dev.sh
```

```powershell
# Windows (PowerShell, project root)
.\check.ps1
.\install.ps1
.\dev.ps1
```

`check` exits `0` only when required items pass; optional items (Ollama, CUDA, yt-dlp) are warnings.

### Phase 2 — Windows-native validation

- [ ] Clone repo to `C:\Users\<you>\projects\reels` (avoid `\\wsl$\` paths for VOD I/O).
- [ ] Install system deps:
  - FFmpeg with NVENC (e.g. `winget install Gyan.FFmpeg` or full build from gyan.dev).
  - Node LTS (`winget install OpenJS.NodeJS.LTS`).
  - Ollama for Windows (already installed).
  - NVIDIA driver up to date.
- [ ] Run `.\install.ps1` then `.\check.ps1` until required checks pass.
- [ ] Run one short VOD: analyze → review → export 1 clip with **NVENC on**.
- [ ] Tune `config/twitch_gaming.yaml` for native GPU:
  - `ffmpeg_video_encoder: h264_nvenc`
  - `whisper_device: cuda`
  - `ffmpeg_threads: 6`–`8` (no WSL cap needed if not using WSL).

### Phase 3 — Config profiles per environment

- [ ] Add `config/windows_native.yaml` preset (NVENC on, CUDA on, no WSL thread paranoia) — optional merge over `twitch_gaming`.
- [ ] Add `config/wsl_safe.yaml` (libx264, lower threads) for users who stay on WSL.
- [ ] UI: detect or let user pick preset in JobForm (already has preset field).

### Phase 4 — Code hardening (OS-neutral)

- [ ] `export_clip`: optional fast seek (`-ss` before `-i`) for long VODs (both OS).
- [ ] Highlight preview: segment-only endpoint (avoid streaming 4 GB MP4) — both OS.
- [ ] Paths: keep `pathlib`; avoid hardcoded `/` in API responses.
- [ ] CI: GitHub Actions matrix `ubuntu-latest` + `windows-latest` running `python scripts/env_check.py` (mock/minimal).

### Phase 5 — Deprecate WSL-only assumptions

- [ ] Move WSL tips to `docs/WSL.md` only; README stays OS-neutral.
- [ ] Rename or alias `install_cuda_wsl.sh` → document as Linux-only; Windows uses `install.ps1` + `[cuda]` extra.
- [ ] Optional: `scripts/platform.py` used by CLI for venv re-exec on Windows (`Scripts\reels.exe`).

## What to install per OS

### Linux (Debian/Ubuntu/WSL)

```bash
sudo apt update
sudo apt install -y python3.10-venv ffmpeg
# Node: nvm or nodesource
curl -fsSL https://ollama.com/install.sh | sh   # optional, or Ollama on Windows
```

Then: `./install.sh`

### Windows

```powershell
winget install Python.Python.3.12
winget install Gyan.FFmpeg
winget install OpenJS.NodeJS.LTS
# Ollama: https://ollama.com/download/windows
# NVIDIA driver: GeForce Experience / nvidia.com
```

Then: `.\install.ps1`

## Decision: WSL vs Windows native

| Stay on WSL if… | Move to Windows native if… |
|-----------------|----------------------------|
| You live in Linux terminal / Cursor Remote WSL | You want **NVENC + Whisper CUDA** without `dxg` errors |
| Short VODs, CPU export is OK | Long Twitch VODs + batch export |
| Ollama already on Windows and forwarding works | You want one RAM pool and simpler GPU scheduling |

## Success criteria (Windows migration done)

1. `.\check.ps1` → all **required** green.
2. `.\dev.ps1` → UI at `:5173`, API at `:8000`.
3. Analyze + export 5 clips from a multi-GB VOD **with NVENC** without WSL reboot.
4. Same three commands work on Linux with `./check.sh` etc.

## Related files

```
check.sh / check.ps1          → scripts/env_check.py
install.sh / install.ps1      → scripts/install_deps.py
start.sh / start.ps1          → reels serve via .venv
dev.sh / dev.ps1              → API + Vite
scripts/reels_platform.py     → OS + venv path helpers
docs/WSL.md                   → WSL-only tuning (memory, pageReporting)
```
