"""Profiles: which checks to run, against which rule packs.

    name: print_label_final
    description: ...
    packs:                      # relative to a rules folder, or absolute
      - printer/wizard_labels.yaml
      - regulatory/us_supplement.yaml
      - brand/example_brand.yaml
    checks: [page_matches_die, trim_safety, ...]

Rule folders are searched in order: each entry of $SLA_PREFLIGHT_RULES
(os.pathsep-separated, e.g. a private folder of client packs), then this
repo's rules/. Profiles likewise: $SLA_PREFLIGHT_PROFILES, then profiles/.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from .rules import RulePack, RulePackError, RuleSet, load_pack

REPO_ROOT = Path(__file__).resolve().parent.parent


def _search_path(env: str, default: Path) -> list[Path]:
    """Folders from an os.pathsep-separated env var, then the repo default."""
    extra = [Path(p) for p in os.environ.get(env, "").split(os.pathsep) if p]
    return extra + [default]


def rules_dirs() -> list[Path]:
    return _search_path("SLA_PREFLIGHT_RULES", REPO_ROOT / "rules")


def profiles_dirs() -> list[Path]:
    return _search_path("SLA_PREFLIGHT_PROFILES", REPO_ROOT / "profiles")


def _find(ref: str, dirs: list[Path]) -> Path | None:
    for d in dirs:
        if (d / ref).is_file():
            return d / ref
    return None


@dataclass
class Profile:
    name: str
    description: str
    packs: list[str]
    checks: list[str]
    path: Path


def resolve_profile_path(profile: str | Path) -> Path:
    p = Path(profile)
    if p.suffix in (".yaml", ".yml") and p.is_file():
        return p
    cand = _find(f"{profile}.yaml", profiles_dirs())
    if cand is not None:
        return cand
    raise RulePackError(f"profile not found: {profile}")


def load_profile(profile: str | Path) -> Profile:
    path = resolve_profile_path(profile)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("checks"), list):
        raise RulePackError(f"{path.name}: profile needs a 'checks' list")
    from .registry import all_checks

    known = {c.name for c in all_checks(include_deferred=True)}
    unknown = [c for c in data["checks"] if c not in known]
    if unknown:
        raise RulePackError(f"{path.name}: unknown checks: {', '.join(unknown)}")
    return Profile(
        name=str(data.get("name", path.stem)),
        description=str(data.get("description", "")),
        packs=[str(x) for x in data.get("packs", [])],
        checks=list(data["checks"]),
        path=path,
    )


def load_packs(profile: Profile, brand_pack: str | Path | None = None) -> RuleSet:
    """Load the profile's packs. A ``brand_pack`` given at run time (e.g. a
    private client pack kept outside this repo) replaces the profile's brand
    packs."""
    packs: list[RulePack] = []
    for ref in profile.packs:
        p = Path(ref)
        if p.is_absolute():
            packs.append(load_pack(p, name=p.name))
            continue
        path = _find(ref, rules_dirs())
        if path is None:
            raise RulePackError(f"rule pack not found: {ref}")
        packs.append(load_pack(path, name=ref))
    if brand_pack is not None:
        bp = Path(brand_pack)
        extra = load_pack(bp, name=f"brand/{bp.name}")
        if extra.kind != "brand":
            raise RulePackError(f"{bp.name}: brand_pack must have kind: brand")
        packs = [p for p in packs if p.kind != "brand"] + [extra]
    return RuleSet(packs)
