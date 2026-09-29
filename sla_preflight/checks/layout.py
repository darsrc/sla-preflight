"""Layout rules for the facts panel area (deterministic): x-height measured
from the font file, placement relative to the panel, and row separators."""
from __future__ import annotations

import re
from functools import lru_cache

from ..context import Context
from ..registry import check
from ..result import CheckResult, Finding, finalize
from ..scribus import font_files
from ..sla import Frame, pt_to_in
from ._common import (
    CheckInputError, box_in, label, matches, printing_leaves, r6, schematic_crop, with_aliases,
)

DOT_LEADER = re.compile(r"\.{3,}|…")


# ---------------------------------------------------------------- x-height
@lru_cache(maxsize=64)
def glyph_height(path: str, char: str) -> tuple[float, float, float]:
    """(ink height, yMin, yMax) of ``char`` in em units (1.0 = font size),
    from the glyph outline in the font file."""
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib import TTFont

    font = TTFont(path, fontNumber=0, lazy=True)
    upem = font["head"].unitsPerEm
    glyph = font.getBestCmap().get(ord(char))
    if glyph is None:
        raise CheckInputError(f"font file {path} has no glyph for {char!r}")
    gs = font.getGlyphSet()
    pen = BoundsPen(gs)
    gs[glyph].draw(pen)
    if pen.bounds is None:
        raise CheckInputError(f"glyph {char!r} in {path} is empty")
    _, y0, _, y1 = pen.bounds
    return (y1 - y0) / upem, y0 / upem, y1 / upem


@check(
    "min_x_height",
    category="geometry",
    description="Lowercase x-height, measured on the actual font file, meets a minimum in inches.",
    rules=("min_x_height",),
    explain=(
        "For every text run in the rule's frames, finds the font file Scribus renders it with, "
        "measures the ink height of the reference glyph (min_x_height.glyph, default 'o', "
        "overshoot included) from its outline, and scales it by the run's point size and "
        "vertical scaling: height_in = glyph_em x size_pt x scale_v / 72. Reports each "
        "frame/font/size under min_in. Needs Scribus to map font names to files; errors "
        "when a font is missing."
    ),
    fix="Raise the type size (or use a font with a taller x-height) in the reported frame.",
)
def min_x_height(ctx: Context) -> CheckResult:
    doc = ctx.doc
    rules = ctx.rules.all("min_x_height")
    if "font_files" not in ctx.cache:
        ctx.cache["font_files"] = font_files(fonts_dir=ctx.options.get("fonts_dir"))
    files = ctx.cache["font_files"]
    findings: list[Finding] = []
    for rule in rules:
        min_in = float(rule["min_in"])
        char = str(rule.get("glyph", "o"))
        scope = with_aliases(ctx, rule.get("frames") or [])
        for f in printing_leaves(doc):
            if not f.is_text or (scope and not matches(f.name, scope)):
                continue
            seen = set()
            for run in f.runs:
                if not run.text.strip():
                    continue
                key = (run.font, run.size_pt, run.scale_v)
                if key in seen:
                    continue
                seen.add(key)
                path = files.get(run.font)
                if path is None:
                    raise CheckInputError(
                        f"font {run.font!r} (in {label(f)!r}) is not available to Scribus, so "
                        "its x-height cannot be measured; install it or use --fonts-dir")
                em, _, _ = glyph_height(path, char)
                h_in = em * run.size_pt * (run.scale_v / 100.0) / 72.0
                if h_in >= min_in - 1e-9:
                    continue
                findings.append(Finding.from_rule(
                    rule, label(f),
                    measured={"x_height_in": r6(h_in), "glyph": char, "size_pt": run.size_pt,
                              "scale_v_pct": run.scale_v, "font": run.font,
                              "glyph_height_em": round(em, 4), "text": run.text[:40]},
                    threshold={"min_in": min_in},
                    message=f"x-height of {run.font} at {run.size_pt:g} pt in {label(f)!r} is "
                            f"{h_in:.4f} in, under {min_in} in.",
                ))
    names = sorted({f.object for f in findings})
    return finalize(
        "min_x_height", "deterministic", findings, rules,
        "All measured x-heights meet the minimum.",
        f"x-height below the minimum in: {', '.join(names)}.",
    )


