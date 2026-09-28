"""Schema, rule packs, profiles, registry and surfaces (no check logic)."""
import json
from pathlib import Path

import pytest
import yaml

from sla_preflight import api, registry
from sla_preflight.cli import main as cli_main
from sla_preflight.profiles import load_packs, load_profile
from sla_preflight.result import CheckResult, Finding, finalize, overall_status
from sla_preflight.rules import Rule, RulePackError, load_pack
from sla_preflight.sla import parse_sla

REPO = Path(__file__).resolve().parent.parent
V01 = [
    "page_matches_die", "trim_safety", "bleed_coverage", "frame_overflow", "frame_overlap",
    "min_type_size", "pdf_page_box", "pdf_fonts_outlined", "pdf_color_space",
    "required_elements", "facts_math", "claim_disclaimer_pairing", "render_regression",
]
V02 = ["text_contrast", "swatch_whitelist", "fonts_available", "brief_to_checklist", "brief_compliance"]


def rule(verified=True):
    return Rule("r", "d", "Some source", verified, "x" if verified else None,
                "2026-01-01" if verified else None, {}, "printer/p.yaml", "printer")


# ------------------------------------------------------------ result schema
def test_result_dict_matches_schema():
    r = rule()
    res = finalize("trim_safety", "deterministic",
                   [Finding.from_rule(r, "manufacturer", measured={"gap_bottom_in": 0.041},
                                      threshold={"min_gap_in": 0.0625},
                                      evidence={"crop": "out/trim_safety/manufacturer.png"})],
                   [r], "ok", "bad")
    d = res.to_dict()
    assert set(d) == {"check", "kind", "status", "summary", "findings"}
    f = d["findings"][0]
    assert f["object"] == "manufacturer"
    assert f["rule"] == "printer/p.yaml#r"
    assert f["rule_source"] == "Some source" and f["rule_verified"] is True
    json.dumps(d)  # serialisable


def test_verified_violation_fails():
    r = rule()
    assert finalize("c", "deterministic", [Finding.from_rule(r, "o")], [r], "ok", "bad").status == "fail"


def test_unverified_violation_is_warn_never_fail():
    r = rule(verified=False)
    res = finalize("c", "deterministic", [Finding.from_rule(r, "o")], [r], "ok", "bad")
    assert res.status == "warn"


def test_unverified_clean_is_warn_never_pass_and_cites_source():
    r = rule(verified=False)
    res = finalize("c", "deterministic", [], [r], "ok", "bad")
    assert res.status == "warn"
    assert res.findings and res.findings[0].rule_source == "Some source"


def test_judgment_never_passes_alone():
    r = rule()
    assert finalize("c", "judgment", [], [r], "ok", "bad").status == "warn"


def test_bad_status_rejected():
    with pytest.raises(ValueError):
        CheckResult("c", "deterministic", "ok", "s")


@pytest.mark.parametrize("statuses,kinds,expected", [
    (["pass", "pass"], None, "pass"),
    (["pass", "warn"], None, "warn"),
    (["warn", "fail"], None, "fail"),
    (["pass", "error"], None, "error"),
    (["fail", "error"], None, "fail"),
    (["pass", "skipped"], None, "pass"),
    (["fail"], ["judgment"], "warn"),
])
def test_overall_status(statuses, kinds, expected):
    kinds = kinds or ["deterministic"] * len(statuses)
    rs = [CheckResult(f"c{i}", k, s, "x") for i, (s, k) in enumerate(zip(statuses, kinds))]
    assert overall_status(rs) == expected


# --------------------------------------------------------------- rule packs
def write(tmp_path, data):
    p = tmp_path / "pack.yaml"
    p.write_text(yaml.safe_dump(data))
    return p


GOOD_RULE = {"id": "a", "description": "d", "source": "s", "verified": False}


@pytest.mark.parametrize("data,msg", [
    ({"kind": "nope", "rules": [GOOD_RULE]}, "kind"),
    ({"kind": "brand", "rules": []}, "non-empty"),
    ({"kind": "brand", "rules": [{"id": "a", "description": "d", "verified": False}]}, "source"),
    ({"kind": "brand", "rules": [{**GOOD_RULE, "verified": "yes"}]}, "true or false"),
    ({"kind": "brand", "rules": [{**GOOD_RULE, "verified": True}]}, "verified_by"),
    ({"kind": "brand", "rules": [GOOD_RULE, GOOD_RULE]}, "duplicate"),
    ({"kind": "brand", "rules": [{**GOOD_RULE, "source": " "}]}, "empty source"),
])
def test_pack_validation(tmp_path, data, msg):
    with pytest.raises(RulePackError, match=msg):
        load_pack(write(tmp_path, data))


