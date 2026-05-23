"""Typer CLI: run, analyze, export."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from reels.config import AnalysisMode, load_config
from reels.export import export_all
from reels.highlights import load_highlights
from reels.pipeline import analyze_vod, resolve_output_dir, run_pipeline
from reels.probe import probe_video

app = typer.Typer(
    name="reels",
    help="Local Twitch VOD highlights → YouTube + Reels clips (100% local, Ollama VLM).",
)
console = Console()


@app.command()
def run(
    video: Path = typer.Argument(..., help="Path to Twitch VOD .mp4", exists=True),
    preset: str = typer.Option("twitch_gaming", "--preset", "-p", help="Config preset"),
    mode: AnalysisMode = typer.Option("auto", "--mode", "-m", help="auto|gaming|multimodal"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output directory"),
    max_clips: Optional[int] = typer.Option(None, "--max-clips", help="Max highlights"),
    resume: bool = typer.Option(False, "--resume", help="Resume from checkpoint"),
    use_nvenc: bool = typer.Option(False, "--use-nvenc", help="Use NVENC for export"),
    cleanup: bool = typer.Option(False, "--cleanup", help="Remove proxy after run"),
    ollama_model: Optional[str] = typer.Option(
        None, "--ollama-model", help="Override Ollama vision model"
    ),
) -> None:
    """Analyze VOD and export YouTube + Reels clips."""
    config = load_config(preset)
    config.analysis.mode = mode
    if max_clips is not None:
        config.clip.max_clips = max_clips
    if ollama_model:
        config.ollama.vision_model = ollama_model

    out = run_pipeline(
        video.resolve(),
        config,
        output,
        mode=mode,
        resume=resume,
        use_nvenc=use_nvenc,
        cleanup=cleanup,
    )
    console.print(f"[green]Done.[/green] Output: {out}")
    console.print(f"Highlights: {out / 'highlights.json'}")


@app.command()
def analyze(
    video: Path = typer.Argument(..., exists=True),
    preset: str = typer.Option("twitch_gaming", "--preset", "-p"),
    mode: AnalysisMode = typer.Option("auto", "--mode", "-m"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    max_clips: Optional[int] = typer.Option(None, "--max-clips"),
    resume: bool = typer.Option(False, "--resume"),
    ollama_model: Optional[str] = typer.Option(None, "--ollama-model"),
) -> None:
    """Analyze VOD only; write highlights.json."""
    config = load_config(preset)
    config.analysis.mode = mode
    if max_clips is not None:
        config.clip.max_clips = max_clips
    if ollama_model:
        config.ollama.vision_model = ollama_model

    out = resolve_output_dir(video.resolve(), output)
    doc = analyze_vod(video.resolve(), config, out, mode=mode, resume=resume)
    path = out / "highlights.json"
    console.print(f"[green]Wrote {len(doc.highlights)} highlights[/green] → {path}")
    for w in doc.warnings:
        console.print(f"[yellow]{w}[/yellow]")


@app.command("export")
def export_cmd(
    video: Path = typer.Argument(..., exists=True),
    highlights: Path = typer.Option(..., "--highlights", "-h", exists=True),
    preset: str = typer.Option("twitch_gaming", "--preset", "-p"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
    use_nvenc: bool = typer.Option(False, "--use-nvenc"),
) -> None:
    """Export clips from highlights.json using original VOD."""
    config = load_config(preset)
    doc = load_highlights(highlights)
    out = resolve_output_dir(video.resolve(), output or highlights.parent)
    info = probe_video(video)
    paths = export_all(
        video.resolve(),
        doc,
        out,
        config,
        use_nvenc=use_nvenc,
        source_width=info.width,
        source_height=info.height,
    )
    console.print(f"[green]Exported {len(paths)} files[/green] to {out}/youtube and {out}/reels")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind host (local only)"),
    port: int = typer.Option(8000, "--port", "-p"),
    reload: bool = typer.Option(False, "--reload", help="Dev auto-reload"),
) -> None:
    """Start web UI API server (use with `npm run dev` in web/)."""
    import uvicorn

    from reels.api.app import create_app
    from reels.logging_config import setup_logging

    log_path = setup_logging()
    console.print(f"[dim]Logs: {log_path}[/dim]")

    uvicorn.run(
        create_app(),
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    app()
