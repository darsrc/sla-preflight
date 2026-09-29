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
    ("page_matches_die", "page_baked_bleed", None, "fail", {"page 1"}, "job#die"),
    ("page_matches_die", "page_baked_bleed", None, "fail", {"document bleed"}, f"{PRINTER}#bleed"),
    ("page_matches_die", "page_wrong_size", None, "fail", {"page 1"}, "job#die"),
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
    # font size reached only through paragraph style -> character style
    ("min_type_size", "style_ok_type", None, "pass", None, None),
    ("min_type_size", "style_small_type", None, "fail", {"disclaimer"}, f"{BRAND}#min_type_size"),
    # rotation decides whether the frame is inside the safe area
    ("trim_safety", "rotated_ok", None, "pass", None, None),
    ("trim_safety", "rotated_near_trim", None, "fail", {"badge"}, f"{PRINTER}#safe_margin"),
    # multi-page: problems found on page 2; same coordinates on different pages don't overlap
    ("page_matches_die", "two_pages", None, "pass", None, None),
    ("trim_safety", "two_pages", None, "fail", {"back_edge"}, f"{PRINTER}#safe_margin"),
    ("frame_overlap", "two_pages", None, "pass", None, None),
    # master page items are checked on the pages that use them
    ("trim_safety", "master_note_near_trim", None, "fail", {"master_note"}, f"{PRINTER}#safe_margin"),
    ("required_elements", "manufacturer_on_master", None, "pass", None, None),
    ("bleed_coverage", "manufacturer_on_master", None, "pass", None, None),
    # per-frame minimum sizes (test_layout pack: serving_info >= 7 pt)
    ("min_type_size", "serving_small", None, "fail", {"serving_info"}, "brand/test_layout.yaml#min_type_size.per_frame"),
    # placement immediately below / right of the facts panel
    ("element_placement", "placement_below", None, "pass", None, None),
    ("element_placement", "placement_right", None, "pass", None, None),
    ("element_placement", "placement_away", None, "fail", {"other_ingredients"}, "brand/test_layout.yaml#element_placement"),
    ("element_placement", "placement_gap", None, "fail", {"other_ingredients"}, "brand/test_layout.yaml#element_placement"),
    # hairlines between facts rows, or dot leaders
    ("facts_row_separators", "rows_hairlines", None, "pass", None, None),
    ("facts_row_separators", "rows_missing_hairline", None, "fail", {"fact_row_1, fact_row_2, fact_row_3"},
     "brand/test_layout.yaml#facts_row_separators"),
    ("facts_row_separators", "rows_block_hairlines", None, "pass", None, None),
    ("facts_row_separators", "rows_block_none", None, "fail", {"fact_rows_block"}, "brand/test_layout.yaml#facts_row_separators"),
    ("facts_row_separators", "rows_block_tab_leaders", None, "pass", None, None),
    ("facts_row_separators", "rows_block_literal_dots", None, "pass", None, None),
    ("facts_row_separators", "rows_block_plain_tabs", None, "fail", {"fact_rows_block"}, "brand/test_layout.yaml#facts_row_separators"),
    # a required frame that continues a linked text chain is not empty
    ("required_elements", "linked_manufacturer", None, "pass", None, None),
    ("frame_overlap", "linked_manufacturer", None, "pass", None, None),
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


DIE = "4x2.5"  # the fixtures' die, given at run time like a real job


def run_one(fx, check, sla, pdf=None, tmp_path=None, **kw):
    kw.setdefault("die", DIE)
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
        # a frame may be required by more than one pack; the expected rule
        # must be among those cited, and every citation must be complete
        assert any(f["rule"] == rule for f in failing), failing
        assert all(f["rule_source"] and f["rule_verified"] is True for f in failing), failing
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
    # linked chain: only the last frame of an overflowing chain is reported
    ("linked_manufacturer", "pass", None),
    ("linked_overflow", "fail", {"manufacturer"}),
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


@requires_scribus
@pytest.mark.parametrize("export,expected", [
    ("print_ready", {"pdf_page_box": "pass", "pdf_fonts_outlined": "pass", "pdf_color_space": "pass"}),
    ("no_bleed", {"pdf_page_box": "fail", "pdf_fonts_outlined": "pass", "pdf_color_space": "pass"}),
    ("embedded_rgb", {"pdf_fonts_outlined": "fail", "pdf_color_space": "fail"}),
    # crop marks enlarge the MediaBox; the bleed is still judged correctly
    ("marks_bleed", {"pdf_page_box": "pass"}),
    ("marks_no_bleed", {"pdf_page_box": "fail"}),
])
def test_pdf_checks_on_real_scribus_exports(fx, scribus_pdfs, tmp_path, export, expected):
    rep = run_checks(fx["sla"]["good"], "test_final", pdf_path=scribus_pdfs[export],
                     out_dir=tmp_path, only=list(expected))
    got = {r["check"]: r["status"] for r in rep["results"]}
    assert got == expected, rep["results"]


