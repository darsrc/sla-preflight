"""Rule packs: thresholds and requirements as data (spec section 4).

A pack is a YAML file::

    pack: printer/wizard_labels      # optional; defaults to the file's path
    kind: printer                    # printer | regulatory | brand
    description: ...
    rules:
      - id: safe_margin
        description: All non-bleed content at least this far inside trim.
        min_gap_in: 0.0625           # any other key is a parameter
        source: "..."
        verified: true
        verified_by: ...
        verified_on: 2026-09-28

Rules are referenced as ``<pack>#<id>``, e.g. ``printer/wizard_labels.yaml#safe_margin``.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PACK_KINDS = ("printer", "regulatory", "brand")
RULE_META_KEYS = ("id", "description", "source", "verified", "verified_by", "verified_on")


class RulePackError(Exception):
    """A rule pack is missing, malformed, or breaks the pack contract."""


@dataclass
class Rule:
    id: str
    description: str
    source: str
    verified: bool
    verified_by: str | None
    verified_on: str | None
    params: dict[str, Any]
    pack: str
    pack_kind: str

    @property
    def ref(self) -> str:
        return f"{self.pack}#{self.id}"

    def __getitem__(self, key: str) -> Any:
        return self.params[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.params.get(key, default)


@dataclass
class RulePack:
    name: str
    kind: str
    description: str
    path: Path
    rules: list[Rule] = field(default_factory=list)

    def by_id(self, rule_id: str) -> Rule | None:
        for r in self.rules:
            if r.id == rule_id:
                return r
        return None


def _rule_from_dict(d: dict, pack: str, kind: str, where: str) -> Rule:
    if not isinstance(d, dict):
        raise RulePackError(f"{where}: rule entry must be a mapping")
    missing = [k for k in ("id", "description", "source", "verified") if k not in d]
    if missing:
        raise RulePackError(f"{where}: rule {d.get('id', '?')!r} missing {', '.join(missing)}")
    if not isinstance(d["verified"], bool):
        raise RulePackError(f"{where}: rule {d['id']!r} 'verified' must be true or false")
    if not str(d["source"]).strip():
        raise RulePackError(f"{where}: rule {d['id']!r} has an empty source")
    if d["verified"] and not (d.get("verified_by") and d.get("verified_on")):
        raise RulePackError(
            f"{where}: rule {d['id']!r} is verified but lacks verified_by/verified_on"
        )
    if kind == "regulatory" and d["verified"] and not d.get("verified_by"):
        raise RulePackError(f"{where}: regulatory rule {d['id']!r} verified without a reviewer")
    von = d.get("verified_on")
    if isinstance(von, (_dt.date, _dt.datetime)):
        von = von.isoformat()
    params = {k: v for k, v in d.items() if k not in RULE_META_KEYS}
    return Rule(
        id=str(d["id"]),
        description=str(d["description"]),
        source=str(d["source"]),
        verified=d["verified"],
        verified_by=d.get("verified_by"),
        verified_on=von,
        params=params,
        pack=pack,
        pack_kind=kind,
    )


def load_pack(path: str | Path, name: str | None = None) -> RulePack:
    """Load and validate one pack. ``name`` is the reference prefix used in
    results; it defaults to the file name."""
    p = Path(path)
    if not p.is_file():
        raise RulePackError(f"rule pack not found: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RulePackError(f"{p.name}: invalid YAML: {e}") from e
    if not isinstance(data, dict):
        raise RulePackError(f"{p.name}: pack must be a mapping with a 'rules' list")
    kind = data.get("kind")
    if kind not in PACK_KINDS:
        raise RulePackError(f"{p.name}: 'kind' must be one of {', '.join(PACK_KINDS)}")
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        raise RulePackError(f"{p.name}: 'rules' must be a non-empty list")
    pack_name = name or data.get("pack") or p.name
    parsed = [_rule_from_dict(r, pack_name, kind, p.name) for r in rules]
    ids = [r.id for r in parsed]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise RulePackError(f"{p.name}: duplicate rule ids: {', '.join(sorted(dupes))}")
    return RulePack(pack_name, kind, str(data.get("description", "")), p, parsed)


def parse_die(text: str) -> tuple[float, float]:
    """'10.25x2.5', '10.25 x 2.5 in' -> (10.25, 2.5) inches."""
    import re

    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[xX\u00d7]\s*(\d+(?:\.\d+)?)\s*(?:in|\")?\s*", text or "")
    if not m:
        raise RulePackError(f"die must look like 10.25x2.5 (inches), got {text!r}")
    w, h = float(m.group(1)), float(m.group(2))
    if w <= 0 or h <= 0:
        raise RulePackError(f"die size must be positive, got {text!r}")
    return w, h


def job_pack(die: str | None = None, tolerance_in: float = 0.001) -> RulePack | None:
    """Job-level settings given at run time (the die is per job, not per
    printer). Cited as ``job#die``; verified because the person running the
    check states it for this job."""
    if not die:
        return None
    w, h = parse_die(die)
    today = _dt.date.today().isoformat()
    rule = Rule(
        id="die", description="Die size for this job (given at run time).",
        source=f"job setting: die {w:g} x {h:g} in given at run time",
        verified=True, verified_by="run-time job setting", verified_on=today,
        params={"width_in": w, "height_in": h, "tolerance_in": tolerance_in},
        pack="job", pack_kind="job",
    )
    return RulePack("job", "job", "Run-time job settings", Path("<run time>"), [rule])


class RuleSet:
    """All packs loaded for one run. Checks ask for rules by id."""

    def __init__(self, packs: list[RulePack]):
        self.packs = packs

    def all(self, rule_id: str) -> list[Rule]:
        """Every rule with this id, across packs, in load order. A rule id
        may carry a suffix after a dot ('min_type_size.facts'), so one pack
        can hold several rules for the same check, each with its own source
        and verified status."""
        return [r for p in self.packs for r in p.rules
                if r.id == rule_id or r.id.startswith(rule_id + ".")]

    def first(self, rule_id: str) -> Rule | None:
        found = self.all(rule_id)
        return found[0] if found else None
