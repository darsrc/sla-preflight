"""Read a Scribus .sla file into plain geometry and text.

All geometry is in points (1/72 in), relative to the top-left of the
object's page, taken from the exact XML values (never rounded display
values). Group children are placed with the scaled-group math Scribus uses:
a group stores its size at grouping time (``groupWidth``/``groupHeight``);
if the group was resized afterwards, each child's offset and size scale by
``WIDTH / groupWidth`` and ``HEIGHT / groupHeight``.

Targets the Scribus 1.5/1.6 format (``SCRIBUSUTF8NEW``).
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

PT_PER_IN = 72.0

PTYPES = {
    2: "image",
    4: "text",
    5: "line",
    6: "polygon",
    7: "polyline",
    8: "pathtext",
    9: "latex",
    10: "osg",
    11: "symbol",
    12: "group",
    13: "regular_polygon",
    14: "arc",
    15: "spiral",
    16: "table",
    17: "note",
}


class SlaError(Exception):
    """The file is missing or is not a readable Scribus document."""


def pt_to_in(v: float) -> float:
    return v / PT_PER_IN


@dataclass
class TextRun:
    text: str
    font: str | None
    size_pt: float


@dataclass
class Layer:
    number: int
    name: str
    printable: bool
    visible: bool


@dataclass
class Page:
    index: int
    x: float  # canvas position of the page's top-left, points
    y: float
    width: float
    height: float


@dataclass
class Frame:
    name: str
    item_id: str | None
    ptype: int
    page: int | None
    x: float  # page-relative, points, after group scaling
    y: float
    width: float
    height: float
    rotation: float
    layer: int
    line_color: str | None
    line_width: float
    fill_color: str | None
    parent: str | None = None
    runs: list[TextRun] = field(default_factory=list)
    next_item: str | None = None  # linked text frames: ItemID of the next frame
    back_item: str | None = None  # ItemID of the previous frame in the chain
    master: str | None = None  # name of the master page this item comes from
    children: list["Frame"] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return PTYPES.get(self.ptype, f"ptype{self.ptype}")

    @property
    def is_text(self) -> bool:
        return self.ptype == 4

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    def bbox(self) -> tuple[float, float, float, float]:
        """Axis-aligned box (x0, y0, x1, y1) of the frame shape, rotation
        included (Scribus rotates clockwise about the item's top-left)."""
        if not self.rotation:
            return (self.x, self.y, self.x + self.width, self.y + self.height)
        a = math.radians(self.rotation)
        c, s = math.cos(a), math.sin(a)
        pts = [
            (self.x + px * c - py * s, self.y + px * s + py * c)
            for px, py in ((0, 0), (self.width, 0), (self.width, self.height), (0, self.height))
        ]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    def ink_bbox(self) -> tuple[float, float, float, float]:
        """Like bbox() but including half of a visible stroke, which prints
        outside the frame edge."""
        x0, y0, x1, y1 = self.bbox()
        h = self.line_width / 2 if self.line_color not in (None, "None") else 0.0
        return (x0 - h, y0 - h, x1 + h, y1 + h)


@dataclass
class Document:
    path: Path
    version: str
    pages: list[Page]
    layers: dict[int, Layer]
    bleed: dict[str, float]  # top/left/right/bottom, points
    frames: list[Frame]  # top-level items in document order

    def all_frames(self) -> list[Frame]:
        """Every item, group children included, depth-first."""
        out: list[Frame] = []

        def walk(fs: list[Frame]) -> None:
            for f in fs:
                out.append(f)
                walk(f.children)

        walk(self.frames)
        return out

    def text_frames(self) -> list[Frame]:
        return [f for f in self.all_frames() if f.is_text]

    def find(self, name: str) -> list[Frame]:
        return [f for f in self.all_frames() if f.name == name]

    def chain_head(self, frame: Frame) -> Frame:
        """First frame of a linked text chain (Scribus stores the whole
        story there; continuation frames carry no text of their own)."""
        by_id = {f.item_id: f for f in self.all_frames() if f.item_id}
        cur, seen = frame, set()
        while cur.back_item and cur.back_item in by_id and cur.item_id not in seen:
            seen.add(cur.item_id)
            cur = by_id[cur.back_item]
        return cur

    def has_text(self, frame: Frame) -> bool:
        """Non-text frames count as filled. A frame in a linked chain counts
        as filled when the chain's story has text (which part of the story
        lands in which frame needs Scribus layout, see frame_overflow)."""
        if not frame.is_text:
            return True
        return bool(self.chain_head(frame).text.strip())

    def layer_printable(self, frame: Frame) -> bool:
        layer = self.layers.get(frame.layer)
        return True if layer is None else layer.printable


def _f(el: ET.Element, key: str, default: float = 0.0) -> float:
    v = el.get(key)
    if v in (None, ""):
        return default
    return float(v)


class _Styles:
    """Resolve character attributes (font size, font) the way Scribus does:

    run attributes > run's character style chain > paragraph: its own
    attributes > its character style (CPARENT) chain > its parent paragraph
    style (PARENT) chain > the frame's default style likewise > the
    document's default paragraph and character styles > DOCUMENT DSIZE/DFONT.
    """

    DEFAULT_PARA = "Default Paragraph Style"
    DEFAULT_CHAR = "Default Character Style"

    def __init__(self, doc_el: ET.Element):
        self.default_size = _f(doc_el, "DSIZE", 12.0)
        self.default_font = doc_el.get("DFONT")
        self.para = {s.get("NAME"): s for s in doc_el.findall("STYLE")}
        self.char = {s.get("CNAME"): s for s in doc_el.findall("CHARSTYLE")}

    def _char_chain(self, name: str | None, key: str) -> str | None:
        for _ in range(20):
            st = self.char.get(name) if name else None
            if st is None:
                return None
            if st.get(key) not in (None, ""):
                return st.get(key)
            name = st.get("CPARENT") or st.get("PARENT")
        return None

    def _para_chain(self, name: str | None, key: str) -> str | None:
        for _ in range(20):
            st = self.para.get(name) if name else None
            if st is None:
                return None
            if st.get(key) not in (None, ""):
                return st.get(key)
            v = self._char_chain(st.get("CPARENT"), key)
            if v is not None:
                return v
            name = st.get("PARENT")
        return None

    def resolve(self, key: str, el: ET.Element | None, para_style: ET.Element | None,
                default_style: ET.Element | None) -> str | None:
        if el is not None:
            if el.get(key) not in (None, ""):
                return el.get(key)
            v = self._char_chain(el.get("CPARENT"), key)
            if v is not None:
                return v
        for src in (para_style, default_style):
            if src is None:
                continue
            if src.get(key) not in (None, ""):
                return src.get(key)
            v = self._char_chain(src.get("CPARENT"), key)
            if v is None:
                v = self._para_chain(src.get("PARENT"), key)
            if v is not None:
                return v
        v = self._para_chain(self.DEFAULT_PARA, key)
        if v is None:
            v = self._char_chain(self.DEFAULT_CHAR, key)
        return v


def _parse_story(obj: ET.Element, styles: _Styles) -> list[TextRun]:
    story = obj.find("StoryText")
    if story is None:
        return []
    default_style = story.find("DefaultStyle")
    runs: list[TextRun] = []
    pending: list[ET.Element] = []  # ITEXT waiting for their paragraph end

    def flush(para_el: ET.Element | None, newline: bool) -> None:
        for el in pending:
            size = styles.resolve("FONTSIZE", el, para_el, default_style)
            font = styles.resolve("FONT", el, para_el, default_style)
            runs.append(TextRun(
                el.get("CH", ""),
                font or styles.default_font,
                float(size) if size is not None else styles.default_size,
            ))
        pending.clear()
        if newline:
            runs.append(TextRun("\n", None, 0.0))

    for el in story:
        tag = el.tag
        if tag == "ITEXT":
            pending.append(el)
        elif tag == "para":
            flush(el, newline=True)
        elif tag == "trail":
            flush(el, newline=False)
        elif tag == "tab":
            pending.append(ET.Element("ITEXT", {**el.attrib, "CH": "\t"}))
        elif tag == "breakline":
            pending.append(ET.Element("ITEXT", {**el.attrib, "CH": "\n"}))
    flush(None, newline=False)
    # zero-size marker runs only carry line breaks
    return runs


def _parse_object(
    obj: ET.Element,
    styles: _Styles,
    pages: list[Page],
    origin: tuple[float, float] | None,
    scale: tuple[float, float],
    parent: str | None,
    page_override: Page | None = None,
) -> Frame:
    ptype = int(_f(obj, "PTYPE", -1))
    if origin is None:
        # top-level: XPOS/YPOS are canvas coordinates; make page-relative
        own = int(_f(obj, "OwnPage", -1))
        page = page_override or (pages[own] if 0 <= own < len(pages) else None)
        px, py = (page.x, page.y) if page else (0.0, 0.0)
        x = _f(obj, "XPOS") - px
        y = _f(obj, "YPOS") - py
        page_idx = own if page else None
    else:
        # group child: offset inside the group, scaled with the group
        x = origin[0] + _f(obj, "gXpos") * scale[0]
        y = origin[1] + _f(obj, "gYpos") * scale[1]
        page_idx = None
    w = _f(obj, "WIDTH") * scale[0]
    h = _f(obj, "HEIGHT") * scale[1]
    frame = Frame(
        name=obj.get("ANNAME") or "",
        item_id=obj.get("ItemID"),
        ptype=ptype,
        page=page_idx,
        x=x,
        y=y,
        width=w,
        height=h,
        rotation=_f(obj, "ROT"),
        layer=int(_f(obj, "LAYER", 0)),
        line_color=obj.get("PCOLOR2"),
        line_width=_f(obj, "PWIDTH", 1.0) * min(scale),
        fill_color=obj.get("PCOLOR"),
        parent=parent,
        next_item=_link(obj.get("NEXTITEM")),
        back_item=_link(obj.get("BACKITEM")),
    )
    if ptype == 4:
        frame.runs = _parse_story(obj, styles)
    if ptype == 12:
        gw = _f(obj, "groupWidth", 0.0) or _f(obj, "WIDTH")
        gh = _f(obj, "groupHeight", 0.0) or _f(obj, "HEIGHT")
        sx = scale[0] * (_f(obj, "WIDTH") / gw if gw else 1.0)
        sy = scale[1] * (_f(obj, "HEIGHT") / gh if gh else 1.0)
        for child in obj.findall("PAGEOBJECT"):
            c = _parse_object(child, styles, pages, (x, y), (sx, sy), frame.name or parent)
            c.page = page_idx if origin is None else c.page
            frame.children.append(c)
        _propagate_page(frame, frame.page)
    return frame


def _link(v: str | None) -> str | None:
    return None if v in (None, "", "-1") else v


def _propagate_page(frame: Frame, page: int | None) -> None:
    for c in frame.children:
        c.page = page
        _propagate_page(c, page)


def parse_sla(path: str | Path) -> Document:
    p = Path(path)
    if not p.is_file():
        raise SlaError(f"SLA file not found: {p}")
    try:
        root = ET.parse(p).getroot()
    except ET.ParseError as e:
        raise SlaError(f"{p.name}: not valid XML: {e}") from e
    if root.tag != "SCRIBUSUTF8NEW":
        raise SlaError(f"{p.name}: not a Scribus 1.5/1.6 document (root <{root.tag}>)")
    doc_el = root.find("DOCUMENT")
    if doc_el is None:
        raise SlaError(f"{p.name}: no <DOCUMENT> element")
    styles = _Styles(doc_el)
    pages = [
        Page(
            index=int(_f(pg, "NUM", i)),
            x=_f(pg, "PAGEXPOS"),
            y=_f(pg, "PAGEYPOS"),
            width=_f(pg, "PAGEWIDTH"),
            height=_f(pg, "PAGEHEIGHT"),
        )
        for i, pg in enumerate(doc_el.findall("PAGE"))
    ]
    pages.sort(key=lambda pg: pg.index)
    layers = {
        int(_f(l, "NUMMER")): Layer(
            number=int(_f(l, "NUMMER")),
            name=l.get("NAME", ""),
            printable=l.get("DRUCKEN", "1") == "1",
            visible=l.get("SICHTBAR", "1") == "1",
        )
        for l in doc_el.findall("LAYERS")
    }
    bleed = {
        "top": _f(doc_el, "BleedTop"),
        "left": _f(doc_el, "BleedLeft"),
        "right": _f(doc_el, "BleedRight"),
        "bottom": _f(doc_el, "BleedBottom"),
    }
    frames = [
        _parse_object(o, styles, pages, None, (1.0, 1.0), None)
        for o in doc_el.findall("PAGEOBJECT")
    ]
    # Master page items print on every page that uses the master, beneath
    # the page's own items. They are placed relative to their master page.
    masters = {
        m.get("NAM", ""): Page(int(_f(m, "NUM")), _f(m, "PAGEXPOS"), _f(m, "PAGEYPOS"),
                               _f(m, "PAGEWIDTH"), _f(m, "PAGEHEIGHT"))
        for m in doc_el.findall("MASTERPAGE")
    }
    master_objs: dict[str, list[ET.Element]] = {}
    for o in doc_el.findall("MASTEROBJECT"):
        master_objs.setdefault(o.get("OnMasterPage", ""), []).append(o)
    master_frames: list[Frame] = []
    for i, pg_el in enumerate(doc_el.findall("PAGE")):
        mname = pg_el.get("MNAM", "")
        if mname not in masters or mname not in master_objs:
            continue
        page_index = int(_f(pg_el, "NUM", i))
        for o in master_objs[mname]:
            f = _parse_object(o, styles, pages, None, (1.0, 1.0), None,
                              page_override=masters[mname])
            f.page = page_index
            _propagate_page(f, page_index)
            _mark_master(f, mname)
            master_frames.append(f)
    return Document(p, root.get("Version", ""), pages, layers, bleed, master_frames + frames)


def _mark_master(frame: Frame, name: str) -> None:
    frame.master = name
    for c in frame.children:
        _mark_master(c, name)
