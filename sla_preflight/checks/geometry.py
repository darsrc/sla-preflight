"""Geometry checks, read from the .sla (deterministic)."""
from __future__ import annotations

from ..context import Context
from ..registry import check
from ..result import CheckResult


@check(
    "page_matches_die",
    category="geometry",
    description="Page size equals the printer's die; bleed is set in document settings, not baked into the page.",
    rules=("die",),
    explain=(
        "Compares every page's width and height with the die size in the printer pack "
        "(rule 'die': width_in, height_in, bleed_in, tolerance_in). Also checks that the "
        "document bleed settings equal bleed_in on all four sides. A page that equals "
        "die + 2 x bleed means bleed was baked into the page size."
    ),
    fix=(
        "Document Setup: set the page size to the die size exactly, and put the bleed "
        "in Document Setup > Bleeds, not in the page size."
    ),
)
def page_matches_die(ctx: Context) -> CheckResult:
    raise NotImplementedError


@check(
    "trim_safety",
    category="geometry",
    description="Every object not allowed to bleed sits at least min_gap_in inside trim.",
    rules=("safe_margin",),
    explain=(
        "For every object on a printing layer (group children included, rotation and "
        "visible stroke included), measures the gap from each side to the trim edge using "
        "exact XML values. Objects named in safe_margin.bleed_allowed are exempt. Reports "
        "each side under min_gap_in with the measured gap."
    ),
    fix="Move or shrink the named object so every side is at least min_gap_in inside trim, or, if it is meant to bleed, add it to bleed_allowed in the pack.",
)
def trim_safety(ctx: Context) -> CheckResult:
    raise NotImplementedError


@check(
    "bleed_coverage",
    category="geometry",
    description="Bleed objects that touch a trim edge extend fully to the bleed edge on that side.",
    rules=("safe_margin",),
    explain=(
        "For each object listed in safe_margin.bleed_allowed, finds the trim edges it "
        "touches or crosses, and checks it reaches the bleed edge (document bleed setting) "
        "on each of those sides. A band that stops at trim leaves a white sliver after cutting."
    ),
    fix="Extend the named object past trim to the bleed edge on the reported side.",
)
def bleed_coverage(ctx: Context) -> CheckResult:
    raise NotImplementedError


@check(
    "frame_overflow",
    category="geometry",
    description="No text frame overflows (asks Scribus for real text layout).",
    rules=("no_text_overflow",),
    explain=(
        "Opens the document in headless Scribus (under xvfb-run if there is no display) and "
        "asks the Scripter whether each text frame's text fits. Overflowing text is not printed."
    ),
    fix="Enlarge the named frame, shorten the text, or link it to a continuation frame.",
)
def frame_overflow(ctx: Context) -> CheckResult:
    raise NotImplementedError


@check(
    "frame_overlap",
    category="geometry",
    description="No text frame overlaps another text frame or a required frame, except declared containers.",
    rules=("no_frame_overlap",),
    optional_rules=("required_elements",),
    explain=(
        "Intersects the boxes of all text frames on printing layers with each other and with "
        "every frame listed in required_elements. Pairs declared in no_frame_overlap.containers "
        "(e.g. a text frame inside its own box outline) are allowed. Reports each pair with the "
        "overlap area."
    ),
    fix="Move or resize one frame of the reported pair so they no longer overlap, or declare the pair a container if the overlap is intended.",
)
def frame_overlap(ctx: Context) -> CheckResult:
    raise NotImplementedError


@check(
    "min_type_size",
    category="geometry",
    description="No text below the minimum size in the pack; reports every run under it.",
    rules=("min_type_size",),
    explain=(
        "Resolves the font size of every text run (character, paragraph style and document "
        "defaults) and reports each run below min_type_size.min_pt with frame name and size. "
        "A rule may limit itself to certain frames with 'frames'."
    ),
    fix="Raise the reported runs to at least min_pt, making room by resizing the frame or trimming text.",
)
def min_type_size(ctx: Context) -> CheckResult:
    raise NotImplementedError
