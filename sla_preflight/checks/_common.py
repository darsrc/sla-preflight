"""Helpers shared by checks: units, frame selection, overlap data, evidence."""
from __future__ import annotations

from fnmatch import fnmatchcase
from pathlib import Path

from ..context import Context
from ..sla import Document, Frame, pt_to_in

EPS_PT = 1e-6  # float noise; far below any real layout distance


class CheckInputError(Exception):
    """The check cannot run on this input (e.g. text it must parse is not
    there). Reported as ``error``, never as ``fail``."""


def matches(name: str, patterns) -> bool:
    """Frame-name lists in packs accept shell wildcards: 'bar_top',
    '*bar_top', 'Copy of *', 'bg_?'. Matching is case-sensitive."""
    return bool(name) and any(fnmatchcase(name, p) for p in patterns or ())


def any_matches(names, patterns) -> bool:
    return any(matches(n, patterns) for n in names)


def label(f: Frame) -> str:
    """How a frame is named in results: its Scribus name, or where it is
    when it has none."""
    if f.name:
        return f.name
    where = f"at ({pt_to_in(f.x):.3f}, {pt_to_in(f.y):.3f}) in"
    return f"unnamed {f.kind} {where}" + (f" in group {f.parent}" if f.parent else "")


def bleed_patterns(ctx: Context, rule) -> list[str]:
    """Objects allowed to bleed: the printer rule's bleed_allowed plus the
    frames of every bleed_objects rule (a layout/brand pack names its own
    bleed objects, e.g. 'Copy of background*')."""
    pats = list(rule.get("bleed_allowed", []) or [])
    for r in ctx.rules.all("bleed_objects"):
        pats += list(r.get("frames", []) or [])
    return pats


def missing_fonts(ctx: Context, available: list[str]) -> list[str]:
    """Fonts used by printing text that Scribus does not have. Scribus
    silently substitutes them, which changes text layout."""
    have = set(available)
    used = {
        r.font
        for f in printing_leaves(ctx.doc) if f.is_text
        for r in f.runs if r.text.strip() and r.font
    }
    return sorted(used - have)


def require_fonts(ctx: Context, available: list[str]) -> None:
    missing = missing_fonts(ctx, available)
    if missing:
        raise CheckInputError(
            f"{len(missing)} font(s) used by the label are not available to Scribus "
            f"({', '.join(missing)}), so its text layout would be wrong. Install them "
            "or point --fonts-dir / $SLA_PREFLIGHT_FONTS_DIR at a folder holding them."
        )


def r6(v: float) -> float:
    """Round a reported inch value to 6 places (display only; comparisons
    always use the exact values)."""
    return round(v, 6)


def box_in(box: tuple[float, float, float, float]) -> list[float]:
    return [r6(pt_to_in(v)) for v in box]


def printing_leaves(doc: Document) -> list[Frame]:
    """Frames that print: on a page, on a printing layer, not a group shell."""
    return [
        f for f in doc.all_frames()
        if f.kind != "group" and f.page is not None and doc.layer_printable(f)
    ]


def names_with_ancestry(frame: Frame, doc: Document) -> set[str]:
    """The frame's name plus the names of the groups that contain it."""
    by_name = {f.name: f for f in doc.all_frames() if f.name}
    out, cur = {frame.name}, frame
    while cur.parent:
        out.add(cur.parent)
        cur = by_name.get(cur.parent)
        if cur is None:
            break
    return out


def intersection(a, b):
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    if x1 - x0 > EPS_PT and y1 - y0 > EPS_PT:
        return (x0, y0, x1, y1)
    return None


