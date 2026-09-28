"""Spec section 9: the three real defects, and unverified regulatory rules."""
from sla_preflight.api import run_checks

PRINTER = "printer/test_printer.yaml"
BRAND = "brand/example_brand.yaml"


def failing(rep, check):
    (res,) = [r for r in rep["results"] if r["check"] == check]
    return res


def objects(res):
    return {f.get("object") for f in res["findings"]} | {
        f.get("measured", {}).get("other") for f in res["findings"]}


def test_defect_servings_60_for_200_count(fx, tmp_path):
    rep = run_checks(fx["sla"]["facts_60_servings"], "test_final", out_dir=tmp_path,
                     only=["facts_math"])
    assert rep["status"] == "fail"
    res = failing(rep, "facts_math")
    assert res["status"] == "fail" and "serving_info" in objects(res)
    assert res["findings"][0]["rule"] == f"{BRAND}#facts_math"


def test_defect_pdf_without_bleed(fx, tmp_path):
    rep = run_checks(fx["sla"]["good"], "test_final", pdf_path=fx["pdf"]["no_bleed"],
                     out_dir=tmp_path, only=["pdf_page_box"])
    assert rep["status"] == "fail"
    res = failing(rep, "pdf_page_box")
    assert res["findings"][0]["rule"] == f"{PRINTER}#pdf_bleed"


def test_defect_facts_overprint_manufacturer(fx, tmp_path):
    rep = run_checks(fx["sla"]["facts_7_rows_overlap"], "test_final", out_dir=tmp_path,
                     only=["frame_overlap", "required_elements"])
    assert rep["status"] == "fail"
    for check, rule in (("frame_overlap", "no_frame_overlap"), ("required_elements", "required_elements")):
        res = failing(rep, check)
        assert res["status"] == "fail" and "manufacturer" in objects(res), check
        assert any(f["rule"] == f"{BRAND}#{rule}" for f in res["findings"])


def test_regulatory_results_are_warn_with_source(fx, tmp_path):
    for fixture in ("good", "missing_manufacturer", "claim_no_disclaimer"):
        rep = run_checks(fx["sla"][fixture], "test_regulatory", out_dir=tmp_path)
        for res in rep["results"]:
            assert res["status"] == "warn", (fixture, res)
            assert res["findings"], (fixture, res)
            for f in res["findings"]:
                assert f["rule"].startswith("regulatory/us_supplement.yaml#")
                assert "CFR" in f["rule_source"] and f["rule_verified"] is False
