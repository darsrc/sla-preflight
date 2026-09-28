"""Generate synthetic fixtures: .sla files, PDFs and packs for the tests.

Dummy text only. No client files, ever.

    python tests/make_fixtures.py OUT_DIR

Every fixture starts from one clean 4 x 2.5 in label (``base_label``) and
changes one thing, so each failing fixture isolates one defect class.
Coordinates are in inches, page-relative; the writer converts to the
Scribus 1.6 XML layout (points, canvas coordinates, page at 100,20).
"""
from __future__ import annotations

import copy
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

PT = 72.0
PAGE_X, PAGE_Y = 100.0, 20.0
FONT = "DejaVu Sans Book"

DIE_W, DIE_H, BLEED = 4.0, 2.5, 0.125


# --------------------------------------------------------------------- model
@dataclass
class Obj:
    name: str
    x: float
    y: float
    w: float
    h: float
    kind: str = "text"  # text | shape | group
    text: list[tuple[str, float]] = field(default_factory=list)  # (paragraph, size pt)
    layer: int = 0
    line_color: str | None = None
    line_width: float = 1.0
    fill: str | None = None
    rotation: float = 0.0
    children: list["Obj"] = field(default_factory=list)
    group_scale: tuple[float, float] = (1.0, 1.0)  # group resized after grouping
    page: int = 0
    para_style: str | None = None  # paragraph style; text sizes of None come from it
    link_to: str | None = None  # name of the next frame in a linked text chain


@dataclass
class Label:
    page_w: float = DIE_W
    page_h: float = DIE_H
    bleed: float = BLEED
    objects: list[Obj] = field(default_factory=list)
    layers: list[tuple[str, bool]] = field(default_factory=lambda: [("Background", True)])
    pages: int = 1
    # extra STYLE / CHARSTYLE elements: (tag, attributes)
    styles: list[tuple[str, dict]] = field(default_factory=list)
    masters: dict[str, list[Obj]] = field(default_factory=dict)
    page_master: dict[int, str] = field(default_factory=dict)  # page -> master name

    def get(self, name: str) -> Obj:
        for o in self._walk(self.objects):
            if o.name == name:
                return o
        raise KeyError(name)

    def remove(self, name: str) -> None:
        self.objects = [o for o in self.objects if o.name != name]

    def _walk_all(self):
        yield from self._walk(self.objects)
        for objs in self.masters.values():
            yield from self._walk(objs)

    def _walk(self, objs):
        for o in objs:
            yield o
            yield from self._walk(o.children)


def text(name, x, y, w, h, *paras, size=7.0, **kw) -> Obj:
    return Obj(name, x, y, w, h, "text", [(p, size) for p in paras], **kw)


def shape(name, x, y, w, h, **kw) -> Obj:
    kw.setdefault("fill", "White")
    return Obj(name, x, y, w, h, "shape", **kw)


def base_label() -> Label:
    """A clean 4 x 2.5 in label: passes every v0.1 check with the test packs."""
    b = BLEED
    return Label(objects=[
        shape("bg_band", -b, -b, DIE_W + 2 * b, DIE_H + 2 * b),
        shape("bar_top", -b, -b, DIE_W + 2 * b, 0.30 + b, fill="Black"),
        shape("bar_bottom", -b, 2.20, DIE_W + 2 * b, DIE_H + b - 2.20, fill="Black"),
        text("product_name", 0.30, 0.38, 3.40, 0.30, "Example Product", size=12),
        text("statement_of_identity", 0.30, 0.72, 1.90, 0.14, "Dietary Supplement", size=6),
        text("count", 0.30, 0.88, 1.90, 0.18, "200 Capsules", size=8),
        text("net_quantity", 0.30, 1.08, 1.90, 0.14, "Net Contents: 200 Capsules", size=6),
        text("serving_info", 0.30, 1.24, 1.90, 0.32,
             "Serving Size: 2 Capsules", "Servings Per Container: 100", size=7),
        text("claim", 0.30, 1.58, 1.90, 0.16, "Supports example wellness.*", size=7),
        text("disclaimer", 0.30, 1.76, 1.90, 0.36,
             "*These statements are placeholder text for testing.", size=6),
        shape("facts_box", 2.30, 0.72, 1.40, 1.43, fill="None", line_color="Black"),
        text("supplement_facts", 2.35, 0.77, 1.30, 1.33,
             "Supplement Facts", "Serving Size 2 Capsules",
             "Nutrient A 10 mg", "Nutrient B 20 mg", size=6),
        text("manufacturer", 0.30, 2.24, 2.60, 0.16, "Made for Example Co., Sample City", size=6),
        shape("lot_box", 3.00, 2.24, DIE_W + b - 3.00, DIE_H + b - 2.24),
        text("lot_text", 3.05, 2.26, 0.55, 0.14, "LOT 0000", size=6),
    ])