def overlap_pairs(ctx: Context) -> list[dict]:
    """Every overlapping pair of (text frame, text-or-required frame) on the
    same page, minus declared container pairs. Shared by frame_overlap and
    required_elements; cached per run."""
    if "overlap_pairs" in ctx.cache:
        return ctx.cache["overlap_pairs"]
    doc = ctx.doc
    required = {n for r in ctx.rules.all("required_elements") for n in r.get("frames", [])}
    containers: list[tuple[str, str]] = []
    ignore: list[str] = []
    for r in ctx.rules.all("no_frame_overlap"):
        containers += [tuple(pair) for pair in r.get("containers", []) or []]
        ignore += list(r.get("ignore", []) or [])
    frames = [f for f in printing_leaves(doc)
              if not matches(f.name, ignore) and (f.is_text or matches(f.name, required))]
    pairs = []
    for i, a in enumerate(frames):
        for b in frames[i + 1:]:
            if a.page != b.page or not (a.is_text or b.is_text):
                continue
            if a.name and a.name == b.name:
                continue
            na, nb = names_with_ancestry(a, doc), names_with_ancestry(b, doc)
            if any((any_matches(na, [o]) and any_matches(nb, [i])) or
                   (any_matches(nb, [o]) and any_matches(na, [i])) for o, i in containers):
                continue
            box = intersection(a.bbox(), b.bbox())
            if box is None:
                continue
            # later in document order = stacked on top
            pairs.append({"top": b, "under": a, "box": box})
    ctx.cache["overlap_pairs"] = pairs
    return pairs


# ------------------------------------------------------------------ evidence
DPI = 100
COLORS = {"trim": (0, 0, 0), "bleed": (200, 0, 0), "safe": (0, 140, 255),
          "hit": (230, 0, 120), "other": (255, 150, 0), "frame": (170, 170, 170)}


def schematic_crop(ctx: Context, check: str, stem: str, highlight: list[Frame],
                   others: list[Frame] = (), region=None, safe_in: float | None = None) -> str:
    """Draw a schematic of the page (trim black, bleed red, safe area blue,
    all frames grey, highlighted frames magenta/orange) cropped around the
    highlighted objects. Used where no real render is needed; returns the
    PNG path."""
    from PIL import Image, ImageDraw

    doc = ctx.doc
    page = doc.pages[highlight[0].page or 0] if highlight and highlight[0].page is not None else doc.pages[0]
    b = doc.bleed
    s = DPI / 72.0
    ox, oy = b["left"] + 18, b["top"] + 18  # canvas margin, points
    W = int((page.width + b["left"] + b["right"] + 36) * s)
    H = int((page.height + b["top"] + b["bottom"] + 36) * s)
    im = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(im)

    def rect(box, color, width=1):
        x0, y0, x1, y1 = box
        d.rectangle([(x0 + ox) * s, (y0 + oy) * s, (x1 + ox) * s, (y1 + oy) * s],
                    outline=color, width=width)

    for f in doc.all_frames():
        if f.page == page.index and f.kind != "group":
            rect(f.bbox(), COLORS["frame"])
    rect((-b["left"], -b["top"], page.width + b["right"], page.height + b["bottom"]), COLORS["bleed"])
    rect((0, 0, page.width, page.height), COLORS["trim"], 2)
    if safe_in:
        m = safe_in * 72
        rect((m, m, page.width - m, page.height - m), COLORS["safe"])
    for f in others:
        rect(f.bbox(), COLORS["other"], 2)
    for f in highlight:
        rect(f.ink_bbox(), COLORS["hit"], 3)
    if region:
        rect(region, COLORS["hit"], 1)
    boxes = [f.ink_bbox() for f in list(highlight) + list(others)] + ([region] if region else [])
    if boxes:
        pad = 36
        x0 = max(0, int((min(bx[0] for bx in boxes) + ox - pad) * s))
        y0 = max(0, int((min(bx[1] for bx in boxes) + oy - pad) * s))
        x1 = min(W, int((max(bx[2] for bx in boxes) + ox + pad) * s))
        y1 = min(H, int((max(bx[3] for bx in boxes) + oy + pad) * s))
        im = im.crop((x0, y0, x1, y1))
    path = ctx.check_dir(check) / f"{_safe(stem)}.png"
    im.save(path)
    return str(path)


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in name) or "object"


def page_label(index: int | None) -> str:
    return f"page {(index or 0) + 1}"


__all__ = [
    "CheckInputError", "r6", "matches", "any_matches", "label", "bleed_patterns",
    "missing_fonts", "require_fonts", "box_in", "printing_leaves", "overlap_pairs",
    "schematic_crop", "page_label", "intersection", "names_with_ancestry", "Path",
]
