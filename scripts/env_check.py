#!/usr/bin/env python3
"""Cross-platform environment check for Reels (Windows, Linux, WSL)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Allow running before pip install -e .
_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parent
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from reels_platform import (  # noqa: E402
    in_wsl,
    machine_summary,
    os_family,
    project_root,
    python_version_ok,
    run_quiet,
    venv_python,
    venv_reels_cli,
    which,
)


@dataclass
class CheckResult:
    name: str
    status: str  # ok | warn | fail
    message: str
    required: bool = True
    fix: str = ""


@dataclass
class Report:
    summary: dict[str, str] = field(default_factory=dict)
    checks: list[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)

    @property
    def ok(self) -> bool:
        return all(c.status != "fail" for c in self.checks if c.required)

    def print_human(self) -> None:
        icons = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
        print(f"Reels environment check ({self.summary.get('os', '?')}"
              f"{', WSL' if self.summary.get('wsl') == 'true' else ''})")
        print("-" * 60)
        for c in self.checks:
            tag = icons.get(c.status, c.status)
            req = "required" if c.required else "optional"
            print(f"[{tag:4}] {c.name} ({req}): {c.message}")
            if c.status != "ok" and c.fix:
                print(f"       fix: {c.fix}")
        print("-" * 60)
        if self.ok:
            print("All required checks passed.")
        else:
            print("Some required checks failed. Run install script for your OS:")
            fam = self.summary.get("os", "linux")
            if fam == "windows":
                print("  .\\install.ps1")
            else:
                print("  ./install.sh")


def _check_python(report: Report) -> None:
    ok, ver = python_version_ok(10)
    report.add(
        CheckResult(
            "python",
            "ok" if ok else "fail",
            f"Python {ver}",
            fix="Install Python 3.10+ (winget install Python.Python.3.12 or apt python3.10-venv)",
        )
    )


def _check_venv(report: Report, root: Path) -> None:
    py = venv_python(root)
    if py.is_file():
        report.add(CheckResult("venv", "ok", str(py)))
    else:
        report.add(
            CheckResult(
                "venv",
                "fail",
                "missing .venv",
                fix="./install.sh or .\\install.ps1",
            )
        )


def _check_reels_package(report: Report, root: Path) -> None:
    py = venv_python(root)
    if not py.is_file():
        report.add(
            CheckResult("reels-package", "fail", "venv missing", fix="./install.sh")
        )
        return
    code, out, err = run_quiet([str(py), "-c", "import reels; print(reels.__file__)"])
    if code == 0:
        report.add(CheckResult("reels-package", "ok", out or "importable"))
    else:
        report.add(
            CheckResult(
                "reels-package",
                "fail",
                err or "not installed",
                fix=f'{py} -m pip install -e ".[dev,cuda,twitch]"',
            )
        )


def _check_cli(report: Report, root: Path) -> None:
    cli = venv_reels_cli(root)
    if cli.is_file():
        report.add(CheckResult("reels-cli", "ok", str(cli), required=False))
    else:
        report.add(
            CheckResult(
                "reels-cli",
                "warn",
                "reels entry point not found (pip install -e .)",
                required=False,
                fix="./install.sh",
            )
        )


def _check_ffmpeg(report: Report) -> None:
    ff = which("ffmpeg")
    if not ff:
        fam = os_family()
        fix = (
            "winget install Gyan.FFmpeg  (or add ffmpeg to PATH)"
            if fam == "windows"
            else "sudo apt install ffmpeg"
        )
        report.add(CheckResult("ffmpeg", "fail", "not in PATH", fix=fix))
        return
    code, out, _ = run_quiet([ff, "-version"])
    line = (out or "").splitlines()[0] if code == 0 else ff
    report.add(CheckResult("ffmpeg", "ok", line))


def _check_ffprobe(report: Report) -> None:
    fp = which("ffprobe")
    if fp:
        report.add(CheckResult("ffprobe", "ok", fp))
    else:
        report.add(
            CheckResult(
                "ffprobe",
                "fail",
                "not in PATH (usually bundled with ffmpeg)",
                fix="install full ffmpeg package",
            )
        )


def _check_nvenc(report: Report) -> None:
    ff = which("ffmpeg")
    if not ff:
        report.add(
            CheckResult("nvenc", "warn", "skipped (no ffmpeg)", required=False)
        )
        return
    code, out, err = run_quiet([ff, "-hide_banner", "-encoders"])
    text = f"{out}\n{err}"
    if "h264_nvenc" in text:
        note = "available"
        if in_wsl():
            note += " (WSL NVENC can be unstable; native Windows preferred)"
        report.add(CheckResult("nvenc", "ok", note, required=False))
    else:
        report.add(
            CheckResult(
                "nvenc",
                "warn",
                "h264_nvenc not listed — use libx264 or install NVIDIA ffmpeg build",
                required=False,
                fix="Windows: Gyan full build; Linux: ffmpeg with nvenc",
            )
        )


def _check_node(report: Report) -> None:
    node = which("node")
    npm = which("npm")
    if node and npm:
        _, ver, _ = run_quiet([node, "--version"])
        report.add(CheckResult("node", "ok", f"node {ver}", required=False))
    else:
        fam = os_family()
        fix = (
            "winget install OpenJS.NodeJS.LTS"
            if fam == "windows"
            else "install node via nvm or nodesource"
        )
        report.add(
            CheckResult(
                "node",
                "warn",
                "node/npm not in PATH (needed for web UI dev)",
                required=False,
                fix=fix,
            )
        )


def _check_ollama(report: Report) -> None:
    import urllib.error
    import urllib.request

    url = "http://127.0.0.1:11434/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            if resp.status == 200:
                report.add(
                    CheckResult(
                        "ollama",
                        "ok",
                        url,
                        required=False,
                    )
                )
                return
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        report.add(
            CheckResult(
                "ollama",
                "warn",
                f"not reachable ({e}) — only needed for Limpar vídeo LLM",
                required=False,
                fix="Install Ollama and run: ollama pull llama3.2:3b",
            )
        )


def _check_yt_dlp(report: Report, root: Path) -> None:
    py = venv_python(root)
    if py.is_file():
        code, _, _ = run_quiet([str(py), "-c", "import yt_dlp"])
        if code == 0:
            report.add(CheckResult("yt-dlp", "ok", "installed in venv", required=False))
            return
    if which("yt-dlp"):
        report.add(CheckResult("yt-dlp", "ok", "on PATH", required=False))
        return
    report.add(
        CheckResult(
            "yt-dlp",
            "warn",
            "not installed — Twitch download disabled",
            required=False,
            fix='pip install -e ".[twitch]"',
        )
    )


def _check_cuda(report: Report, root: Path) -> None:
    py = venv_python(root)
    if not py.is_file():
        report.add(CheckResult("cuda", "warn", "skipped (no venv)", required=False))
        return
    script = """
