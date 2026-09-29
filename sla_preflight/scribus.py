"""Headless Scribus: render pages and ask the Scripter about text layout.

Scribus runs a generated Python script (``scribus -g -ns -py script.py``),
under ``xvfb-run -a`` when no display is present (Scribus needs an X
display even with -g). Each run gets a throwaway HOME so user preferences
cannot change the result. When a font folder is given (argument or
$SLA_PREFLIGHT_FONTS_DIR), fontconfig is confined to it so renders do not
depend on the fonts installed on the machine.

Documents are opened read-only in spirit: scripts never save.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


class ScribusError(Exception):
    """Scribus is missing, timed out, or its script failed."""


def find_scribus() -> str | None:
    return os.environ.get("SCRIBUS_BIN") or shutil.which("scribus")


def _fonts_conf(fonts_dir: Path, tmp: Path) -> Path:
    conf = tmp / "fonts.conf"
    conf.write_text(
        '<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "fonts.dtd">'
        f"<fontconfig><dir>{fonts_dir.resolve()}</dir>"
        f"<cachedir>{tmp / 'fc-cache'}</cachedir></fontconfig>",
        encoding="utf-8",
    )
    return conf


def run_script(body: str, timeout: float = 120, fonts_dir: str | Path | None = None) -> dict:
    """Run ``body`` inside Scribus. The script gets ``RESULT`` (a dict) and
    ``scribus``; whatever it puts in RESULT is returned."""
    exe = find_scribus()
    if exe is None:
        raise ScribusError("Scribus not found (install it or set SCRIBUS_BIN)")
    fonts_dir = fonts_dir or os.environ.get("SLA_PREFLIGHT_FONTS_DIR")
    with tempfile.TemporaryDirectory(prefix="sla-preflight-scribus-") as t:
        tmp = Path(t)
        out = tmp / "result.json"
        script = tmp / "job.py"
        script.write_text(
            "import json, traceback\nimport scribus\nRESULT = {}\n"
            "try:\n"
            + "".join("    " + line + "\n" for line in body.strip().splitlines())
            + "except Exception:\n"
            "    RESULT['__error__'] = traceback.format_exc()\n"
            f"with open({str(out)!r}, 'w') as fh:\n"
            "    json.dump(RESULT, fh)\n",
            encoding="utf-8",
        )
        env = dict(os.environ, HOME=str(tmp), XDG_CONFIG_HOME=str(tmp / "config"),
                   XDG_RUNTIME_DIR=str(tmp))
        if fonts_dir:
            env["FONTCONFIG_FILE"] = str(_fonts_conf(Path(fonts_dir), tmp))
        cmd = [exe, "-g", "-ns", "-py", str(script)]
        if not os.environ.get("DISPLAY"):
            xvfb = shutil.which("xvfb-run")
            if xvfb is None:
                raise ScribusError("no display and xvfb-run not installed")
            cmd = [xvfb, "-a"] + cmd
        try:
            proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ScribusError(f"Scribus timed out after {timeout:.0f} s") from None
        if not out.is_file():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            raise ScribusError(f"Scribus script produced no result: {' | '.join(tail)}")
        result = json.loads(out.read_text(encoding="utf-8"))
    if "__error__" in result:
        raise ScribusError("Scribus script failed: " + result["__error__"].strip().splitlines()[-1])
    return result


def available_fonts(timeout: float = 120, fonts_dir: str | Path | None = None) -> list[str]:
    """Full names of the fonts Scribus can use (e.g. 'DejaVu Sans Book')."""
    body = 'RESULT["fonts"] = [f[0] for f in scribus.getXFontNames()]'
    return run_script(body, timeout, fonts_dir)["fonts"]


def font_files(timeout: float = 120, fonts_dir: str | Path | None = None) -> dict[str, str]:
    """Scribus font name -> the font file Scribus renders it with."""
    body = 'RESULT["files"] = {f[0]: f[5] for f in scribus.getXFontNames()}'
    return run_script(body, timeout, fonts_dir)["files"]


def text_overflows(sla_path: str | Path, timeout: float = 120,
                   fonts_dir: str | Path | None = None) -> dict[str, bool]:
    """Map each text frame's name to whether its text overflows. Groups are
    dissolved first (in memory, never saved) so grouped frames are seen.
    Frames without a name get the name Scribus gives them on load."""
    return layout_report(sla_path, timeout, fonts_dir)["overflows"]


def layout_report(sla_path: str | Path, timeout: float = 120,
                  fonts_dir: str | Path | None = None) -> dict:
    """``{"overflows": {name: bool}, "fonts": [available font names]}`` from
    one Scribus run."""
    p = Path(sla_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"SLA file not found: {p}")
    # read the font list before opening the document: once a document is
    # open, Scribus lists each missing font under its own name, mapped to a
    # substitute, which would hide the problem
    body = f"""
RESULT["fonts"] = [f[0] for f in scribus.getXFontNames()]
scribus.openDoc({str(p)!r})
over = {{}}
for page in range(1, scribus.pageCount() + 1):
    scribus.gotoPage(page)
    for _ in range(50):
        groups = [n for n in scribus.getAllObjects()
                  if scribus.getObjectType(n) == "Group"]
        if not groups:
            break
        for g in groups:
            scribus.unGroupObjects(g)
    for name in scribus.getAllObjects():
        if scribus.getObjectType(name) == "TextFrame":
            over[name] = bool(scribus.textOverflows(name))
RESULT["overflows"] = over
scribus.closeDoc()
"""
    return run_script(body, timeout, fonts_dir)


def render_png(sla_path: str | Path, out_png: str | Path, dpi: int = 150,
               timeout: float = 120, fonts_dir: str | Path | None = None) -> Path:
    """Render page 1 (trim size, no bleed) to a PNG at ``dpi``."""
    p = Path(sla_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"SLA file not found: {p}")
    out = Path(out_png).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    body = f"""
scribus.openDoc({str(p)!r})
scribus.gotoPage(1)
img = scribus.ImageExport()
img.type = "PNG"
img.dpi = {int(dpi)}
img.scale = 100
img.quality = 100
img.transparentBkgnd = False
RESULT["ok"] = bool(img.saveAs({str(out)!r}))
scribus.closeDoc()
"""
    res = run_script(body, timeout, fonts_dir)
    if not res.get("ok") or not out.is_file():
        raise ScribusError(f"Scribus could not render {p.name}")
    return out