# --------------------------------------------------------------- placement
def _union(frames: list[Frame]):
    boxes = [f.bbox() for f in frames]
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _find(ctx: Context, names: list[str]) -> list[Frame]:
    pats = with_aliases(ctx, names)
    return [f for f in printing_leaves(ctx.doc) if matches(f.name, pats)]


@check(
    "element_placement",
    category="content",
    description="A frame sits immediately below, or immediately to the right of, a reference panel.",
    rules=("element_placement",),
    explain=(
        "The panel box is the union of the frames in element_placement.panel. The frame "
        "(element_placement.frame) must start at or after the panel's bottom edge, within "
        "max_gap_in, and overlap it horizontally ('below'); or start at or after the panel's "
        "right edge, within max_gap_in, and overlap it vertically ('right'). 'positions' "
        "lists which of these are allowed."
    ),
    fix="Move the frame directly under the panel or directly to its right, within the allowed gap.",
)
def element_placement(ctx: Context) -> CheckResult:
    rules = ctx.rules.all("element_placement")
    findings: list[Finding] = []
    for rule in rules:
        name = rule["frame"]
        targets = _find(ctx, [name])
        panel = _find(ctx, list(rule.get("panel") or []))
        if not targets:
            raise CheckInputError(f"frame {name!r} not found; cannot check its placement")
        if not panel:
            raise CheckInputError(f"panel frames {rule.get('panel')} not found")
        allowed = list(rule.get("positions") or ["below", "right"])
        gap_max = float(rule.get("max_gap_in", 0.125)) * 72
        tol = 0.001 * 72
        px0, py0, px1, py1 = _union(panel)
        x0, y0, x1, y1 = _union(targets)
        gap_below, gap_right = y0 - py1, x0 - px1
        ok = {
            "below": -tol <= gap_below <= gap_max and min(x1, px1) - max(x0, px0) > tol,
            "right": -tol <= gap_right <= gap_max and min(y1, py1) - max(y0, py0) > tol,
        }
        if any(ok[p] for p in allowed if p in ok):
            continue
        f = Finding.from_rule(
            rule, name,
            measured={"gap_below_panel_in": r6(pt_to_in(gap_below)),
                      "gap_right_of_panel_in": r6(pt_to_in(gap_right)),
                      "frame_box_in": box_in((x0, y0, x1, y1)),
                      "panel_box_in": box_in((px0, py0, px1, py1))},
            threshold={"positions": allowed, "max_gap_in": rule.get("max_gap_in", 0.125)},
            message=f"{name!r} is not immediately {' or '.join(allowed)} the panel "
                    f"({', '.join(sorted({p.name for p in panel}))}).",
        )
        f.evidence["crop"] = schematic_crop(ctx, "element_placement", name, targets, panel)
        findings.append(f)
    return finalize(
        "element_placement", "deterministic", findings, rules,
        "Placement relative to the panel is correct.",
        findings[0].message if findings else "",
    )


# ---------------------------------------------------------- row separators
def _paragraphs(ctx: Context, f: Frame) -> list[list]:
    """Non-empty paragraphs of a frame's story, as lists of runs."""
    runs = ctx.doc.chain_head(f).runs
    paras, cur = [], []
    for r in runs:
        if r.text == "\n":
            paras.append(cur)
            cur = []
        else:
            cur.append(r)
    paras.append(cur)
    return [p for p in paras if "".join(r.text for r in p).strip()]


def _dotted(runs) -> bool:
    text = "".join(r.text for r in runs)
    return bool(DOT_LEADER.search(text)) or any(
        r.text == "\t" and r.tab_fill and r.tab_fill.strip() == "." for r in runs)


def _rules_between(shapes: list[Frame], xspan, y_lo: float, y_hi: float, min_frac: float):
    x0, x1 = xspan
    need = min_frac * (x1 - x0)
    out = []
    for s in shapes:
        b = s.bbox()
        cy = (b[1] + b[3]) / 2
        if y_lo <= cy <= y_hi and min(b[2], x1) - max(b[0], x0) >= need:
            out.append(s)
    return out


