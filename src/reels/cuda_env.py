"""Expose NVIDIA pip wheels (libcublas etc.) to the dynamic linker."""

from __future__ import annotations

import os
import site
from pathlib import Path


def _nvidia_lib_dirs() -> list[str]:
    dirs: list[str] = []
    search_roots: list[Path] = []
    for p in site.getsitepackages() + [site.getusersitepackages()]:
        if p:
            search_roots.append(Path(p))

    subpackages = ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc", "curand", "cusolver", "cusparse")
    for root in search_roots:
        nvidia = root / "nvidia"
        if not nvidia.is_dir():
            continue
        for sub in subpackages:
            lib = nvidia / sub / "lib"
            if lib.is_dir():
                dirs.append(str(lib.resolve()))
    return dirs


def setup_cuda_library_path() -> list[str]:
    """
    Prepend nvidia-* pip package lib dirs to LD_LIBRARY_PATH.
    Call before importing faster_whisper / ctranslate2 CUDA.
    """
    lib_dirs = _nvidia_lib_dirs()
    if not lib_dirs:
        return []

    existing = os.environ.get("LD_LIBRARY_PATH", "")
    parts = lib_dirs + ([existing] if existing else [])
    merged = ":".join(parts)
    os.environ["LD_LIBRARY_PATH"] = merged
    return lib_dirs


def cuda_libs_available() -> bool:
    """True if libcublas.so.12 is reachable via pip wheels or system paths."""
    for d in _nvidia_lib_dirs():
        if (Path(d) / "libcublas.so.12").is_file():
            return True
    return False