@requires_scribus
def test_linked_overflow_names_only_the_last_frame(fx, tmp_path):
    res = run_one(fx, "frame_overflow", "linked_overflow", tmp_path=tmp_path)
    assert {f["object"] for f in res["findings"]} == {"manufacturer"}


@requires_scribus
def test_confined_font_folder(fx, tmp_path):
    """Scribus runs with only the fonts in a given folder."""
    import shutil
    from pathlib import Path

    from sla_preflight.scribus import render_png, text_overflows

    src = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if not src.is_file():
        pytest.skip("DejaVu Sans not installed")
    fonts = tmp_path / "fonts"
    fonts.mkdir()
    shutil.copy(src, fonts)
    assert text_overflows(fx["sla"]["text_overflow"], fonts_dir=fonts)["disclaimer"] is True
    assert render_png(fx["sla"]["good"], tmp_path / "r.png", dpi=72, fonts_dir=fonts).is_file()


def test_page_matches_die_without_die_checks_bleed_only(fx, tmp_path):
    res = run_one(fx, "page_matches_die", "good", tmp_path=tmp_path, die=None)
    assert res["status"] == "pass" and "no die given" in res["summary"]
    res = run_one(fx, "page_matches_die", "page_no_doc_bleed", tmp_path=tmp_path, die=None)
    assert res["status"] == "fail"
    assert {f["object"] for f in res["findings"]} == {"document bleed"}


def test_wrong_die_fails(fx, tmp_path):
    res = run_one(fx, "page_matches_die", "good", tmp_path=tmp_path, die="10.25x2.5")
    assert res["status"] == "fail"
    assert res["findings"][0]["rule"] == "job#die"
    assert res["findings"][0]["rule_verified"] is True


def test_bleed_objects_patterns_from_a_layout_pack(fx, tmp_path):
    """Frame-name lists take wildcards, and a layout (brand) pack can name
    its own bleed objects."""
    res = run_one(fx, "trim_safety", "renamed_bleed", tmp_path=tmp_path)
    assert res["status"] == "fail" and "Copy of bar_top" in named(res)
    pack = tmp_path / "layout.yaml"
    pack.write_text(
        "kind: brand\nrules:\n"
        "  - id: bleed_objects\n    description: Bleed objects in this layout.\n"
        "    frames: ['Copy of *']\n    source: test\n    verified: true\n"
        "    verified_by: tests\n    verified_on: 2026-09-28\n")
    for check in ("trim_safety", "bleed_coverage"):
        res = run_one(fx, check, "renamed_bleed", tmp_path=tmp_path, brand_pack=pack)
        assert res["status"] == "pass", res


def test_unnamed_frames_are_labelled_by_position(fx, tmp_path):
    res = run_one(fx, "min_type_size", "unnamed_small_type", tmp_path=tmp_path)
    assert res["status"] == "fail"
    assert {f["object"] for f in res["findings"]} == {"unnamed text at (0.300, 1.760) in"}


@requires_scribus
@pytest.mark.parametrize("check", ["frame_overflow", "render_regression"])
def test_scribus_checks_refuse_missing_fonts(fx, tmp_path, approved_render, check):
    """Scribus silently substitutes missing fonts, which changes the layout;
    the check must say so instead of reporting false overflow or changes."""
    res = run_one(fx, check, "missing_font", tmp_path=tmp_path, approved_render=approved_render)
    assert res["status"] == "error", res
    assert "Nonexistent Sans Regular" in res["summary"]


GEL_PACK = """kind: brand
rules:
  - id: facts_math
    description: Servings equal net quantity / serving size (capsules or grams).
    count_frame: count
    serving_frame: serving_info
    count_pattern: '(?i)\\((\\d+(?:\\.\\d+)?)\\s*g\\)|(\\d[\\d,]*)\\s*capsules'
    serving_size_pattern: '(?i)serving\\s+size\\s*:?[^\\n(]*\\((\\d+(?:\\.\\d+)?)\\s*g\\)|serving\\s+size\\s*:?\\s*(\\d+)'
    servings_pattern: '(?i)servings\\s+per\\s+container\\s*:?\\s*(?:about\\s+)?(\\d+)'
    source: test
    verified: true
    verified_by: tests
    verified_on: 2026-09-28
%s"""
ABOUT_RULE = """  - id: facts_about_rounding
    description: About N rounds to the nearest whole serving.
    method: nearest
    source: test (unverified)
    verified: false
"""


