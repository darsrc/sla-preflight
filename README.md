# sla-preflight

A modular verification toolkit for print labels laid out in [Scribus](https://www.scribus.net/).
It reads a `.sla` file (and optionally the exported PDF), runs small independent
checks against rules kept in YAML, and returns results with evidence that a
person, a script, or a small local model can act on.

It exists because three real defects on one label job were caught by hand:

| Defect | Check that catches it |
|---|---|
| A 200-count label said "Servings Per Container: 60" (should be 100) | `facts_math` |
| A final PDF was exported with no bleed | `pdf_page_box` |
| A layout with 7 facts rows overprinted the manufacturer block | `frame_overlap`, `required_elements` |

## Principles

1. **One check = one small, independent function.** Each can run alone.
2. **Rules are data, not code.** Thresholds and requirements live in YAML rule
   packs. The same check serves different printers, brands and regulations by
   swapping packs.
3. **Deterministic and judgment checks are separate.** Deterministic checks get
   an exact answer from geometry, colour data, text or math. Judgment checks
   (v0.2) need a model, always return evidence crops, are labelled
   `kind: judgment`, and never pass a release on their own.
4. **Every result carries evidence**: object names, measured values, the
   threshold used, the rule and its source, and, where visual, a crop.
5. **Regulatory rules cite their source and start unverified.** A result from
   an unverified rule is reported as `warn`, never `pass` or `fail`. No model
   may write or paraphrase law into a rule pack.
6. **Small-model friendly surface.** The MCP server exposes three tools; all
   depth lives in the engine.
7. **Public engine, private rule packs.** Client brand packs, client files and
   client briefs never enter this repository (see [Keeping private things private](#keeping-private-things-private)).

## Install

Python 3.11+, and Scribus 1.6 for the two checks that need real text layout or
rendering (`frame_overflow`, `render_regression`). Without a display, Scribus
runs under `xvfb-run` automatically.

Those two checks need **the label's own fonts**. Scribus silently substitutes
missing fonts, which changes line breaks and makes overflow results wrong, so
both checks return `error` and name the missing fonts instead of guessing.
Install the fonts, or pass a folder holding them with `--fonts-dir` (or
`$SLA_PREFLIGHT_FONTS_DIR`).

```bash
sudo apt-get install scribus xvfb      # Debian/Ubuntu
pip install -e ".[test]"
```

## Use

```bash
sla-preflight run label.sla --profile print_label_final --pdf label.pdf --die 10.25x2.5
sla-preflight run label.sla --profile draft_review --brand-pack ~/private/packs/client.yaml
sla-preflight run label.sla --profile print_label_final --json      # full report
sla-preflight list [--profile print_label_final]
sla-preflight explain trim_safety
```

Exit codes: `0` pass, `1` warn, `2` fail, `3` error. Evidence images are
written to `--out` (default: a temporary folder named in the report).

Options for `run`: `--pdf`, `--die WxH` (this job's die size in inches; the die
is per job, not per printer), `--fonts-dir`, `--brand-pack` (replaces the
profile's brand pack),
`--approved-render` (PNG for `render_regression`), `--out`, `--check NAME`
(repeatable, run only these), `--json`.

## Checks (v0.1)

| Check | Reads | Rule id(s) |
|---|---|---|
| `page_matches_die` | .sla | `die` (job, from `--die`), `bleed` |
| `trim_safety` | .sla | `safe_margin` (+ `bleed_objects`) |
| `bleed_coverage` | .sla | `safe_margin` (`bleed_allowed`, + `bleed_objects`) |
| `frame_overflow` | .sla via Scribus | `no_text_overflow` |
| `frame_overlap` | .sla | `no_frame_overlap` (+ `required_elements`) |
| `min_type_size` | .sla | `min_type_size` |
| `pdf_page_box` | .sla + PDF | `pdf_bleed` |
| `pdf_fonts_outlined` | PDF | `pdf_fonts` |
| `pdf_color_space` | PDF | `pdf_color` |
| `required_elements` | .sla | `required_elements` (+ `no_frame_overlap`) |
| `facts_math` | .sla text | `facts_math` |
| `claim_disclaimer_pairing` | .sla text | `claim_disclaimer` |
| `element_placement` | .sla | `element_placement` |
| `facts_row_separators` | .sla | `facts_row_separators` |
| `min_x_height` | .sla + font files via Scribus | `min_x_height` |
| `render_regression` | .sla via Scribus + approved PNG | `render_regression` |

`sla-preflight explain <check>` says what each one checks, which rules it
reads, and how to fix a failure. Designed for v0.2 but not built:
`text_contrast`, `swatch_whitelist`, `fonts_available`, `brief_to_checklist`,
`brief_compliance` (listed by `sla-preflight list`, reported as `skipped`).

Checks find objects by their Scribus **name** (Properties > Name), so a layout
must name the frames its packs refer to (e.g. `manufacturer`, `serving_info`,
`lot_box`). Geometry uses exact XML values in points, including group scaling,
rotation and visible strokes. Also handled:

- **Master pages**: master items are checked on every page that uses the
  master (the result says `master_page`).
- **Multi-page documents**: each object is measured against its own page.
- **Linked text frames**: the story lives in the first frame of the chain; a
  continuation frame counts as filled when the chain has text, and overflow
  is reported only on the chain's last frame.
- **Styles**: font sizes are resolved through character and paragraph style
  chains, not just direct formatting.
- **Printer marks**: `pdf_page_box` measures bleed between TrimBox and
  BleedBox, so crop/bleed/registration marks do not cause false failures.

Not yet handled: Scribus 1.4 files, text on paths, tables, and non-rectangular
overlap (overlap uses bounding boxes, so rotated or shaped frames can report
an overlap that is not really there).

## Result schema

Every check returns:

```json
{
  "check": "trim_safety",
  "kind": "deterministic",
  "status": "fail",
  "summary": "1 object(s) too close to trim: manufacturer.",
  "findings": [
    {
      "object": "manufacturer",
      "measured": {"gap_bottom_in": 0.041},
      "threshold": {"min_gap_in": 0.0625},
      "rule": "printer/wizard_labels.yaml#safe_margin",
      "rule_source": "Wizard Labels prepress email, 2026-06-04",
      "rule_verified": true,
      "evidence": {"crop": "out/trim_safety/manufacturer.png"},
      "severity": "fail",
      "message": "'manufacturer' is closer than 0.0625 in to trim on the bottom side."
    }
  ]
}
```

- `status` is one of `pass`, `warn`, `fail`, `error`, `skipped`.
- `error` means the check could not run (missing file, bad rule pack,
  unparseable text), which is different from `fail`.
- `skipped` means an input it needs was not given (e.g. no PDF) or no loaded
  pack has its rule.
- `summary` is one sentence a small model can relay verbatim.

`run_checks` returns `{"status", "profile", "out_dir", "results": [...]}`. The
overall status is `fail` if any deterministic check fails, `error` if a check
could not run, `warn` if there are only warnings, otherwise `pass`.

## Rule packs

```
rules/
  printer/wizard_labels.yaml     # public example
  regulatory/us_supplement.yaml  # public; every rule verified: false until reviewed
  brand/example_brand.yaml       # public example only
profiles/
  print_label_final.yaml         # release gate: .sla + PDF
  draft_review.yaml              # fast layout/content review, no PDF or Scribus
```

A pack is a YAML file with a `kind` (`printer`, `regulatory` or `brand`) and a
list of rules. Every rule has `id`, `description`, `source`, `verified`, and,
once verified, `verified_by` and `verified_on`. Every other key is a
parameter the check reads:

```yaml
pack: printer/my_printer.yaml
kind: printer
description: Artwork requirements for My Printer.
rules:
  - id: safe_margin
    description: All non-bleed content at least this far inside trim.
    min_gap_in: 0.0625
    bleed_allowed: [bg_band, bar_top, bar_bottom, lot_box]
    source: "My Printer prepress email, 2026-06-04"
    verified: true
    verified_by: Your Name
    verified_on: 2026-09-28
```

Frame-name lists (`bleed_allowed`, `bleed_objects`, `frames`, `containers`,
`ignore`) accept shell wildcards: `Copy of bar_*`, `*background*`. A name also
matches every object inside a group of that name. Frames without a name are
reported by position, e.g. `unnamed text at (0.174, 1.983) in in group Group40`.

A brand pack can keep its template's own frame names: a `frame_aliases` rule
maps the names the regulatory pack uses (`statement_of_identity`,
`net_quantity`, `supplement_facts`) to the template's frames. Results then name
the template frame and record the name it was required as (`required_as`).

`facts_math` also handles weights ("NET 16 OZ (454 g)", "Serving Size: 1-2
Tablespoons (15 g)") and "About N" servings. When "About N" is within 1 of the
exact value, only the rounding is in question and the `facts_about_rounding`
rule judges it (and is cited); a larger difference, or no rounding rule, fails
under `facts_math`.

A rule id may carry a suffix after a dot (`min_type_size.facts`,
`min_type_size.other`): a check reads every rule whose id is its rule id or
starts with it plus a dot, so one pack can hold several rules for the same
check, each with its own source and verified status.

`min_x_height` measures the reference glyph's outline (overshoot included) in
the very font file Scribus renders the run with, so it needs Scribus and the
label's fonts. `facts_row_separators` counts a non-text shape as a hairline
when it is thinner than `max_rule_height_in` and spans most of the rows'
width; dot leaders are a tab with a `.` leader in the paragraph style, or
`...`/`…` in the text.

Rules are cited as `<pack>#<id>`. A check uses every loaded rule with its id,
so a brand pack and a regulatory pack can both require frames. The pack
loader refuses a rule with no source, a non-boolean `verified`, or
`verified: true` without `verified_by`/`verified_on`.

Parameters per rule id:

| Rule id | Parameters |
|---|---|
| `die` | not in packs: given per job with `--die WxH`, cited as `job#die` |
| `bleed` | `bleed_in`, `tolerance_in` |
| `safe_margin` | `min_gap_in`, `bleed_allowed` (frame names), `touch_tolerance_in` |
| `bleed_objects` | `frames`: a layout pack's own objects allowed to bleed (added to `bleed_allowed`) |
| `frame_aliases` | `aliases`: map names other packs use to this layout's frames, e.g. `{net_quantity: count}` |
| `facts_about_rounding` | `method` (`nearest` or `floor`): how "About N" servings may be rounded |
| `pdf_bleed` | `required`, `tolerance_in` |
| `pdf_fonts` | `fonts_outlined` |
| `pdf_color` | `color_space` (`CMYK`) |
| `no_text_overflow` | none |
| `no_frame_overlap` | `containers` (`[outer, inner]` pairs allowed to overlap), `ignore` |
| `min_type_size` | `min_pt` (optionally limited to `frames`) and/or `per_frame` (`{frame: pt}`) |
| `min_x_height` | `frames`, `min_in`, `glyph` (default `o`): ink height of the glyph from the font file x size x vertical scale |
| `element_placement` | `frame`, `panel` (frames whose union is the panel box), `positions` (`below`, `right`), `max_gap_in` |
| `facts_row_separators` | `rows_frames` (one row per frame, or paragraphs of a single frame), `dot_leaders_allowed`, `max_rule_height_in`, `min_span_fraction` |
| `required_elements` | `frames` |
| `facts_math` | `count_frame`, `serving_frame`, `count_pattern`, `serving_size_pattern`, `servings_pattern`, `about_pattern` (regexes; the first matching group is used, so one pattern can cover unit counts and grams) |
| `claim_disclaimer` | `claim_frames`, `disclaimer_frame` |
| `render_regression` | `dpi`, `pixel_threshold`, `max_changed_fraction` |

**Where packs are found:** folders listed in `$SLA_PREFLIGHT_RULES`
(separated by `:`) first, then this repo's `rules/`. Profiles likewise use
`$SLA_PREFLIGHT_PROFILES`, then `profiles/`. Keep client packs in a private
folder and point `--brand-pack` or `$SLA_PREFLIGHT_RULES` at it.

## Verifying a regulatory rule

Every rule in `rules/regulatory/` ships `verified: false`, and its results are
advisory `warn`s that cite the source. To verify one:

1. Open the cited section in the current eCFR (<https://www.ecfr.gov>). Read
   the actual text; do not rely on a summary or on a model.
2. Confirm the rule's `description` and parameters say what the text says,
   and nothing more. If they don't, fix the rule or split it.
3. Make the `source` precise (section and paragraph).
4. Set `verified: true`, `verified_by: <your name>`, `verified_on: <date>`,
   and commit that change on its own so the review is easy to audit.

Re-verify when the regulation is amended. Never let a model write or
paraphrase law into a pack.

## MCP server

`sla-preflight-mcp` runs a stdio MCP server (v1 FastMCP API, `mcp>=1.9,<2`)
with exactly three tools:

- `list_checks(profile=None)`: names, kind and one-line description.
- `run_checks(sla_path, profile, pdf_path=None, brand_pack=None, die=None)`:
  runs the profile, writes evidence crops to an output folder, returns the
  results plus an overall status. `die` is the job's die size, e.g. `"10.25x2.5"`.
- `explain(check)`: what it checks, which rules it reads, how to fix a failure.

Example client entry:

```json
{"mcpServers": {"sla-preflight": {"command": "sla-preflight-mcp"}}}
```

## Tests

```bash
xvfb-run -a python -m pytest -q        # or plain pytest; Scribus is started under xvfb-run itself
python tests/make_fixtures.py out/fixtures   # look at the synthetic fixtures
```

Fixtures are synthetic `.sla` files and PDFs generated by
`tests/make_fixtures.py` at test time, with dummy text only. Each failing
fixture changes one thing in a clean label to reproduce one defect class.
Tests that need Scribus are skipped when it is not installed. Some tests
export real PDFs through Scribus to check the PDF checks against genuine
exports (print-ready, no bleed, embedded fonts with RGB).

## Keeping private things private

`scripts/safety_check.py` scans every file in the git index and refuses:

- client names and other private patterns, read from a gitignored
  `.safety-patterns` file (one regex per line) or from
  `$SLA_PREFLIGHT_SAFETY_PATTERNS`; the patterns are never written in the repo;
- absolute user paths;
- artwork and client file types (`.sla`, `.pdf`, images, design files);
- brand packs other than the public example.

Turn it on as a pre-commit hook once per clone:

```bash
git config core.hooksPath .githooks
```

CI runs it with the patterns from the `SAFETY_PATTERNS` repository secret.
