"""Check registry. One check = one small, independent function."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .result import CheckResult, Kind

INPUTS = ("sla", "pdf", "approved_render", "brief")


@dataclass(frozen=True)
class CheckSpec:
    name: str
    kind: Kind
    description: str  # one line
    inputs: tuple[str, ...]  # what the check needs to run at all
    rules: tuple[str, ...]  # rule ids it reads; at least one must be loaded
    optional_rules: tuple[str, ...]  # rule ids it reads when present
    explain: str  # what it checks, in a few sentences
    fix: str  # how to fix a failure
    func: Callable[..., CheckResult] | None
    deferred: bool = False  # interface designed, not built (v0.2)
    category: str = ""


REGISTRY: dict[str, CheckSpec] = {}


def check(
    name: str,
    *,
    kind: Kind = "deterministic",
    description: str,
    inputs: tuple[str, ...] = ("sla",),
    rules: tuple[str, ...] = (),
    optional_rules: tuple[str, ...] = (),
    explain: str,
    fix: str,
    category: str = "",
    deferred: bool = False,
):
    """Register a check function ``f(ctx) -> CheckResult``."""
    bad = [i for i in inputs if i not in INPUTS]
    if bad:
        raise ValueError(f"{name}: unknown inputs {bad}")

    def deco(func):
        if name in REGISTRY:
            raise ValueError(f"check {name!r} registered twice")
        REGISTRY[name] = CheckSpec(
            name, kind, description, tuple(inputs), tuple(rules), tuple(optional_rules),
            explain, fix, func, deferred, category,
        )
        return func

    return deco


def get(name: str) -> CheckSpec:
    _load()
    try:
        return REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown check {name!r}") from None


def all_checks(include_deferred: bool = False) -> list[CheckSpec]:
    _load()
    return [c for c in REGISTRY.values() if include_deferred or not c.deferred]


def _load() -> None:
    # importing the package registers every check
    from . import checks  # noqa: F401