@check(
    "facts_row_separators",
    category="content",
    description="Facts rows are separated by hairlines, or by dot leaders where allowed.",
    rules=("facts_row_separators",),
    explain=(
        "Rows are the frames matching facts_row_separators.rows_frames (one row per frame) or, "
        "when a single frame matches, its non-empty paragraphs. A hairline is a non-text shape "
        "no taller than max_rule_height_in that spans at least min_span_fraction of the rows' "
        "width. With several row frames, each gap between consecutive rows needs one; in a "
        "single frame, there must be at least rows - 1 inside it. When dot_leaders_allowed is "
        "true, rows that all carry dot leaders (a tab with a '.' leader, or '...' / '…' "
        "in the text) also pass."
    ),
    fix="Add a hairline between each pair of facts rows (or dot leaders, where allowed).",
)
def facts_row_separators(ctx: Context) -> CheckResult:
    rules = ctx.rules.all("facts_row_separators")
    findings: list[Finding] = []
    for rule in rules:
        rows_frames = sorted((f for f in _find(ctx, list(rule["rows_frames"])) if f.is_text),
                             key=lambda f: (f.page or 0, f.bbox()[1]))
        if not rows_frames:
            raise CheckInputError(f"no facts row frames match {rule['rows_frames']}")
        max_h = float(rule.get("max_rule_height_in", 0.02)) * 72
        frac = float(rule.get("min_span_fraction", 0.8))
        page = rows_frames[0].page
        shapes = [s for s in printing_leaves(ctx.doc)
                  if not s.is_text and s.page == page and s.kind != "image"
                  and s.bbox()[3] - s.bbox()[1] <= max_h]
        if len(rows_frames) > 1:
            rows = [f.runs for f in rows_frames]
            gaps_missing = []
            for a, b in zip(rows_frames, rows_frames[1:]):
                ax0, _, ax1, ay1 = a.bbox()
                bx0, by0, bx1, _ = b.bbox()
                span = (max(ax0, bx0), min(ax1, bx1))
                tol = 0.01 * 72
                if not _rules_between(shapes, span, ay1 - tol, by0 + tol, frac):
                    gaps_missing.append(f"{label(a)} / {label(b)}")
            hairlines_ok = not gaps_missing
            found = len(rows_frames) - 1 - len(gaps_missing)
        else:
            f = rows_frames[0]
            rows = _paragraphs(ctx, f)
            x0, y0, x1, y1 = f.bbox()
            found = len(_rules_between(shapes, (x0, x1), y0, y1, frac))
            hairlines_ok = found >= len(rows) - 1
            gaps_missing = []
        dotted = sum(1 for r in rows if _dotted(r))
        leaders_ok = bool(rule.get("dot_leaders_allowed", False)) and dotted == len(rows)
        if hairlines_ok or leaders_ok or len(rows) < 2:
            continue
        obj = rows_frames[0].name if len(rows_frames) == 1 else ", ".join(
            sorted({label(f) for f in rows_frames}))
        finding = Finding.from_rule(
            rule, obj,
            measured={"rows": len(rows), "hairlines_found": found,
                      "rows_with_dot_leaders": dotted,
                      **({"gaps_without_hairline": gaps_missing} if gaps_missing else {})},
            threshold={"hairlines_needed": len(rows) - 1,
                       "dot_leaders_allowed": bool(rule.get("dot_leaders_allowed", False))},
            message=f"{len(rows)} facts rows but only {found} hairline(s) between them"
                    + (f" and {dotted} row(s) with dot leaders." if rule.get("dot_leaders_allowed")
                       else "."),
        )
        finding.evidence["crop"] = schematic_crop(ctx, "facts_row_separators", "rows", rows_frames)
        findings.append(finding)
    return finalize(
        "facts_row_separators", "deterministic", findings, rules,
        "Facts rows are separated as required.",
        findings[0].message if findings else "",
    )
