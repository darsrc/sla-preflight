"""v0.2 checks: interfaces designed, not built.

Judgment checks (kind="judgment") must return evidence crops with every
finding and can never pass a release on their own: ``result.finalize``
turns a clean judgment result into ``warn`` for human confirmation.
"""
from __future__ import annotations

from ..registry import check

check(
    "text_contrast",
    kind="judgment",
    category="judgment",
    deferred=True,
    description="Text is readable against its background (measured contrast, model-assisted).",
    rules=("text_contrast",),
    explain="Measures contrast of each text run against the rendered background; borderline cases go to a model with the crop as evidence.",
    fix="Darken/lighten the text or background, or add a knockout.",
)(None)

check(
    "swatch_whitelist",
    category="content",
    deferred=True,
    description="Only colours from the brand's approved swatch list are used.",
    rules=("swatch_whitelist",),
    explain="Compares every colour used by an object with the allowed swatches in the brand pack.",
    fix="Replace the named colour with an approved swatch.",
)(None)

check(
    "fonts_available",
    category="content",
    deferred=True,
    description="Every font used is present in the confined font folder.",
    rules=("fonts_available",),
    explain="Lists fonts used by text runs and checks each exists in the font folder Scribus renders with.",
    fix="Add the font file to the font folder or change the text to an available font.",
)(None)

check(
    "brief_to_checklist",
    kind="judgment",
    category="judgment",
    deferred=True,
    inputs=("brief",),
    description="Turn client notes into atomic, checkable requirements.",
    explain="A model splits a brief into atomic requirements, each quoting the brief line it came from; a human confirms the list.",
    fix="Edit the generated checklist before using it.",
)(None)

check(
    "brief_compliance",
    kind="judgment",
    category="judgment",
    deferred=True,
    inputs=("sla", "brief"),
    description="Check each confirmed brief requirement against the design, with evidence.",
    explain="For each confirmed requirement, finds the relevant objects and returns a crop plus a model judgment.",
    fix="Address each requirement reported as not met.",
)(None)
