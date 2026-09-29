"""Geometry checks, read from the .sla (deterministic)."""
from __future__ import annotations

from ..context import Context
from ..registry import check
from ..result import CheckResult, Finding, finalize
from ..scribus import layout_report
from ..sla import pt_to_in
from ._common import (
    EPS_PT, any_matches, bleed_patterns, box_in, label, matches, names_with_ancestry,
    overlap_pairs, page_label, printing_leaves, r6, require_fonts, schematic_crop, with_aliases,
)

SIDES = ("left", "top", "right", "bottom")


@check(
    "page_matches_die",
    category="geometry",
    description="Page size equals this job's die; document bleed equals the printer's bleed.",
    rules=("die", "bleed"),
    explain=(
        "Compares every page's width and height with the job's die size, given at run time "
        "(--die 10.25x2.5; rule job#die). Checks the document bleed settings equal the printer "
        "pack's bleed.bleed_in on all four sides. A page that equals die + 2 x bleed means the "
        "bleed was baked into the page size. Without --die only the bleed is checked."
    ),
    fix=(
        "Document Setup: set the page size to the die size exactly, and put the bleed "
        "in Document Setup > Bleeds, not in the page size."
    ),
)
def page_matches_die(ctx: Context) -> CheckResult:
    doc = ctx.doc
    dies, bleeds = ctx.rules.all("die"), ctx.rules.all("bleed")
    bleed_in = bleeds[0]["bleed_in"] if bleeds else None
    findings: list[Finding] = []
    for rule in dies:
        w, h = rule["width_in"], rule["height_in"]
        tol = rule.get("tolerance_in", 0.001)
        for pg in doc.pages:
            pw, ph = pt_to_in(pg.width), pt_to_in(pg.height)
            if abs(pw - w) > tol or abs(ph - h) > tol:
                baked = (bleed_in is not None and abs(pw - (w + 2 * bleed_in)) <= tol
                         and abs(ph - (h + 2 * bleed_in)) <= tol)
                findings.append(Finding.from_rule(
                    rule, page_label(pg.index),
                    measured={"width_in": r6(pw), "height_in": r6(ph)},
                    threshold={"width_in": w, "height_in": h, "tolerance_in": tol},
                    message=("Bleed is baked into the page size; set the page to the die "
                             "and put the bleed in Document Setup > Bleeds."
                             if baked else "Page size differs from the die."),
                ))
    for rule in bleeds:
        want, tol = rule["bleed_in"], rule.get("tolerance_in", 0.001)
        sides = {k: r6(pt_to_in(v)) for k, v in doc.bleed.items()}
        if any(abs(v - want) > tol for v in sides.values()):
            findings.append(Finding.from_rule(
                rule, "document bleed",
                measured={f"bleed_{k}_in": v for k, v in sides.items()},
                threshold={"bleed_in": want, "tolerance_in": tol},
                message="Document bleed settings differ from the printer's bleed.",
            ))
    n = len(findings)
    ok = "Page size matches the die and document bleed is set." if dies else (
        "Document bleed matches the printer; page size not checked (no die given, use --die).")
    return finalize(
        "page_matches_die", "deterministic", findings, dies + bleeds, ok,
        f"Page size or bleed does not match ({n} problem{'s' * (n != 1)}).",
    )


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
    doc = ctx.doc
    rules = ctx.rules.all("safe_margin")
    findings: list[Finding] = []
    for rule in rules:
        min_gap = rule["min_gap_in"]
        allowed = bleed_patterns(ctx, rule)
        for f in printing_leaves(doc):
            if any_matches(names_with_ancestry(f, doc), allowed):
                continue
            pg = doc.pages[f.page]
            x0, y0, x1, y1 = f.ink_bbox()
            gaps = {"left": x0, "top": y0, "right": pg.width - x1, "bottom": pg.height - y1}
            short = {k: v for k, v in gaps.items() if pt_to_in(v) < min_gap - EPS_PT}
            if not short:
                continue
            finding = Finding.from_rule(
                rule, label(f),
                measured={**{f"gap_{k}_in": r6(pt_to_in(v)) for k, v in short.items()},
                          "page": f.page + 1, **({"master_page": f.master} if f.master else {})},
                threshold={"min_gap_in": min_gap},
                message=f"{label(f)!r} is closer than {min_gap} in to trim on the "
                        + ", ".join(short) + " side" + ("s" if len(short) > 1 else "") + ".",
            )
            finding.evidence["crop"] = schematic_crop(
                ctx, "trim_safety", label(f), [f], safe_in=min_gap)
            findings.append(finding)
    names = sorted({f.object for f in findings})
    return finalize(
        "trim_safety", "deterministic", findings, rules,
        "All non-bleed objects sit inside the safe margin.",
        f"{len(names)} object(s) too close to trim: {', '.join(names)}.",
    )


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
    doc = ctx.doc
    rules = ctx.rules.all("safe_margin")
    findings: list[Finding] = []
    for rule in rules:
        allowed = bleed_patterns(ctx, rule)
        tol = rule.get("touch_tolerance_in", 0.001) * 72
        for f in printing_leaves(doc):
            if not any_matches(names_with_ancestry(f, doc), allowed):
                continue
            pg = doc.pages[f.page]
            b = doc.bleed
            x0, y0, x1, y1 = f.bbox()
            # how far past trim the object reaches on each side it touches
            reach = {
                "left": (x0 <= tol, -x0, b["left"]),
                "top": (y0 <= tol, -y0, b["top"]),
                "right": (x1 >= pg.width - tol, x1 - pg.width, b["right"]),
                "bottom": (y1 >= pg.height - tol, y1 - pg.height, b["bottom"]),
            }
            short = {k: (past, need) for k, (touch, past, need) in reach.items()
                     if touch and past < need - tol}
            if not short:
                continue
            finding = Finding.from_rule(
                rule, label(f),
                measured={f"past_trim_{k}_in": r6(pt_to_in(p)) for k, (p, _) in short.items()},
                threshold={f"bleed_{k}_in": r6(pt_to_in(n)) for k, (_, n) in short.items()},
                message=f"{label(f)!r} touches trim but stops short of the bleed edge on the "
                        + ", ".join(short) + " side" + ("s" if len(short) > 1 else "") + ".",
            )
            finding.evidence["crop"] = schematic_crop(ctx, "bleed_coverage", label(f), [f])
            findings.append(finding)
    names = sorted({f.object for f in findings})
    return finalize(
        "bleed_coverage", "deterministic", findings, rules,
        "Every bleed object that touches trim runs to the bleed edge.",
        f"{len(names)} bleed object(s) stop short of the bleed edge: {', '.join(names)}.",
    )


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
    doc = ctx.doc
    rules = ctx.rules.all("no_text_overflow")
    report = layout_report(ctx.sla_path, fonts_dir=ctx.options.get("fonts_dir"))
    require_fonts(ctx, report["fonts"])
    over = report["overflows"]
    frames = {f.name: f for f in doc.all_frames() if f.is_text and f.name}
    findings: list[Finding] = []
    for rule in rules:
        for name, flag in sorted(over.items()):
            if not flag:
                continue
            f = frames.get(name)
            if f is not None and (f.page is None or not doc.layer_printable(f)):
                continue  # does not print
            finding = Finding.from_rule(
                rule, name, measured={"overflows": True}, threshold={"overflows": False},
                message=f"Text in {name!r} does not fit its frame; the rest will not print."
                        + ("" if f else " (Scribus named this unnamed frame.)"),
            )
            if f is not None:
                finding.evidence["crop"] = schematic_crop(ctx, "frame_overflow", name, [f])
            findings.append(finding)
    names = sorted({f.object for f in findings})
    return finalize(
        "frame_overflow", "deterministic", findings, rules,
        f"No text frame overflows ({len(over)} checked in Scribus).",
        f"{len(names)} text frame(s) overflow: {', '.join(names)}.",
    )


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
    rules = ctx.rules.all("no_frame_overlap")
    rule = rules[0]  # containers/ignore from all packs are merged in overlap_pairs
    findings: list[Finding] = []
    for p in overlap_pairs(ctx):
        top, under, box = p["top"], p["under"], p["box"]
        w, h = pt_to_in(box[2] - box[0]), pt_to_in(box[3] - box[1])
        finding = Finding.from_rule(
            rule, label(top),
            measured={"other": label(under), "overlap_in": [r6(w), r6(h)],
                      "overlap_box_in": box_in(box)},
            threshold={"max_overlap_in": 0},
            message=f"{label(top)!r} overlaps {label(under)!r} by {w:.3f} x {h:.3f} in.",
        )
        finding.evidence["crop"] = schematic_crop(
            ctx, "frame_overlap", f"{label(top)}__{label(under)}", [top], [under], region=box)
        findings.append(finding)
    pairs = [f"{f.object}/{f.measured['other']}" for f in findings]
    return finalize(
        "frame_overlap", "deterministic", findings, rules,
        "No text frame overlaps another text frame or a required frame.",
        f"{len(pairs)} overlapping pair(s): {', '.join(pairs)}.",
    )


