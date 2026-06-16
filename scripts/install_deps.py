#!/usr/bin/env python3
"""Create .venv and install Reels pip dependencies (cross-platform)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from reels_platform import (  # noqa: E402
    in_wsl,
    os_family,
    project_root,
    venv_python,
    venv_reels_cli,
    which,
)


PIP_EXTRAS = "dev,cuda,twitch"


def _run(cmd: list[str], *, cwd: Path) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def _print_system_hints() -> None:
    fam = os_family()
    print()
    print("System dependencies (install manually if check fails):")
    if fam == "windows":
        print("  winget install Python.Python.3.12")
        print("  winget install Gyan.FFmpeg")
        print("  winget install OpenJS.NodeJS.LTS")
        print("  Ollama: https://ollama.com/download/windows")
        print("  NVIDIA driver: latest GeForce Game Ready")
    elif fam == "linux":
        print("  sudo apt update")
        print("  sudo apt install -y python3.10-venv ffmpeg")
        if in_wsl():
            print("  WSL tuning: docs/WSL.md (.wslconfig memory/processors)")
            print("  For native GPU on Windows, consider docs/CROSS_PLATFORM.md Phase 2")
    else:
        print("  Install Python 3.10+, FFmpeg, and Node via your package manager.")
    print()


def ensure_venv(root: Path, *, recreate: bool = False) -> Path:
    venv = root / ".venv"
    py = venv_python(root)
    if recreate and venv.exists():
        import shutil

        print(f"Removing {venv}…")
        shutil.rmtree(venv)

    if not py.is_file():
        print("Creating .venv…")
        base_py = which("python3") or which("python")
        if not base_py:
            print("ERROR: python3 not found on PATH", file=sys.stderr)
            sys.exit(1)
        if os_family() == "linux":
            # ensurepip may be missing without python3-venv package
            code = subprocess.run(
                [base_py, "-m", "venv", str(venv)],
                cwd=root,
                check=False,
            ).returncode
            if code != 0:
                print(
                    "ERROR: venv failed. On Ubuntu: sudo apt install python3.10-venv",
                    file=sys.stderr,
                )
                sys.exit(code)
        else:
            _run([base_py, "-m", "venv", str(venv)], cwd=root)
    return py


def pip_install(root: Path, py: Path, *, extras: str, no_cuda: bool) -> None:
    ex = extras
    if no_cuda:
        parts = [p for p in extras.split(",") if p.strip() != "cuda"]
        ex = ",".join(parts) or "dev"
    _run([str(py), "-m", "pip", "install", "-U", "pip"], cwd=root)
    _run([str(py), "-m", "pip", "install", "-e", f".[{ex}]"], cwd=root)


def npm_install_web(root: Path) -> None:
    web = root / "web"
    if not (web / "package.json").is_file():
        return
    if not which("npm"):
        print("WARN: npm not found — skip web/node_modules (install Node for UI dev)")
        return
    if (web / "node_modules").is_dir():
        print("web/node_modules already exists — run npm install in web/ to update")
        return
    _run(["npm", "install"], cwd=web)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install Reels Python deps into .venv")
    parser.add_argument("--recreate-venv", action="store_true")
    parser.add_argument("--no-cuda", action="store_true", help="Skip [cuda] extra")
    parser.add_argument("--extras", default=PIP_EXTRAS, help=f"pip extras (default: {PIP_EXTRAS})")
    parser.add_argument("--skip-npm", action="store_true")
    parser.add_argument("--check", action="store_true", help="Run env_check after install")
    args = parser.parse_args()

    root = project_root()
    os.chdir(root)

    _print_system_hints()
    py = ensure_venv(root, recreate=args.recreate_venv)
    pip_install(root, py, extras=args.extras, no_cuda=args.no_cuda)

    cli = venv_reels_cli(root)
    if cli.is_file():
        print(f"CLI ready: {cli}")
    else:
        print(f"Python ready: {py}")

    if not args.skip_npm:
        npm_install_web(root)

    print()
    print("Next:")
    fam = os_family()
    if fam == "windows":
        print("  .\\check.ps1")
        print("  .\\dev.ps1")
    else:
        print("  ./check.sh")
        print("  ./dev.sh")

    if args.check:
        print()
        check_script = root / "scripts" / "env_check.py"
        return subprocess.run([str(py), str(check_script)], cwd=root).returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