@pytest.mark.parametrize("fixture,with_about,status,rule_id", [
    ("facts_gel_about_30", True, "warn", "facts_about_rounding"),   # rounding OK, rule unverified
    ("facts_gel_about_31", True, "warn", "facts_about_rounding"),   # rounding wrong, rule unverified
    ("facts_gel_about_60", True, "fail", "facts_math"),             # math wrong: a real failure
    ("facts_gel_about_30", False, "fail", "facts_math"),            # no rounding rule: strict
    ("good", True, "pass", None),                                    # capsules unaffected
])
def test_facts_math_grams_and_about(fx, tmp_path, fixture, with_about, status, rule_id):
    pack = tmp_path / "gel.yaml"
    pack.write_text(GEL_PACK % (ABOUT_RULE if with_about else ""))
    res = run_one(fx, "facts_math", fixture, tmp_path=tmp_path, brand_pack=pack)
    assert res["status"] == status, res
    if rule_id:
        assert any(f["rule"].endswith("#" + rule_id) for f in res["findings"]), res


def test_frame_aliases_map_other_packs_names(fx, tmp_path):
    """A brand pack maps the regulatory pack's names to template names."""
    def problems(res):
        return {f["measured"]["required_as"] for f in res["findings"] if f.get("measured", {}).get("problem")}

    rep = run_checks(fx["sla"]["template_names"], "test_regulatory", out_dir=tmp_path,
                     only=["required_elements"])
    assert problems(rep["results"][0]) == {"statement_of_identity", "net_quantity", "supplement_facts"}
    pack = tmp_path / "aliases.yaml"
    pack.write_text(
        "kind: brand\nrules:\n  - id: frame_aliases\n    description: template names\n"
        "    aliases: {statement_of_identity: tagline, net_quantity: net_text, "
        "supplement_facts: facts_rows}\n"
        "    source: test\n    verified: true\n    verified_by: tests\n    verified_on: 2026-09-29\n")
    rep = run_checks(fx["sla"]["template_names"], "test_regulatory", out_dir=tmp_path,
                     brand_pack=pack, only=["required_elements"])
    res = rep["results"][0]
    assert res["status"] == "warn" and problems(res) == set(), res  # unverified pack, but clean
    # a missing aliased frame is reported under the template's name
    rep = run_checks(fx["sla"]["missing_manufacturer"], "test_regulatory", out_dir=tmp_path,
                     brand_pack=pack, only=["required_elements"])
    objs = {f["object"] for f in rep["results"][0]["findings"] if f.get("measured", {}).get("problem")}
    assert "manufacturer" in objs


@requires_scribus
@pytest.mark.parametrize("sla,status,sizes", [
    ("good", "pass", None),
    ("small_type", "fail", [4.5, 5.0]),      # 4.5 and 5 pt DejaVu Sans: o under 0.04 in
    ("xheight_scaled", "fail", [6.0]),       # 6 pt squashed to 70 %
])
def test_min_x_height(fx, tmp_path, sla, status, sizes):
    res = run_one(fx, "min_x_height", sla, tmp_path=tmp_path)
    assert_result(res, status, {"disclaimer"} if sizes else None, "brand/test_layout.yaml#min_x_height")
    if sizes:
        assert sorted(f["measured"]["size_pt"] for f in res["findings"]) == sizes
        for f in res["findings"]:
            assert f["measured"]["x_height_in"] < 0.04 and f["measured"]["glyph"] == "o"


@requires_scribus
def test_x_height_matches_the_font_outline(fx, tmp_path):
    """The measured height comes from the font file: DejaVu Sans 'o' ink
    height is 1147 + 29 = 1176 units of 2048 per em (overshoot included)."""
    from sla_preflight.checks.layout import glyph_height

    em, y0, y1 = glyph_height("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "o")
    assert round(em * 2048) == 1176 and round(y0 * 2048) == -29
    res = run_one(fx, "min_x_height", "small_type", tmp_path=tmp_path)
    f45 = [f for f in res["findings"] if f["measured"]["size_pt"] == 4.5][0]
    assert f45["measured"]["x_height_in"] == pytest.approx(1176 / 2048 * 4.5 / 72, abs=1e-6)


def test_dot_leaders_only_when_allowed(fx, tmp_path):
    pack = tmp_path / "strict.yaml"
    pack.write_text(
        "kind: brand\nrules:\n  - id: facts_row_separators\n    description: hairlines only\n"
        "    rows_frames: [fact_rows_block]\n    dot_leaders_allowed: false\n"
        "    source: test\n    verified: true\n    verified_by: tests\n    verified_on: 2026-09-29\n")
    res = run_one(fx, "facts_row_separators", "rows_block_tab_leaders", tmp_path=tmp_path, brand_pack=pack)
    assert res["status"] == "fail"
