"""File + console logging for reels backend."""

from __future__ import annotations

import logging
from pathlib import Path

from reels.storage import project_root

_CONFIGURED = False


def setup_logging(*, level: int = logging.INFO) -> Path:
    """Configure logs under project temp/logs/reels.log."""
    global _CONFIGURED
    log_dir = project_root() / "temp" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "reels.log"

    if _CONFIGURED:
        return log_file

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger("reels")
    root.setLevel(level)
    root.handlers.clear()

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(level)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    _CONFIGURED = True
    root.info("Logging initialized → %s", log_file)
    return log_file
