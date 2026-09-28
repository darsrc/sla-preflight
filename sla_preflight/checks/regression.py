"""Render regression against an approved render (deterministic)."""
from __future__ import annotations

from ..context import Context
from ..registry import check
from ..result import CheckResult


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
    raise NotImplementedError
