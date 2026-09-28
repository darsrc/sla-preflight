"""Content checks, read from the .sla text (deterministic)."""
from __future__ import annotations

from ..context import Context
from ..registry import check
from ..result import CheckResult


@check(
    "required_elements",
    category="content",
    description="Every required frame exists, prints, has content, and is not overlapped.",
    rules=("required_elements",),
    optional_rules=("no_frame_overlap",),
    explain=(
        "For each frame named in every required_elements rule (brand and regulatory packs): "
        "the frame exists, is on a printing layer, is non-empty (text frames have text), and "
        "no other text frame overlaps it (same overlap data as frame_overlap)."
    ),
    fix="Restore or rename the frame, move it to a printing layer, fill it, or move the overlapping frame away.",
)
def required_elements(ctx: Context) -> CheckResult:
    raise NotImplementedError


@check(
    "facts_math",
    category="content",
    description="Servings per container equals count / serving size.",
    rules=("facts_math",),
    explain=(
        "Parses the unit count (e.g. '200 Capsules') from the count frame and the serving size "
        "and servings per container from the serving_info frame, using the regexes in the "
        "facts_math rule. Fails on mismatch; errors when a number cannot be parsed."
    ),
    fix="Correct 'Servings Per Container' (or the count / serving size) so that count / serving size = servings.",
)
def facts_math(ctx: Context) -> CheckResult:
    raise NotImplementedError


@check(
    "claim_disclaimer_pairing",
    category="content",
    description="If any claim frame has text, the disclaimer frame is present and non-empty.",
    rules=("claim_disclaimer",),
    explain=(
        "Looks at the frames listed in claim_disclaimer.claim_frames. If any has text, the "
        "frame named in disclaimer_frame must exist on a printing layer and have text."
    ),
    fix="Add the disclaimer text to the named disclaimer frame, or remove the claim.",
)
def claim_disclaimer_pairing(ctx: Context) -> CheckResult:
    raise NotImplementedError
