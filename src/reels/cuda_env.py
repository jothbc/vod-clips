"""Expose NVIDIA pip wheels (libcublas etc.) to the dynamic linker."""

from __future__ import annotations

import os
import site
import sys
from pathlib import Path

_DLL_DIR_HANDLES: list[object] = []
_CUDA_PATH_CONFIGURED = False

_SUBPACKAGES = ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc", "curand", "cusolver", "cusparse")


def _nvidia_lib_dirs() -> list[str]:
    """Return nvidia-* wheel lib/bin directories for the current OS."""
    dirs: list[str] = []
    search_roots: list[Path] = []
    for p in site.getsitepackages() + [site.getusersitepackages()]:
        if p:
            search_roots.append(Path(p))

    subdir = "bin" if sys.platform == "win32" else "lib"
    for root in search_roots:
        nvidia = root / "nvidia"
        if not nvidia.is_dir():
            continue
        for sub in _SUBPACKAGES:
            lib = nvidia / sub / subdir
            if lib.is_dir():
                dirs.append(str(lib.resolve()))
    return dirs


def setup_cuda_library_path() -> list[str]:
    """
    Expose nvidia-* pip wheels to the loader.
    Call before importing faster_whisper / ctranslate2 CUDA.
    Idempotent: safe to call on every /api/v2/system poll.
    """
    global _CUDA_PATH_CONFIGURED

    lib_dirs = _nvidia_lib_dirs()
    if not lib_dirs:
        return []

    if _CUDA_PATH_CONFIGURED:
        return lib_dirs

    if sys.platform == "win32":
        for d in lib_dirs:
            try:
                _DLL_DIR_HANDLES.append(os.add_dll_directory(d))
            except (AttributeError, OSError):
                pass
        path_key = "PATH"
        existing = os.environ.get(path_key, "")
        missing = [d for d in lib_dirs if d not in existing.split(os.pathsep)]
        if missing:
            os.environ[path_key] = os.pathsep.join(missing + ([existing] if existing else []))
    else:
        existing = os.environ.get("LD_LIBRARY_PATH", "")
        missing = [d for d in lib_dirs if d not in existing.split(":")]
        if missing:
            os.environ["LD_LIBRARY_PATH"] = ":".join(missing + ([existing] if existing else []))

    _CUDA_PATH_CONFIGURED = True
    return lib_dirs


def cuda_libs_available() -> bool:
    """True if cuBLAS is reachable via pip wheels."""
    marker = "cublas64_12.dll" if sys.platform == "win32" else "libcublas.so.12"
    for d in _nvidia_lib_dirs():
        if (Path(d) / marker).is_file():
            return True
    return False
