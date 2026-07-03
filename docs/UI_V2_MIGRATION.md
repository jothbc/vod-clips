# UI v2 Migration

Production-line UX (YouTube-style home + watch page + actions). Legacy tab UI remains at `/old`.

## Design direction (frontend-design skill)

All UI under `web/src/v2/` follows the [frontend-design](c:\Users\Jonathan\.cursor\skills\frontend-design\SKILL.md) skill:

| Aspect | Choice |
|--------|--------|
| Purpose | Local video studio — VOD → clips production line |
| Tone | Editorial dark refined studio (not generic streaming clone) |
| Display font | Fraunces |
| Body font | Instrument Sans |
| Palette | `--v2-bg` charcoal, `--v2-accent` warm amber, `--v2-teal` secondary |
| Motion | Staggered section reveals, carousel crossfade, card hover lift |
| Depth | Subtle grain overlay, card shadows, bordered panels |

Legacy UI in `web/src/legacy/` does **not** use frontend-design.

## Storage layout

```
temp/video/{slug}/
  original/source.mp4 + metadata.json
  transcript/segments.json (+ segments_original.json, audio_16k.wav)
  analysis/highlights.json
  clips/{clipSlug}/youtube.mp4, reels.mp4, meta.json
```

## API v2

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/v2/videos` | Home feed (originals) |
| GET | `/api/v2/clips` | Recent clips (carousel, rows) |
| GET | `/api/v2/gallery` | Hierarchical gallery tree |
| GET | `/api/v2/videos/{id}` | Video detail |
| GET | `/api/v2/videos/{id}/related` | Sidebar related items |
| POST | `/api/v2/videos/{id}/metadata` | Probe + Whisper (shared transcript) |
| GET/PUT | `/api/v2/videos/{id}/transcript` | Read/edit transcript |
| POST | `/api/v2/videos/{id}/analyze-highlights` | **202** — async `v2_analyze` job |
| GET | `/api/v2/videos/{id}/highlights` | Read `analysis/highlights.json` |
| POST | `/api/v2/videos/{id}/generate-clips` | **202** — async `v2_export_clips` job |
| GET | `/api/v2/system` | CUDA/GPU/CPU/RAM, models, active job |
| GET | `/api/jobs/{id}/events` | SSE progress (shared with legacy) |
| POST | `/api/jobs/{id}/cancel` | Cancel running job (no pause) |
| POST | `/api/v2/videos/{id}/cleanup` | Legacy cleanup job |
| POST | `/api/v2/videos/{id}/captions` | Legacy captions job |
| POST | `/api/v2/videos/{id}/publish` | Legacy publish job |
| GET | `/api/v2/media/{slug}/source.mp4` | Stream original |
| GET | `/api/v2/media/{parent}/clips/{clip}/{fmt}.mp4` | Stream clip |

Upload (`POST /api/upload`) and Twitch downloads write to `temp/video/{slug}/`.

## Feature migration checklist

| Legacy (`/old`) | v2 destination | Status |
|-----------------|----------------|--------|
| Galeria (upload/Twitch/VODs) | `GalleryModal` on home | Done |
| Gerar Reels tab | Action "Gerar clips" + modal | Done |
| Limpar video tab | Action "Remover silêncios" | Done (delegates to job) |
| Captions tab | Action "Gerar legendas" + transcript section | Done (delegates to job) |
| Publish tab | Action "Publicar" | Done (delegates to job) |
| FeatureSelector tabs | Home + Watch routes | Done |
| MediaSelectionContext pick | Gallery modal + direct nav | Done |
| ExportResolutionPicker | Inside GenerateClipsModal | Done |
| CleanupPanel (limpar temp) | Gallery / backlog | Partial |
| `resetSession` | Not used | Backlog |
| Presets YAML | Modal defaults + collapsible config | Partial |
| VLM / multimodal analysis | `/old` only | Backlog |
| Scene detection | Config only | Backlog |
| Keywords heuristic | Config only | Backlog |
| Resume job / `state.json` | Long VOD — port later | Backlog |
| Pickable clips flat list | Original ↔ clips relationship | Done |
| Full-width v2 layout | `#root` unconstrained; legacy uses `.legacy-root` | Done |
| System status panel | `GET /api/v2/system` + header "Sistema" drawer | Done |
| Generate clips manual flow | idle → analyze → review → export via jobs + SSE | Done |
| Job cancel (no pause) | `POST /api/jobs/{id}/cancel` + progress bar | Done |

## Backlog

- Search on home header
- Cleanup temp UI in gallery
- Word-level timestamps for karaoke captions
- Clip-level transcript subset copy
- Delete old `temp/vods/` and `temp/outputs/` after manual verification

## Frontend structure

```
web/src/
  legacy/LegacyApp.tsx     → /old
  v2/                      → / and /watch/:id
  router.tsx
  api/v2.ts
```

## Dev

```powershell
.\dev.ps1
```

Install frontend deps if needed: `cd web; npm install` (requires `react-router-dom`).

## Generate clips flow (v2)

1. Open modal — nothing runs automatically.
2. Click **Analisar highlights** → `POST analyze-highlights` returns `job_id`; progress via SSE.
3. On completion → `GET highlights` loads review list.
4. Select clips + formats → **Exportar** → `POST generate-clips` (202) with progress/cancel.
5. **Pause is not supported** — cancel stops between phases (Whisper chunking respects `whisper_chunk_minutes`).

## System status panel

Header button **Sistema** opens a drawer with ffmpeg/yt-dlp/Ollama/CUDA chips, CPU/RAM bars, GPU VRAM (when available), Whisper/Ollama model names, and the active job snapshot. Polls `/api/v2/system` every 5s when open, 30s when closed.