@check(
    "min_type_size",
    category="geometry",
    description="No text below the minimum size in the pack; reports every run under it.",
    rules=("min_type_size",),
    explain=(
        "Resolves the font size of every text run (character, paragraph style and document "
        "defaults) and reports each run below the minimum with frame name and size. A rule "
        "sets min_pt for every frame (or only the frames in 'frames'), and/or per_frame "
        "minimums ({frame: pt}, wildcards and aliases allowed); a frame named in per_frame "
        "uses that value instead of min_pt."
    ),
    fix="Raise the reported runs to at least the minimum, making room by resizing the frame or trimming text.",
)
def min_type_size(ctx: Context) -> CheckResult:
    doc = ctx.doc
    rules = ctx.rules.all("min_type_size")
    findings: list[Finding] = []
    for rule in rules:
        default = rule.get("min_pt")
        scope = with_aliases(ctx, rule.get("frames") or [])
        per_frame = [(with_aliases(ctx, [k]), float(v))
                     for k, v in (rule.get("per_frame") or {}).items()]
        for f in printing_leaves(doc):
            if not f.is_text:
                continue
            specific = [v for names, v in per_frame if matches(f.name, names)]
            if specific:
                min_pt = max(specific)
            elif default is not None and (not scope or matches(f.name, scope)):
                min_pt = float(default)
            else:
                continue
            for i, run in enumerate(f.runs):
                if not run.text.strip() or run.size_pt >= min_pt - 1e-9:
                    continue
                findings.append(Finding.from_rule(
                    rule, label(f),
                    measured={"size_pt": run.size_pt, "run": i, "text": run.text[:40],
                              "font": run.font},
                    threshold={"min_pt": min_pt},
                    message=f"{run.size_pt:g} pt text in {label(f)!r} is under {min_pt:g} pt.",
                ))
    names = sorted({f.object for f in findings})
    return finalize(
        "min_type_size", "deterministic", findings, rules,
        "No text is below the minimum type size.",
        f"{len(findings)} text run(s) below the minimum size in: {', '.join(names)}.",
    )
