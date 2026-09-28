"""Export checks, read from the PDF with pikepdf (deterministic)."""
from __future__ import annotations

import pikepdf

from ..context import Context
from ..registry import check
from ..result import CheckResult, Finding, finalize
from ..sla import pt_to_in
from ._common import page_label, r6

RGB_NAMES = {"/DeviceRGB", "/CalRGB", "/RGB"}  # /RGB: inline-image abbreviation
RGB_OPERATORS = {"rg", "RG"}


def _open(ctx: Context) -> pikepdf.Pdf:
    if not ctx.pdf_path.is_file():
        raise FileNotFoundError(f"PDF not found: {ctx.pdf_path}")
    try:
        return pikepdf.open(ctx.pdf_path)
    except pikepdf.PdfError as e:
        raise FileNotFoundError(f"{ctx.pdf_path.name}: not a readable PDF: {e}") from e


def _box(page, key: str):
    """A page box as (x0, y0, x1, y1) in points, normalised; None if absent."""
    v = page.obj.get(key)
    if v is None:
        return None
    x0, y0, x1, y1 = (float(n) for n in v)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _page_geometry(page):
    """(trim box or None, bleed box, rotated?). The bleed box falls back to
    CropBox then MediaBox (PDF defaults) and is clipped to the MediaBox; a
    MediaBox bigger than the bleed box just holds printer marks."""
    media = _box(page, "/MediaBox")
    bleed = _box(page, "/BleedBox") or _box(page, "/CropBox") or media
    bleed = (max(bleed[0], media[0]), max(bleed[1], media[1]),
             min(bleed[2], media[2]), min(bleed[3], media[3]))
    rotated = int(page.obj.get("/Rotate", 0)) % 180 != 0
    return _box(page, "/TrimBox"), bleed, rotated


def _resource_dicts(resources, seen=None):
    """Yield (path, resources) for a resources dict and every form XObject,
    pattern and Type3 font it reaches."""
    seen = seen if seen is not None else set()
    if resources is None or not isinstance(resources, pikepdf.Dictionary):
        return
    key = resources.objgen if resources.is_indirect else id(resources)
    if key in seen:
        return
    seen.add(key)
    yield resources
    for group in ("/XObject", "/Pattern"):
        for _, obj in (resources.get(group) or {}).items():
            if isinstance(obj, (pikepdf.Stream, pikepdf.Dictionary)) and "/Resources" in obj:
                yield from _resource_dicts(obj.Resources, seen)
    for _, font in (resources.get("/Font") or {}).items():
        if isinstance(font, pikepdf.Dictionary) and "/Resources" in font:
            yield from _resource_dicts(font.Resources, seen)


def _page_resource_dicts(page):
    yield from _resource_dicts(page.obj.get("/Resources"))
    for annot in page.obj.get("/Annots") or []:
        ap = annot.get("/AP") if isinstance(annot, pikepdf.Dictionary) else None
        normal = ap.get("/N") if ap is not None else None
        if isinstance(normal, pikepdf.Stream) and "/Resources" in normal:
            yield from _resource_dicts(normal.Resources)


def _is_rgb(cs, resources=None, depth=0) -> bool:
    if depth > 8 or cs is None:
        return False
    if isinstance(cs, pikepdf.Name):
        if str(cs) in RGB_NAMES:
            return True
        named = (resources.get("/ColorSpace") or {}) if resources is not None else {}
        return str(cs) in named and _is_rgb(named[str(cs)], resources, depth + 1)
    if isinstance(cs, pikepdf.Array) and len(cs):
        kind = str(cs[0])
        if kind == "/CalRGB":
            return True
        if kind == "/ICCBased":
            return int(cs[1].get("/N", 0)) == 3
        if kind == "/Indexed":
            return _is_rgb(cs[1], resources, depth + 1)
    return False


