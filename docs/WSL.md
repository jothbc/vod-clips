# Running Reels on WSL (heavy VODs)

Long VODs (10 GB+) used to freeze WSL. The defaults now avoid the worst offenders,
but you should still cap how much of the host WSL is allowed to use.

## What changed in the pipeline

- **VLM dropped** from the highlights path — no Ollama VRAM spikes or frame extraction.
- **No full-VOD remux** — the original is served to the browser via HTTP range
  requests (`proxy.make_preview: false`). Set it to `true` only if your player can't
  seek the source.
- **Scene detection off by default** (`analysis.scene_detection: false`). When enabled
  it runs downscaled + fps-limited (`scale=-2:360, fps=4`) instead of full decode.
- **Chunked Whisper** (`hardware.whisper_chunk_minutes`) caps RAM on multi-hour audio
  and lets cancellation take effect between chunks.
- **Thread caps** (`hardware.ffmpeg_threads`, `hardware.opencv_threads`) keep heavy
  decode passes from saturating every core.
- **Cancel** for upload and analysis/export/render so a runaway job can be stopped.

## Limit WSL memory and CPU

Create or edit `C:\Users\<you>\.wslconfig` on Windows (not inside WSL):

```ini
[wsl2]
# Leave headroom for Windows + Ollama running on the host.
memory=24GB
swap=8GB
processors=8
# Reclaim cached memory back to Windows aggressively.
pageReporting=true
```

Then restart WSL from PowerShell:

```powershell
wsl --shutdown
```

Tune `memory`/`processors` to your machine (the reference rig is an i5-13400F /
RTX 3060 12GB / 32GB RAM). Keep `hardware.ffmpeg_threads` ≤ `processors`.

## If it still struggles

- Use a smaller Whisper model (`hardware.whisper_model: small` or `base`).
- Lower `hardware.whisper_chunk_minutes` (e.g. `10`) to cap peak RAM further.
- Force CPU transcription if CUDA libs are flaky: `export REELS_WHISPER_DEVICE=cpu`.
- For **Limpar vídeo**, the default LLM is `llama3.2:3b` (~2 GB VRAM). It is unloaded right
  after the review step. Avoid `qwen2.5:14b` on 12 GB GPUs. Disable LLM with
  `cleanup.use_llm: false` for silence-only cuts.