# --------------------------------------------------------------- SLA writer
def _attrs(**kw) -> dict[str, str]:
    return {k: (f"{v:g}" if isinstance(v, float) else str(v)) for k, v in kw.items()}


def _page_origin(label: Label, page: int) -> tuple[float, float]:
    """Canvas position of a page: pages are stacked vertically, 40 pt apart."""
    return PAGE_X, PAGE_Y + page * (label.page_h * PT + 40.0)


def _object_el(o: Obj, label: Label, ids: dict[str, int], linked_to: set[str],
               parent_origin_pt=None, tag="PAGEOBJECT", master: tuple[str, int] | None = None
               ) -> ET.Element:
    w, h = o.w * PT, o.h * PT
    if parent_origin_pt is not None:
        # group children: offset inside the (unscaled) group
        pos = dict(XPOS=0.0, YPOS=0.0,
                   gXpos=o.x * PT - parent_origin_pt[0], gYpos=o.y * PT - parent_origin_pt[1])
        own = master[1] if master else o.page
    else:
        # master items sit on their master page, which is drawn at the canvas origin
        px, py = (PAGE_X, PAGE_Y) if master else _page_origin(label, o.page)
        pos = dict(XPOS=px + o.x * PT, YPOS=py + o.y * PT, gXpos=0.0, gYpos=0.0)
        own = master[1] if master else o.page
    ptype = {"text": 4, "shape": 6, "group": 12}[o.kind]
    nxt = ids[o.link_to] if o.link_to else -1
    back = next((ids[k] for k, v in _links(label).items() if v == o.name), -1)
    a = _attrs(
        **pos, OwnPage=own, ItemID=ids[o.name], PTYPE=ptype, WIDTH=w, HEIGHT=h,
        ROT=float(o.rotation), ANNAME=o.name, LAYER=o.layer,
        PWIDTH=float(o.line_width), PCOLOR=o.fill or "None", PCOLOR2=o.line_color or "None",
        FRTYPE=0, CLIPEDIT=0, PLINEART=1, COLUMNS=1, COLGAP=0.0, AUTOTEXT=0,
        EXTRA=0.0, TEXTRA=0.0, BEXTRA=0.0, REXTRA=0.0, FLOP=1,
        path=f"M0 0 L{w:g} 0 L{w:g} {h:g} L0 {h:g} L0 0 Z",
        NEXTITEM=nxt, BACKITEM=back,
    )
    if master:
        a["OnMasterPage"] = master[0]
    el = ET.Element(tag, a)
    # continuation frames of a linked chain carry no story (Scribus stores it
    # in the first frame)
    if o.kind == "text" and o.name not in linked_to:
        st = ET.SubElement(el, "StoryText")
        # fixed line spacing of 1.2 x the largest size; Scribus' document
        # default is a fixed 15 pt, too loose for small label type
        sizes = [sz for _, sz in o.text if sz is not None]
        lsp = _attrs(LINESPMode=0, LINESP=1.2 * max(sizes, default=12.0))
        if o.para_style:
            lsp["PARENT"] = o.para_style
        ET.SubElement(st, "DefaultStyle", lsp)
        for i, (para, size) in enumerate(o.text):
            run = {"FONT": FONT, "CH": para}
            if size is not None:
                run["FONTSIZE"] = f"{float(size):g}"
            ET.SubElement(st, "ITEXT", run)
            ET.SubElement(st, "trail" if i == len(o.text) - 1 else "para", lsp)
        if not o.text:
            ET.SubElement(st, "trail")
    if o.kind == "group":
        sx, sy = o.group_scale
        # children given in *unscaled* page inches relative to the group's
        # origin at grouping time; the group was then resized by group_scale.
        el.set("groupWidth", f"{w / sx:g}")
        el.set("groupHeight", f"{h / sy:g}")
        for c in o.children:
            el.append(_object_el(c, label, ids, linked_to, (0.0, 0.0), master=master))
    return el


