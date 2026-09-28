"""Headless Scribus: render pages and ask the Scripter about text layout.

Scribus runs a generated Python script (``scribus -g -ns -py script.py``),
under ``xvfb-run -a`` when no display is present. Fonts are confined to a
font folder when one is given, so renders do not depend on the machine's
installed fonts.
"""
from __future__ import annotations

from pathlib import Path


class ScribusError(Exception):
    """Scribus is missing, timed out, or its script failed."""


def find_scribus() -> str | None:
    raise NotImplementedError


def text_overflows(sla_path: str | Path, timeout: float = 120) -> dict[str, bool]:
    """Map each named text frame to whether its text overflows."""
    raise NotImplementedError


def render_png(sla_path: str | Path, out_png: str | Path, dpi: int = 150,
               timeout: float = 120) -> Path:
    """Render page 1 to a PNG at ``dpi``."""
    raise NotImplementedError
