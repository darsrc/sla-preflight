"""Render regression against an approved render (deterministic)."""
from __future__ import annotations

from PIL import Image, ImageChops

from ..context import Context
from ..registry import check
from ..result import CheckResult, Finding, finalize
from ..scribus import available_fonts, render_png
from ._common import box_in, intersection, label, printing_leaves, require_fonts

CELL = 8  # px; changed pixels are grouped on this grid into regions


def _regions(mask: Image.Image) -> list[tuple[int, int, int, int]]:
    """Group changed pixels (mask > 0) into boxes of 8-connected grid cells."""
    w, h = mask.size
    # pad to whole cells, then average each cell: any changed pixel leaves
    # a non-zero cell
    padded = Image.new("L", (-(-w // CELL) * CELL, -(-h // CELL) * CELL), 0)
    padded.paste(mask, (0, 0))
    small = padded.reduce(CELL)
    gw, gh = small.size
    px = small.load()
    seen = set()
    out = []
    for y in range(gh):
        for x in range(gw):
            if px[x, y] == 0 or (x, y) in seen:
                continue
            stack, cells = [(x, y)], []
            seen.add((x, y))
            while stack:
                cx, cy = stack.pop()
                cells.append((cx, cy))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < gw and 0 <= ny < gh and (nx, ny) not in seen and px[nx, ny]:
                            seen.add((nx, ny))
                            stack.append((nx, ny))
            xs, ys = [c[0] for c in cells], [c[1] for c in cells]
            out.append((min(xs) * CELL, min(ys) * CELL,
                        min(w, (max(xs) + 1) * CELL), min(h, (max(ys) + 1) * CELL)))
    return out


@check(
    "render_regression",
    category="regression",
    description="Pixel diff against an approved render; changed regions are mapped to object names.",
    inputs=("sla", "approved_render"),
    rules=("render_regression",),
    explain=(
        "Renders the .sla with headless Scribus at render_regression.dpi, diffs it against the "
        "approved PNG, groups changed pixels into regions, and names the objects under each "
        "region. Fails when the changed area exceeds max_changed_fraction."
    ),
    fix="If the change was intended, approve the new render; otherwise undo the change to the named objects.",
)
def render_regression(ctx: Context) -> CheckResult:
    rules = ctx.rules.all("render_regression")
    rule = rules[0]
    dpi = int(rule.get("dpi", 150))
    thresh = int(rule.get("pixel_threshold", 24))
    max_frac = float(rule.get("max_changed_fraction", 0.0))
    outdir = ctx.check_dir("render_regression")
    require_fonts(ctx, available_fonts(fonts_dir=ctx.options.get("fonts_dir")))
    current_path = render_png(ctx.sla_path, outdir / "current.png", dpi=dpi,
                              fonts_dir=ctx.options.get("fonts_dir"))
    if not ctx.approved_render.is_file():
        raise FileNotFoundError(f"approved render not found: {ctx.approved_render}")
    cur = Image.open(current_path).convert("RGB")
    ref = Image.open(ctx.approved_render).convert("RGB")
    findings: list[Finding] = []
    thr = {"max_changed_fraction": max_frac, "pixel_threshold": thresh, "dpi": dpi}
    if cur.size != ref.size:
        findings.append(Finding.from_rule(
            rule, "page 1", measured={"size_px": list(cur.size), "approved_size_px": list(ref.size)},
            threshold=thr,
            message="Render size differs from the approved render (page size or dpi changed).",
        ))
        return finalize("render_regression", "deterministic", findings, rules, "",
                        findings[0].message)
    r, g, b = ImageChops.difference(cur, ref).split()
    diff = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mask = diff.point(lambda v: 255 if v > thresh else 0)
    changed = mask.histogram()[255]
    frac = changed / (cur.size[0] * cur.size[1])
    if changed and frac > max_frac:
        scale = 72.0 / dpi
        leaves = [f for f in printing_leaves(ctx.doc) if f.page == 0]
        for i, (x0, y0, x1, y1) in enumerate(_regions(mask), 1):
            region_pt = (x0 * scale, y0 * scale, x1 * scale, y1 * scale)
            hits = [f for f in leaves if intersection(f.ink_bbox(), region_pt)]
            # the most specific object first: smallest frame under the change
            hits.sort(key=lambda f: (f.bbox()[2] - f.bbox()[0]) * (f.bbox()[3] - f.bbox()[1]))
            names = [label(f) for f in hits]
            pad = 12
            crop_box = (max(0, x0 - pad), max(0, y0 - pad),
                        min(cur.size[0], x1 + pad), min(cur.size[1], y1 + pad))
            a, c = ref.crop(crop_box), cur.crop(crop_box)
            pair = Image.new("RGB", (a.width * 2 + 4, a.height), (255, 0, 120))
            pair.paste(a, (0, 0))
            pair.paste(c, (a.width + 4, 0))
            crop = outdir / f"region_{i}.png"
            pair.save(crop)
            findings.append(Finding.from_rule(
                rule, names[0] if names else f"region {i}",
                measured={"objects_under_change": names, "region_in": box_in(region_pt),
                          "changed_fraction": round(frac, 6)},
                threshold=thr,
                evidence={"crop": str(crop), "note": "left: approved, right: current",
                          "render": str(current_path)},
                message=f"Render changed around {', '.join(names[:3]) or 'an empty area'}.",
            ))
    names = [f.object for f in findings]
    return finalize(
        "render_regression", "deterministic", findings, rules,
        "Render matches the approved render.",
        f"Render differs from the approved render in {len(findings)} region(s): {', '.join(names)}.",
    )