def _links(label: Label) -> dict[str, str]:
    return {o.name: o.link_to for o in label._walk_all() if o.link_to}


def write_sla(label: Label, path: Path) -> Path:
    root = ET.Element("SCRIBUSUTF8NEW", Version="1.6.1")
    w, h, b = label.page_w * PT, label.page_h * PT, label.bleed * PT
    doc = ET.SubElement(root, "DOCUMENT", _attrs(
        ANZPAGES=label.pages, PAGEWIDTH=w, PAGEHEIGHT=h, BORDERLEFT=0.0, BORDERRIGHT=0.0,
        BORDERTOP=0.0, BORDERBOTTOM=0.0, ORIENTATION=0, PAGESIZE="Custom", FIRSTNUM=1,
        BOOK=0, UNITS=0, DFONT=FONT, DSIZE=12.0,
        BleedTop=b, BleedLeft=b, BleedRight=b, BleedBottom=b,
    ))
    for name, c, m, y, k in (("Black", 0, 0, 0, 100), ("White", 0, 0, 0, 0)):
        ET.SubElement(doc, "COLOR", _attrs(NAME=name, SPACE="CMYK", C=c, M=m, Y=y, K=k))
    for tag, attrs in label.styles:
        ET.SubElement(doc, tag, {k: str(v) for k, v in attrs.items()})
    for i, (name, prints) in enumerate(label.layers):
        ET.SubElement(doc, "LAYERS", _attrs(
            NUMMER=i, LEVEL=i, NAME=name, SICHTBAR=1, DRUCKEN=int(prints), EDIT=1,
            SELECT=0, FLOW=1, TRANS=1.0, BLEND=0, OUTL=0, LAYERC="#000000"))
    masters = ["Normal"] + [m for m in label.masters if m != "Normal"]
    for i, name in enumerate(masters):
        ET.SubElement(doc, "MASTERPAGE", _attrs(
            PAGEXPOS=PAGE_X, PAGEYPOS=PAGE_Y, PAGEWIDTH=w, PAGEHEIGHT=h, BORDERLEFT=0.0,
            BORDERRIGHT=0.0, BORDERTOP=0.0, BORDERBOTTOM=0.0, NUM=i, NAM=name, MNAM="",
            Size="Custom", Orientation=0, LEFT=0))
    for n in range(label.pages):
        px, py = _page_origin(label, n)
        ET.SubElement(doc, "PAGE", _attrs(
            PAGEXPOS=px, PAGEYPOS=py, PAGEWIDTH=w, PAGEHEIGHT=h, BORDERLEFT=0.0,
            BORDERRIGHT=0.0, BORDERTOP=0.0, BORDERBOTTOM=0.0, NUM=n, NAM="",
            MNAM=label.page_master.get(n, "Normal"), Size="Custom", Orientation=0, LEFT=0))
    ids = {o.name: 1001 + i for i, o in enumerate(label._walk_all())}
    linked_to = set(_links(label).values())
    for name, objs in label.masters.items():
        for o in objs:
            doc.append(_object_el(o, label, ids, linked_to, tag="MASTEROBJECT",
                                  master=(name, masters.index(name))))
    for o in label.objects:
        doc.append(_object_el(o, label, ids, linked_to))
    ET.indent(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)
    return path


