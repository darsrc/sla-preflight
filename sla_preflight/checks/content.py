"""Content checks, read from the .sla text (deterministic)."""
from __future__ import annotations

import re

from ..context import Context
from ..registry import check
from ..result import CheckResult, Finding, finalize
from ._common import CheckInputError, overlap_pairs, schematic_crop


def _state(ctx: Context, name: str) -> tuple[str, object]:
    """('ok'|'missing'|'off_page'|'not_printing'|'empty', frame or None).
    When several frames share a name, the best one counts."""
    doc = ctx.doc
    cands = doc.find(name)
    if not cands:
        return "missing", None
    order = ["ok", "empty", "not_printing", "off_page"]
    best = None
    for f in cands:
        if f.page is None:
            st = "off_page"
        elif not doc.layer_printable(f):
            st = "not_printing"
        elif not doc.has_text(f):
            st = "empty"
        else:
            st = "ok"
        if best is None or order.index(st) < order.index(best[0]):
            best = (st, f)
    return best


def doc_text(ctx: Context, frame) -> str:
    """Text of a frame's story (the chain head's, for linked frames)."""
    return ctx.doc.chain_head(frame).text


PROBLEM_TEXT = {
    "missing": "is missing",
    "off_page": "is not on a page",
    "not_printing": "is on a non-printing layer",
    "empty": "is empty",
}


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
    rules = ctx.rules.all("required_elements")
    pairs = overlap_pairs(ctx)
    findings: list[Finding] = []
    for rule in rules:
        for name in rule.get("frames", []) or []:
            st, frame = _state(ctx, name)
            thr = {"required": True, "printing": True, "non_empty": True, "overlapped": False}
            if st != "ok":
                findings.append(Finding.from_rule(
                    rule, name, measured={"problem": st}, threshold=thr,
                    message=f"Required frame {name!r} {PROBLEM_TEXT[st]}.",
                ))
                continue
            for p in pairs:
                if frame not in (p["top"], p["under"]):
                    continue
                other = p["under"] if frame is p["top"] else p["top"]
                f = Finding.from_rule(
                    rule, name, measured={"problem": "overlapped", "other": other.name},
                    threshold=thr,
                    message=f"Required frame {name!r} is overlapped by {other.name!r}.",
                )
                f.evidence["crop"] = schematic_crop(
                    ctx, "required_elements", f"{name}__{other.name}", [frame], [other],
                    region=p["box"])
                findings.append(f)
    names = sorted({f.object for f in findings})
    return finalize(
        "required_elements", "deterministic", findings, rules,
        "Every required frame is present, printing, filled and clear.",
        f"{len(names)} required frame(s) have problems: {', '.join(names)}.",
    )


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
    rules = ctx.rules.all("facts_math")
    findings: list[Finding] = []

    def text_of(name: str) -> str:
        st, frame = _state(ctx, name)
        if st != "ok":
            raise CheckInputError(f"frame {name!r} {PROBLEM_TEXT[st]}; cannot check the math")
        return doc_text(ctx, frame)

    def number(pattern: str, text: str, what: str, frame: str) -> int:
        m = re.search(pattern, text)
        if not m:
            raise CheckInputError(f"could not parse {what} from {frame!r}: {text[:60]!r}")
        return int(m.group(1).replace(",", ""))

    for rule in rules:
        cf = rule.get("count_frame", "count")
        sf = rule.get("serving_frame", "serving_info")
        count_text, serving_text = text_of(cf), text_of(sf)
        count = number(rule["count_pattern"], count_text, "the unit count", cf)
        size = number(rule["serving_size_pattern"], serving_text, "the serving size", sf)
        stated = number(rule["servings_pattern"], serving_text, "servings per container", sf)
        if size <= 0:
            raise CheckInputError(f"serving size in {sf!r} is {size}")
        expected = count / size
        exp = int(expected) if expected == int(expected) else round(expected, 3)
        if stated != expected:
            findings.append(Finding.from_rule(
                rule, sf,
                measured={"count": count, "serving_size": size, "servings_stated": stated,
                          "servings_expected": exp, "count_frame": cf},
                threshold={"formula": "servings = count / serving_size"},
                message=(f"{count} / {size} = {exp} servings, but the label says {stated}."
                         if expected == int(expected) else
                         f"{count} is not divisible by serving size {size} ({exp}); label says {stated}."),
            ))
    f0 = findings[0] if findings else None
    return finalize(
        "facts_math", "deterministic", findings, rules,
        "Servings per container matches count / serving size.",
        f"Servings per container is wrong: {f0.message}" if f0 else "",
    )


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
    rules = ctx.rules.all("claim_disclaimer")
    findings: list[Finding] = []
    for rule in rules:
        claims = [n for n in rule.get("claim_frames", []) or [] if _state(ctx, n)[0] == "ok"]
        if not claims:
            continue
        disc = rule["disclaimer_frame"]
        st, frame = _state(ctx, disc)
        if st == "ok":
            continue
        findings.append(Finding.from_rule(
            rule, disc, measured={"problem": st, "claims_with_text": claims},
            threshold={"disclaimer_required_when_claims": True},
            message=f"Claim text in {', '.join(map(repr, claims))} but disclaimer {disc!r} {PROBLEM_TEXT[st]}.",
        ))
    return finalize(
        "claim_disclaimer_pairing", "deterministic", findings, rules,
        "Claims (if any) are paired with a filled disclaimer.",
        findings[0].message if findings else "",
    )
