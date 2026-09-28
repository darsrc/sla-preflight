"""Every v0.1 check: one passing fixture and at least one failing fixture
that reproduces the defect class. Fixtures come from make_fixtures.py."""
import pytest

from conftest import requires_scribus
from sla_preflight.api import run_checks

PRINTER = "printer/test_printer.yaml"
BRAND = "brand/example_brand.yaml"

# (check, sla fixture, pdf fixture, expected status, objects named, rule ref)
CASES = [
    ("page_matches_die", "good", None, "pass", None, None),
    ("page_matches_die", "page_baked_bleed", None, "fail", {"page 1"}, f"{PRINTER}#die"),
    ("page_matches_die", "page_wrong_size", None, "fail", {"page 1"}, f"{PRINTER}#die"),
    ("trim_safety", "good", None, "pass", None, None),
    ("trim_safety", "trim_group_scaled_ok", None, "pass", None, None),
    ("trim_safety", "trim_manufacturer", None, "fail", {"manufacturer"}, f"{PRINTER}#safe_margin"),
    ("trim_safety", "trim_group_scaled", None, "fail", {"product_name"}, f"{PRINTER}#safe_margin"),
    ("bleed_coverage", "good", None, "pass", None, None),
    ("bleed_coverage", "bleed_short_bar", None, "fail", {"bar_top"}, f"{PRINTER}#safe_margin"),
    ("frame_overlap", "good", None, "pass", None, None),
    ("frame_overlap", "text_overlap", None, "fail", {"claim", "disclaimer"}, f"{BRAND}#no_frame_overlap"),
    ("frame_overlap", "facts_7_rows_overlap", None, "fail", {"supplement_facts", "manufacturer"},
     f"{BRAND}#no_frame_overlap"),
    ("min_type_size", "good", None, "pass", None, None),
    ("min_type_size", "small_type", None, "fail", {"disclaimer"}, f"{BRAND}#min_type_size"),
    ("pdf_page_box", "good", "good", "pass", None, None),
    ("pdf_page_box", "good", "no_bleed", "fail", {"page 1"}, f"{PRINTER}#pdf_bleed"),
    ("pdf_fonts_outlined", "good", "good", "pass", None, None),
    ("pdf_fonts_outlined", "good", "live_font", "fail", {"Helvetica"}, f"{PRINTER}#pdf_fonts"),
    ("pdf_color_space", "good", "good", "pass", None, None),
    ("pdf_color_space", "good", "rgb_fill", "fail", {"page 1"}, f"{PRINTER}#pdf_color"),
    ("pdf_color_space", "good", "rgb_image", "fail", {"Im1"}, f"{PRINTER}#pdf_color"),
    ("required_elements", "good", None, "pass", None, None),
    ("required_elements", "missing_manufacturer", None, "fail", {"manufacturer"}, f"{BRAND}#required_elements"),
    ("required_elements", "manufacturer_hidden_layer", None, "fail", {"manufacturer"},
     f"{BRAND}#required_elements"),
    ("required_elements", "manufacturer_empty", None, "fail", {"manufacturer"}, f"{BRAND}#required_elements"),
    ("required_elements", "missing_lot_box", None, "fail", {"lot_box"}, f"{PRINTER}#required_elements"),
    ("pdf_page_box", "page_no_doc_bleed", "good", "fail", {"page 1"}, f"{PRINTER}#pdf_bleed"),
    ("required_elements", "facts_7_rows_overlap", None, "fail", {"manufacturer"}, f"{BRAND}#required_elements"),
    ("facts_math", "good", None, "pass", None, None),
    ("facts_math", "facts_60_servings", None, "fail", {"serving_info"}, f"{BRAND}#facts_math"),
    ("facts_math", "facts_unparseable", None, "error", None, None),
    ("claim_disclaimer_pairing", "good", None, "pass", None, None),
    ("claim_disclaimer_pairing", "no_claim_no_disclaimer", None, "pass", None, None),
    ("claim_disclaimer_pairing", "claim_no_disclaimer", None, "fail", {"disclaimer"}, f"{BRAND}#claim_disclaimer"),
]