# --------------------------------------------------------------- PDF writer
def write_pdf(path: Path, width_in: float, height_in: float, *, font: bool = False,
              rgb: bool = False, rgb_image: bool = False, trimbox: bool = True) -> Path:
    """A one-page PDF shaped like a Scribus export: CMYK paths, no live
    text, unless a defect is switched on."""
    import pikepdf

    pdf = pikepdf.new()
    w, h = width_in * PT, height_in * PT
    ops = [b"0 0 0 1 k 10 10 50 20 re f"]
    res = pikepdf.Dictionary()
    if rgb:
        ops.append(b"1 0 0 rg 70 10 20 20 re f")
    if font:
        res.Font = pikepdf.Dictionary(F1=pikepdf.Dictionary(
            Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1,
            BaseFont=pikepdf.Name("/Helvetica")))
        ops.append(b"BT /F1 8 Tf 10 40 Td (Dummy) Tj ET")
    if rgb_image:
        img = pikepdf.Stream(pdf, b"\xff\x00\x00" * 4)
        img.Type, img.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
        img.Width, img.Height, img.BitsPerComponent = 2, 2, 8
        img.ColorSpace = pikepdf.Name.DeviceRGB
        res.XObject = pikepdf.Dictionary(Im1=img)
        ops.append(b"q 20 0 0 20 100 10 cm /Im1 Do Q")
    page = pikepdf.Dictionary(
        Type=pikepdf.Name.Page,
        MediaBox=[0, 0, w, h],
        Resources=res,
        Contents=pikepdf.Stream(pdf, b"\n".join(ops)),
    )
    if trimbox and width_in > DIE_W:
        b = (width_in - DIE_W) / 2 * PT
        page.TrimBox = [b, b, w - b, h - b]
        page.BleedBox = [0, 0, w, h]
    pdf.pages.append(pikepdf.Page(page))
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf.save(path)
    return path


# ------------------------------------------------------------------ catalog
def _variant(fn) -> Label:
    lab = base_label()
    fn(lab)
    return lab


def _facts_60(l: Label):
    # defect 1: 200 count labelled 60 servings (should be 100)
    l.get("serving_info").text = [("Serving Size: 2 Capsules", 7), ("Servings Per Container: 60", 7)]


def _facts_unparseable(l: Label):
    l.get("serving_info").text = [("Serving Size: two capsules", 7), ("Servings Per Container: many", 7)]


def _facts_7_rows(l: Label):
    # defect 3: seven facts rows push the facts panel over the manufacturer block
    rows = [f"Nutrient {c} 10 mg" for c in "ABCDEFG"]
    sf = l.get("supplement_facts")
    sf.text = [("Supplement Facts", 6), ("Serving Size 2 Capsules", 6)] + [(r, 6) for r in rows]
    sf.h = 1.58  # 0.77 .. 2.35, over manufacturer at 2.24 .. 2.40
    l.get("facts_box").h = 1.68


def _trim_manufacturer(l: Label):
    m = l.get("manufacturer")
    m.y = DIE_H - 0.041 - m.h  # bottom gap 0.041 in < 0.0625


def _trim_group_scaled(l: Label):
    # the child looks safe unscaled; the group was scaled 2x afterwards,
    # which pushes it to 0.05 in from the right trim edge
    l.remove("product_name")
    child = text("product_name", 0.0, 0.0, 0.90, 0.15, "Example Product", size=12)
    l.objects.append(Obj("name_group", 2.15, 0.38, 1.80, 0.30, "group",
                         children=[child], group_scale=(2.0, 2.0)))