from reels.cuda_env import setup_cuda_library_path, cuda_libs_available
setup_cuda_library_path()
print(cuda_libs_available())
"""
    code, out, err = run_quiet([str(py), "-c", script])
    if code == 0 and out.strip() == "True":
        note = "Whisper CUDA libs available"
        if in_wsl():
            note += " (WSL CUDA uses dxg; native Windows often more stable)"
        report.add(CheckResult("cuda", "ok", note, required=False))
        return
    fam = os_family()
    fix = (
        f'{py} -m pip install -e ".[cuda]"'
        if fam == "windows"
        else f'{py} -m pip install -e ".[cuda]"  # or bash scripts/install_cuda_wsl.sh'
    )
    report.add(
        CheckResult(
            "cuda",
            "warn",
            "Whisper will fall back to CPU",
            required=False,
            fix=fix,
        )
    )


def _check_nvidia_smi(report: Report) -> None:
    smi = which("nvidia-smi")
    if not smi:
        report.add(
            CheckResult(
                "nvidia-driver",
                "warn",
                "nvidia-smi not found",
                required=False,
                fix="Install NVIDIA driver (Windows: GeForce; Linux: nvidia-driver)",
            )
        )
        return
    code, out, _ = run_quiet([smi, "--query-gpu=name,memory.total", "--format=csv,noheader"])
    line = out.splitlines()[0] if code == 0 and out else smi
    report.add(CheckResult("nvidia-driver", "ok", line, required=False))


def run_checks(*, json_out: bool = False) -> int:
    root = project_root()
    report = Report(summary=machine_summary())
    _check_python(report)
    _check_venv(report, root)
    _check_reels_package(report, root)
    _check_cli(report, root)
    _check_ffmpeg(report)
    _check_ffprobe(report)
    _check_nvenc(report)
    _check_node(report)
    _check_ollama(report)
    _check_yt_dlp(report, root)
    _check_cuda(report, root)
    _check_nvidia_smi(report)

    if json_out:
        payload = {
            "ok": report.ok,
            "summary": report.summary,
            "checks": [asdict(c) for c in report.checks],
        }
        print(json.dumps(payload, indent=2))
    else:
        report.print_human()
    return 0 if report.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Reels runtime environment")
    parser.add_argument("--json", action="store_true", help="Machine-readable output")
    args = parser.parse_args()
    return run_checks(json_out=args.json)


if __name__ == "__main__":
    raise SystemExit(main())
