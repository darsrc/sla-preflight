"""The three operations exposed by the CLI and the MCP server."""
from __future__ import annotations

from typing import Any

from . import registry
from .profiles import load_profile
from .runner import run_checks

__all__ = ["list_checks", "run_checks", "explain"]


def list_checks(profile: str | None = None) -> list[dict[str, Any]]:
    """Names, kind and one-line description of each check (in a profile's
    order when ``profile`` is given; v0.2 checks marked deferred)."""
    if profile:
        specs = [registry.get(n) for n in load_profile(profile).checks]
    else:
        specs = registry.all_checks(include_deferred=True)
    out = []
    for s in specs:
        d = {"name": s.name, "kind": s.kind, "description": s.description}
        if s.deferred:
            d["deferred"] = True
        out.append(d)
    return out


def explain(check: str) -> dict[str, Any]:
    """What a check checks, which rules it reads, and how to fix a failure."""
    s = registry.get(check)
    return {
        "name": s.name,
        "kind": s.kind,
        "category": s.category,
        "description": s.description,
        "what_it_checks": s.explain,
        "needs": list(s.inputs),
        "rules_read": list(s.rules),
        "optional_rules": list(s.optional_rules),
        "how_to_fix": s.fix,
        "deferred": s.deferred,
    }
