"""Export checks, read from the PDF with pikepdf (deterministic)."""
from __future__ import annotations

from ..context import Context
from ..registry import check
from ..result import CheckResult


@check(
    "pdf_page_box",
    category="export",
    description="PDF page size equals trim + 2 x bleed (catches an export with no bleed).",
    inputs=("sla", "pdf"),
    rules=("pdf_export",),
    explain=(
        "Reads each PDF page's MediaBox (and TrimBox/BleedBox when present) and compares the "
        "size with the .sla page size plus 2 x pdf_export.bleed_in. A PDF the size of trim "
        "was exported without bleed."
    ),
    fix="Re-export with File > Export > PDF > Pre-Press: 'Use Document Bleeds' on.",
)
def pdf_page_box(ctx: Context) -> CheckResult:
    raise NotImplementedError


@check(
    "pdf_fonts_outlined",
    category="export",
    description="No live embedded fonts when the printer requires outlined text.",
    inputs=("pdf",),
    rules=("pdf_export",),
    explain=(
        "When pdf_export.fonts_outlined is true, walks every page's resources (form XObjects "
        "and annotations included) and reports every font found."
    ),
    fix="Re-export with File > Export > PDF > Fonts: 'Outline' all fonts.",
)
def pdf_fonts_outlined(ctx: Context) -> CheckResult:
    raise NotImplementedError


@check(
    "pdf_color_space",
    category="export",
    description="No RGB content when the printer requires CMYK.",
    inputs=("pdf",),
    rules=("pdf_export",),
    explain=(
        "When pdf_export.color_space is CMYK, looks for DeviceRGB/CalRGB/ICC-RGB colour spaces "
        "in page resources and images, and RGB colour operators in content streams."
    ),
    fix="Re-export with File > Export > PDF > Color: output intended for Printer, convert to CMYK; replace RGB images and swatches.",
)
def pdf_color_space(ctx: Context) -> CheckResult:
    raise NotImplementedError
