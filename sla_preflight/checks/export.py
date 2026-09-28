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


def _box_size_in(page) -> tuple[float, float]:
    x0, y0, x1, y1 = (float(v) for v in page.MediaBox)
    w, h = abs(x1 - x0) / 72, abs(y1 - y0) / 72
    if int(page.obj.get("/Rotate", 0)) % 180:
        w, h = h, w
    return w, h


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
        "When pdf_bleed.required is true, reads each PDF page's MediaBox (and TrimBox/BleedBox "
        "when present) and compares the size with the .sla page size plus the .sla document "
        "bleed on each side. A PDF the size of trim was exported without bleed; a document "
        "with zero bleed fails too. The bleed amount itself is checked by page_matches_die."
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
                tw, th = pt_to_in(sla_page.width), pt_to_in(sla_page.height)
                ew, eh = tw + b["left"] + b["right"], th + b["top"] + b["bottom"]
                w, h = _box_size_in(page)
                if abs(w - ew) <= tol and abs(h - eh) <= tol:
                    continue
                trim_sized = abs(w - tw) <= tol and abs(h - th) <= tol
                findings.append(Finding.from_rule(
                    rule, page_label(i),
                    measured={"width_in": r6(w), "height_in": r6(h)},
                    threshold={"width_in": r6(ew), "height_in": r6(eh), "tolerance_in": tol},
                    message=("PDF page is trim size: it was exported without bleed."
                             if trim_sized else "PDF page is not trim + bleed."),
                ))
    return finalize(
        "pdf_page_box", "deterministic", findings, rules,
        "PDF page size is trim plus bleed.",
        f"PDF page size is not trim plus bleed: {findings[0].message}" if findings else "",
    )


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