@check(
    "pdf_page_box",
    category="export",
    description="PDF page size equals trim + 2 x bleed (catches an export with no bleed).",
    inputs=("sla", "pdf"),
    rules=("pdf_bleed",),
    explain=(
        "When pdf_bleed.required is true, reads each PDF page's TrimBox and BleedBox (falling "
        "back to CropBox/MediaBox), checks the trim equals the .sla page and the bleed on each "
        "side equals the .sla document bleed. Printer marks outside the bleed box are ignored. "
        "A PDF with no bleed, or a document with zero bleed, fails. The bleed amount itself is "
        "checked by page_matches_die."
    ),
    fix="Re-export with File > Export > PDF > Pre-Press: 'Use Document Bleeds' on.",
)
def pdf_page_box(ctx: Context) -> CheckResult:
    rules = ctx.rules.all("pdf_bleed")
    doc = ctx.doc
    findings: list[Finding] = []
    with _open(ctx) as pdf:
        for rule in rules:
            if not rule.get("required", True):
                continue
            tol = rule.get("tolerance_in", 0.001)
            b = {k: pt_to_in(v) for k, v in doc.bleed.items()}
            if max(b.values()) <= 0:
                findings.append(Finding.from_rule(
                    rule, "document bleed",
                    measured={f"bleed_{k}_in": r6(v) for k, v in b.items()},
                    threshold={"bleed_required": True},
                    message="The .sla has no bleed set, so no export can include bleed.",
                ))
            if len(pdf.pages) != len(doc.pages):
                findings.append(Finding.from_rule(
                    rule, "document", measured={"pdf_pages": len(pdf.pages)},
                    threshold={"sla_pages": len(doc.pages)},
                    message="PDF and .sla have different page counts.",
                ))
            for i, page in enumerate(pdf.pages):
                sla_page = doc.pages[min(i, len(doc.pages) - 1)]
                findings += _check_page_box(rule, page, i, sla_page, b, tol)
    return finalize(
        "pdf_page_box", "deterministic", findings, rules,
        "PDF trim and bleed match the .sla document.",
        f"PDF bleed is wrong: {findings[0].message}" if findings else "",
    )


def _check_page_box(rule, page, i, sla_page, b, tol) -> list[Finding]:
    """Compare one PDF page with the .sla page (trim) and document bleed.
    With a TrimBox (Scribus always writes one) each side's bleed is measured
    between TrimBox and BleedBox, so printer marks do not matter; without
    one, the bleed box size is compared with trim + bleed."""
    tw, th = pt_to_in(sla_page.width), pt_to_in(sla_page.height)
    trim, bleed, rotated = _page_geometry(page)
    thr_b = {f"bleed_{k}_in": r6(v) for k, v in b.items()}
    thr_b["tolerance_in"] = tol
    out = []
    if trim is not None and not rotated:
        pw, ph = (trim[2] - trim[0]) / 72, (trim[3] - trim[1]) / 72
        if abs(pw - tw) > tol or abs(ph - th) > tol:
            out.append(Finding.from_rule(
                rule, page_label(i),
                measured={"trim_width_in": r6(pw), "trim_height_in": r6(ph)},
                threshold={"trim_width_in": r6(tw), "trim_height_in": r6(th), "tolerance_in": tol},
                message="PDF TrimBox differs from the .sla page size.",
            ))
        # PDF y runs upwards: bottom bleed is at low y
        got = {"left": (trim[0] - bleed[0]) / 72, "right": (bleed[2] - trim[2]) / 72,
               "top": (bleed[3] - trim[3]) / 72, "bottom": (trim[1] - bleed[1]) / 72}
        wrong = {k: v for k, v in got.items() if abs(v - b[k]) > tol}
        if wrong:
            none = all(v <= tol for v in got.values())
            out.append(Finding.from_rule(
                rule, page_label(i),
                measured={f"bleed_{k}_in": r6(v) for k, v in got.items()},
                threshold=thr_b,
                message=("PDF has no bleed: it was exported without bleed." if none else
                         "PDF bleed differs from the document bleed on the "
                         + ", ".join(wrong) + " side" + ("s" if len(wrong) > 1 else "") + "."),
            ))
        return out
    # no TrimBox (or rotated page): compare overall size
    w, h = (bleed[2] - bleed[0]) / 72, (bleed[3] - bleed[1]) / 72
    if rotated:
        w, h = h, w
    ew, eh = tw + b["left"] + b["right"], th + b["top"] + b["bottom"]
    if abs(w - ew) > tol or abs(h - eh) > tol:
        trim_sized = abs(w - tw) <= tol and abs(h - th) <= tol
        out.append(Finding.from_rule(
            rule, page_label(i),
            measured={"width_in": r6(w), "height_in": r6(h)},
            threshold={"width_in": r6(ew), "height_in": r6(eh), "tolerance_in": tol},
            message=("PDF page is trim size: it was exported without bleed."
                     if trim_sized else "PDF page is not trim + bleed."),
        ))
    return out