def _trim_group_scaled_ok(l: Label):
    l.remove("product_name")
    child = text("product_name", 0.0, 0.0, 1.70, 0.15, "Example Product", size=12)
    l.objects.append(Obj("name_group", 0.30, 0.38, 3.40, 0.30, "group",
                         children=[child], group_scale=(2.0, 2.0)))


def _bleed_short(l: Label):
    # the top bar stops at trim instead of running into bleed
    bar = l.get("bar_top")
    bar.x, bar.y, bar.w, bar.h = 0.0, 0.0, DIE_W, 0.30


def _page_baked_bleed(l: Label):
    # bleed baked into the page size, document bleed set to zero
    l.page_w, l.page_h, l.bleed = DIE_W + 2 * BLEED, DIE_H + 2 * BLEED, 0.0


def _page_wrong_size(l: Label):
    l.page_w = DIE_W + 0.5


def _overflow(l: Label):
    l.get("disclaimer").text = [("*" + "These statements are placeholder text for testing. " * 12, 6)]


def _small_type(l: Label):
    l.get("disclaimer").text = [("*These statements are placeholder", 4.5), ("text for testing.", 5)]


def _overlap_text(l: Label):
    # claim slides down onto the disclaimer (neither in a container pair)
    l.get("claim").y = 1.70


def _missing_manufacturer(l: Label):
    l.remove("manufacturer")


def _missing_lot_box(l: Label):
    # the lot/expiration area is required, never omitted
    l.remove("lot_box")
    l.remove("lot_text")


def _page_no_doc_bleed(l: Label):
    # document bleed settings left at zero
    l.bleed = 0.0


def _manufacturer_hidden_layer(l: Label):
    l.layers.append(("Notes", False))
    l.get("manufacturer").layer = 1


def _manufacturer_empty(l: Label):
    l.get("manufacturer").text = []


def _claim_no_disclaimer(l: Label):
    l.get("disclaimer").text = []


def _no_claim_no_disclaimer(l: Label):
    l.get("claim").text = []
    l.get("disclaimer").text = []


def _style_small_type(l: Label):
    # 4.5 pt reached only through paragraph style -> character style
    l.styles += [("CHARSTYLE", {"CNAME": "tiny", "FONTSIZE": "4.5"}),
                 ("STYLE", {"NAME": "fine_print", "CPARENT": "tiny"})]
    d = l.get("disclaimer")
    d.para_style = "fine_print"
    d.text = [(t, None) for t, _ in d.text]


def _style_ok_type(l: Label):
    l.styles += [("CHARSTYLE", {"CNAME": "small", "FONTSIZE": "6.5"}),
                 ("STYLE", {"NAME": "fine_print", "CPARENT": "small"})]
    d = l.get("disclaimer")
    d.para_style = "fine_print"
    d.text = [(t, None) for t, _ in d.text]


def _rotated_ok(l: Label):
    # unrotated this would run 0.2 in past the right trim; rotated 90 degrees
    # clockwise about its top-left it hangs down inside the safe area
    l.objects.append(text("badge", 3.30, 0.38, 0.90, 0.20, "NEW", size=8, rotation=90.0))


def _rotated_near_trim(l: Label):
    # rotated 270 degrees it points up, through the top trim edge
    l.objects.append(text("badge", 3.30, 0.38, 0.90, 0.20, "NEW", size=8, rotation=270.0))


def _two_pages(l: Label):
    # page 2 reuses page 1's coordinates (no overlap across pages) and has
    # one frame too close to trim
    l.pages = 2
    c = l.get("claim")
    l.objects += [
        text("back_text", c.x, c.y, c.w, c.h, "Back panel text", size=7, page=1),
        text("back_edge", 0.02, 1.00, 1.00, 0.15, "Too close", size=7, page=1),
    ]