def test_pack_params_are_everything_but_metadata(tmp_path):
    pack = load_pack(write(tmp_path, {"kind": "printer", "rules": [
        {**GOOD_RULE, "min_gap_in": 0.0625, "bleed_allowed": ["x"]}]}), name="printer/t.yaml")
    r = pack.rules[0]
    assert r.params == {"min_gap_in": 0.0625, "bleed_allowed": ["x"]}
    assert r.ref == "printer/t.yaml#a"


def test_shipped_packs_load():
    for p in (REPO / "rules").rglob("*.yaml"):
        load_pack(p)


def test_regulatory_rules_all_unverified_with_source():
    pack = load_pack(REPO / "rules/regulatory/us_supplement.yaml")
    assert pack.kind == "regulatory"
    for r in pack.rules:
        assert r.verified is False, r.id
        assert "CFR" in r.source, r.id


def test_profiles_load_and_reference_real_checks():
    for name in ("print_label_final", "draft_review", "test_final", "test_regulatory"):
        prof = load_profile(name)
        load_packs(prof)
        for c in prof.checks:
            registry.get(c)


def test_brand_pack_replaces_profile_brand_pack(tmp_path):
    p = write(tmp_path, {"kind": "brand", "rules": [GOOD_RULE]})
    rs = load_packs(load_profile("test_final"), brand_pack=p)
    kinds = [pk.kind for pk in rs.packs]
    assert kinds.count("brand") == 1 and rs.packs[-1].path == p


def test_brand_pack_must_be_brand(tmp_path):
    p = write(tmp_path, {"kind": "printer", "rules": [GOOD_RULE]})
    with pytest.raises(RulePackError):
        load_packs(load_profile("test_final"), brand_pack=p)


# ----------------------------------------------------------------- registry
def test_every_v01_check_registered():
    names = [c.name for c in registry.all_checks()]
    assert names == V01


def test_v02_checks_designed_not_built():
    for n in V02:
        spec = registry.get(n)
        assert spec.deferred and spec.func is None


def test_check_rules_exist_in_shipped_or_test_packs():
    ids = set()
    for p in list((REPO / "rules").rglob("*.yaml")) + list((REPO / "tests/rules").rglob("*.yaml")):
        ids |= {r.id for r in load_pack(p).rules}
    for spec in registry.all_checks():
        for r in spec.rules:
            assert r in ids, (spec.name, r)


def test_explain_has_what_rules_and_fix():
    for n in V01:
        e = api.explain(n)
        assert e["what_it_checks"] and e["how_to_fix"] and e["rules_read"]


def test_list_checks_by_profile():
    names = [c["name"] for c in api.list_checks("draft_review")]
    assert names == load_profile("draft_review").checks


# ------------------------------------------------------------------ runner
def test_pdf_checks_skip_without_pdf(fx):
    rep = api.run_checks(fx["sla"]["good"], "test_final", only=["pdf_page_box"])
    assert rep["results"][0]["status"] == "skipped"


def test_bad_profile_is_error():
    rep = api.run_checks("x.sla", "no_such_profile")
    assert rep["status"] == "error"


def test_deferred_check_is_skipped(tmp_path, fx):
    from sla_preflight.context import Context
    from sla_preflight.rules import RuleSet
    from sla_preflight.runner import run_one

    ctx = Context(Path(fx["sla"]["good"]), RuleSet([]), tmp_path)
    assert run_one(registry.get("swatch_whitelist"), ctx).status == "skipped"


# ---------------------------------------------------------------- surfaces
def test_cli_list_and_explain(capsys):
    assert cli_main(["list"]) == 0
    assert "trim_safety" in capsys.readouterr().out
    assert cli_main(["explain", "facts_math"]) == 0
    assert json.loads(capsys.readouterr().out)["name"] == "facts_math"


def test_mcp_exposes_exactly_three_tools():
    import asyncio

    from sla_preflight.mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    assert sorted(t.name for t in tools) == ["explain", "list_checks", "run_checks"]


# -------------------------------------------------------------- SLA parser
def test_fixtures_parse(fx):
    for name, p in fx["sla"].items():
        doc = parse_sla(p)
        assert doc.pages and doc.frames, name


def test_scaled_group_child_geometry(fx):
    doc = parse_sla(fx["sla"]["trim_group_scaled"])
    (child,) = doc.find("product_name")
    x0, y0, x1, y1 = (v / 72 for v in child.bbox())
    assert (round(x0, 6), round(x1, 6)) == (2.15, 3.95)  # 0.90 in wide, scaled 2x
    assert child.parent == "name_group"


def test_font_sizes_resolved(fx):
    doc = parse_sla(fx["sla"]["small_type"])
    (f,) = doc.find("disclaimer")
    assert sorted({r.size_pt for r in f.runs if r.text.strip()}) == [4.5, 5.0]
