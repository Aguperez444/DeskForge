#!/usr/bin/env python3
"""Backward-compatible launcher for DeskForge (formerly AutoJar)."""

from __future__ import annotations

from pathlib import Path
import sys

SRC_DIR = Path(__file__).resolve().parent / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from deskforge.cli.main import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