def named(result):
    """Every object a result's findings point at (object, or the other
    frame of an overlapping pair)."""
    out = set()
    for f in result["findings"]:
        if f.get("object"):
            out.add(f["object"])
        other = f.get("measured", {}).get("other")
        if other:
            out.add(other)
    return out


def run_one(fx, check, sla, pdf=None, tmp_path=None, **kw):
    rep = run_checks(fx["sla"][sla], "test_final", pdf_path=fx["pdf"][pdf] if pdf else None,
                     out_dir=tmp_path, only=[check], **kw)
    (res,) = rep["results"]
    return res


def assert_result(res, status, objects, rule):
    assert "not implemented" not in res["summary"], res["summary"]
    assert res["status"] == status, res["summary"]
    assert res["summary"]
    if objects:
        assert objects <= named(res), (objects, res["findings"])
        failing = [f for f in res["findings"] if f.get("object") in objects or
                   f.get("measured", {}).get("other") in objects]
        assert all(f["rule"] == rule and f["rule_source"] and f["rule_verified"] is True
                   for f in failing), failing
        assert all("measured" in f and "threshold" in f for f in failing), failing


@pytest.mark.parametrize("check,sla,pdf,status,objects,rule", CASES,
                         ids=[f"{c[0]}-{c[1]}-{c[2] or 'nopdf'}" for c in CASES])
def test_check(fx, tmp_path, check, sla, pdf, status, objects, rule):
    assert_result(run_one(fx, check, sla, pdf, tmp_path), status, objects, rule)


def test_min_type_size_reports_every_run(fx, tmp_path):
    res = run_one(fx, "min_type_size", "small_type", tmp_path=tmp_path)
    sizes = sorted(f["measured"]["size_pt"] for f in res["findings"])
    assert sizes == [4.5, 5.0]


def test_trim_safety_uses_exact_values(fx, tmp_path):
    res = run_one(fx, "trim_safety", "trim_manufacturer", tmp_path=tmp_path)
    (f,) = [f for f in res["findings"] if f["object"] == "manufacturer"]
    assert f["measured"]["gap_bottom_in"] == pytest.approx(0.041, abs=1e-9)
    assert f["threshold"]["min_gap_in"] == 0.0625


def test_facts_math_reports_expected_value(fx, tmp_path):
    res = run_one(fx, "facts_math", "facts_60_servings", tmp_path=tmp_path)
    (f,) = res["findings"]
    assert f["measured"]["servings_stated"] == 60
    assert f["measured"]["servings_expected"] == 100


def test_missing_sla_is_error(tmp_path):
    rep = run_checks(tmp_path / "nope.sla", "test_final", only=["trim_safety"])
    (res,) = rep["results"]
    assert res["status"] == "error" and "not found" in res["summary"], res["summary"]


# ------------------------------------------------------- need real Scribus
@requires_scribus
@pytest.mark.parametrize("sla,status,objects", [
    ("good", "pass", None),
    ("text_overflow", "fail", {"disclaimer"}),
])
def test_frame_overflow(fx, tmp_path, sla, status, objects):
    res = run_one(fx, "frame_overflow", sla, tmp_path=tmp_path)
    assert_result(res, status, objects, f"{BRAND}#no_text_overflow")


@requires_scribus
@pytest.mark.parametrize("sla,status,objects", [
    ("good", "pass", None),
    ("render_moved", "fail", {"lot_text"}),
])
def test_render_regression(fx, tmp_path, approved_render, sla, status, objects):
    res = run_one(fx, "render_regression", sla, tmp_path=tmp_path, approved_render=approved_render)
    assert_result(res, status, objects, f"{BRAND}#render_regression")
    if status == "fail":
        assert any(f.get("evidence", {}).get("crop") for f in res["findings"])