@check(
    "pdf_fonts_outlined",
    category="export",
    description="No live embedded fonts when the printer requires outlined text.",
    inputs=("pdf",),
    rules=("pdf_fonts",),
    explain=(
        "When pdf_fonts.fonts_outlined is true, walks every page's resources (form XObjects "
        "and annotations included) and reports every font found."
    ),
    fix="Re-export with File > Export > PDF > Fonts: 'Outline' all fonts.",
)
def pdf_fonts_outlined(ctx: Context) -> CheckResult:
    rules = ctx.rules.all("pdf_fonts")
    findings: list[Finding] = []
    with _open(ctx) as pdf:
        for rule in rules:
            if not rule.get("fonts_outlined", False):
                continue
            seen: set[tuple[str, int]] = set()
            for i, page in enumerate(pdf.pages):
                for res in _page_resource_dicts(page):
                    for key, font in (res.get("/Font") or {}).items():
                        base = str(font.get("/BaseFont", key)).lstrip("/")
                        base = base.split("+", 1)[1] if "+" in base[:7] else base
                        if (base, i) in seen:
                            continue
                        seen.add((base, i))
                        findings.append(Finding.from_rule(
                            rule, base,
                            measured={"page": i + 1, "subtype": str(font.get("/Subtype", "")).lstrip("/"),
                                      "resource": str(key)},
                            threshold={"fonts_outlined": True},
                            message=f"Live font {base} on page {i + 1}; text is not outlined.",
                        ))
    names = sorted({f.object for f in findings})
    return finalize(
        "pdf_fonts_outlined", "deterministic", findings, rules,
        "No live fonts in the PDF; all text is outlined.",
        f"{len(names)} live font(s) in the PDF: {', '.join(names)}.",
    )


@check(
    "pdf_color_space",
    category="export",
    description="No RGB content when the printer requires CMYK.",
    inputs=("pdf",),
    rules=("pdf_color",),
    explain=(
        "When pdf_color.color_space is CMYK, looks for DeviceRGB/CalRGB/ICC-RGB colour spaces "
        "in page resources and images, and RGB colour operators in content streams."
    ),
    fix="Re-export with File > Export > PDF > Color: output intended for Printer, convert to CMYK; replace RGB images and swatches.",
)
def pdf_color_space(ctx: Context) -> CheckResult:
    rules = ctx.rules.all("pdf_color")
    findings: list[Finding] = []
    with _open(ctx) as pdf:
        for rule in rules:
            if str(rule.get("color_space", "")).upper() != "CMYK":
                continue
            thr = {"color_space": "CMYK"}
            for i, page in enumerate(pdf.pages):
                label = page_label(i)
                for res in _page_resource_dicts(page):
                    for key, xo in (res.get("/XObject") or {}).items():
                        if xo.get("/Subtype") == "/Image" and _is_rgb(xo.get("/ColorSpace"), res):
                            findings.append(Finding.from_rule(
                                rule, str(key).lstrip("/"),
                                measured={"page": i + 1, "kind": "image",
                                          "color_space": str(xo.get("/ColorSpace"))[:60]},
                                threshold=thr, message=f"RGB image {key} on page {i + 1}.",
                            ))
                    for key, sh in (res.get("/Shading") or {}).items():
                        if _is_rgb(sh.get("/ColorSpace"), res):
                            findings.append(Finding.from_rule(
                                rule, str(key).lstrip("/"),
                                measured={"page": i + 1, "kind": "shading"},
                                threshold=thr, message=f"RGB shading {key} on page {i + 1}.",
                            ))
                ops: dict[str, int] = {}
                res0 = page.obj.get("/Resources")
                for operands, op in pikepdf.parse_content_stream(page):
                    name = str(op)
                    if name in RGB_OPERATORS:
                        ops[name] = ops.get(name, 0) + 1
                    elif name in ("cs", "CS") and operands and _is_rgb(operands[0], res0):
                        ops[name] = ops.get(name, 0) + 1
                    elif name == "INLINE IMAGE" and operands:
                        d = getattr(operands[0], "obj", None)
                        cs = d.get("/ColorSpace", d.get("/CS")) if d is not None else None
                        if _is_rgb(cs, res0):
                            ops["inline image"] = ops.get("inline image", 0) + 1
                if ops:
                    findings.append(Finding.from_rule(
                        rule, label, measured={"page": i + 1, "rgb_operators": ops},
                        threshold=thr, message=f"RGB colour set directly on {label}.",
                    ))
    names = sorted({f.object for f in findings})
    return finalize(
        "pdf_color_space", "deterministic", findings, rules,
        "PDF uses no RGB colour.",
        f"RGB content found: {', '.join(names)}.",
    )