def _to_master(l: Label, *names: str, extra: tuple = ()) -> None:
    """Move frames onto master page 'Label' (drawn beneath page items), with
    the background band, as a real layout would keep it."""
    moved = [l.get(n) for n in ("bg_band",) + names]
    for n in ("bg_band",) + names:
        l.remove(n)
    l.masters["Label"] = moved + list(extra)
    l.page_master[0] = "Label"


def _master_note_near_trim(l: Label):
    _to_master(l, extra=(text("master_note", 0.02, 1.00, 0.20, 0.15, "M", size=7),))


def _manufacturer_on_master(l: Label):
    _to_master(l, "manufacturer")


def _linked(l: Label, words: str):
    m = l.get("manufacturer")
    l.remove("manufacturer")
    head = text("manufacturer_head", 0.30, m.y, 1.25, m.h, words, size=6)
    head.link_to = "manufacturer"
    l.objects += [head, text("manufacturer", 1.65, m.y, 1.25, m.h, size=6)]


def _linked_manufacturer(l: Label):
    _linked(l, "Made for Example Co., 1 Example Way, Sample City")


def _linked_overflow(l: Label):
    _linked(l, "Made for Example Co., 1 Example Way, Sample City. " * 6)


def _render_moved(l: Label):
    l.get("lot_text").x += 0.10


SLA_FIXTURES = {
    "good": lambda l: None,
    "facts_60_servings": _facts_60,
    "facts_unparseable": _facts_unparseable,
    "facts_7_rows_overlap": _facts_7_rows,
    "trim_manufacturer": _trim_manufacturer,
    "trim_group_scaled": _trim_group_scaled,
    "trim_group_scaled_ok": _trim_group_scaled_ok,
    "bleed_short_bar": _bleed_short,
    "page_baked_bleed": _page_baked_bleed,
    "page_wrong_size": _page_wrong_size,
    "text_overflow": _overflow,
    "small_type": _small_type,
    "text_overlap": _overlap_text,
    "missing_manufacturer": _missing_manufacturer,
    "manufacturer_hidden_layer": _manufacturer_hidden_layer,
    "missing_lot_box": _missing_lot_box,
    "page_no_doc_bleed": _page_no_doc_bleed,
    "manufacturer_empty": _manufacturer_empty,
    "claim_no_disclaimer": _claim_no_disclaimer,
    "no_claim_no_disclaimer": _no_claim_no_disclaimer,
    "render_moved": _render_moved,
    "style_small_type": _style_small_type,
    "style_ok_type": _style_ok_type,
    "rotated_ok": _rotated_ok,
    "rotated_near_trim": _rotated_near_trim,
    "two_pages": _two_pages,
    "master_note_near_trim": _master_note_near_trim,
    "manufacturer_on_master": _manufacturer_on_master,
    "linked_manufacturer": _linked_manufacturer,
    "linked_overflow": _linked_overflow,
}

FULL_W, FULL_H = DIE_W + 2 * BLEED, DIE_H + 2 * BLEED
PDF_FIXTURES = {
    "good": dict(width_in=FULL_W, height_in=FULL_H),
    # defect 2: final PDF exported with no bleed
    "no_bleed": dict(width_in=DIE_W, height_in=DIE_H),
    "live_font": dict(width_in=FULL_W, height_in=FULL_H, font=True),
    "rgb_fill": dict(width_in=FULL_W, height_in=FULL_H, rgb=True),
    "rgb_image": dict(width_in=FULL_W, height_in=FULL_H, rgb_image=True),
}


def build_all(out: Path) -> dict[str, dict[str, Path]]:
    out = Path(out)
    sla = {n: write_sla(_variant(fn), out / "sla" / f"{n}.sla") for n, fn in SLA_FIXTURES.items()}
    pdf = {n: write_pdf(out / "pdf" / f"{n}.pdf", **kw) for n, kw in PDF_FIXTURES.items()}
    return {"sla": sla, "pdf": pdf}


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "out/fixtures")
    made = build_all(target)
    for kind, files in made.items():
        for name, p in files.items():
            print(f"{kind:4} {name:28} {p}")
