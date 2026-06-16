"""OS detection and venv path helpers (Windows + Linux)."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def os_family() -> str:
    """linux | windows | darwin | other"""
    name = sys.platform
    if name.startswith("linux"):
        return "linux"
    if name in ("win32", "cygwin"):
        return "windows"
    if name == "darwin":
        return "darwin"
    return "other"


def in_wsl() -> bool:
    if os_family() != "linux":
        return False
    try:
        with Path("/proc/version").open(encoding="utf-8", errors="ignore") as f:
            return "microsoft" in f.read().lower()
    except OSError:
        return False


def venv_dir(root: Path | None = None) -> Path:
    return (root or project_root()) / ".venv"


def venv_python(root: Path | None = None) -> Path:
    base = venv_dir(root)
    if os_family() == "windows":
        return base / "Scripts" / "python.exe"
    return base / "bin" / "python"


def venv_reels_cli(root: Path | None = None) -> Path:
    base = venv_dir(root)
    if os_family() == "windows":
        return base / "Scripts" / "reels.exe"
    return base / "bin" / "reels"


def venv_activate_hint(root: Path | None = None) -> str:
    base = venv_dir(root)
    if os_family() == "windows":
        return f"{base}\\Scripts\\Activate.ps1"
    return f"source {base}/bin/activate"


def which(cmd: str) -> str | None:
    return shutil.which(cmd)


def run_quiet(cmd: list[str], *, timeout: int = 30) -> tuple[int, str, str]:
    import subprocess

    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return r.returncode, (r.stdout or "").strip(), (r.stderr or "").strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def python_version_ok(minor: int = 10) -> tuple[bool, str]:
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    ok = (v.major, v.minor) >= (3, minor)
    return ok, ver


def machine_summary() -> dict[str, str]:
    return {
        "os": os_family(),
        "platform": platform.platform(),
        "wsl": str(in_wsl()).lower(),
        "python": sys.executable,
    }
