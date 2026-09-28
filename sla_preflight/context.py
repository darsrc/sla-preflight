"""What a check sees: its inputs, the loaded rules, and an output folder."""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

from .rules import RuleSet
from .sla import Document, parse_sla


@dataclass
class Context:
    sla_path: Path
    rules: RuleSet
    out_dir: Path
    pdf_path: Path | None = None
    approved_render: Path | None = None
    brief: Path | None = None
    options: dict[str, Any] = field(default_factory=dict)
    # shared scratch between checks in one run (e.g. overlap data reused by
    # required_elements). Checks must still work when run alone.
    cache: dict[str, Any] = field(default_factory=dict)

    @cached_property
    def doc(self) -> Document:
        return parse_sla(self.sla_path)

    def has_input(self, name: str) -> bool:
        return {
            "sla": self.sla_path,
            "pdf": self.pdf_path,
            "approved_render": self.approved_render,
            "brief": self.brief,
        }[name] is not None

    def check_dir(self, check: str) -> Path:
        d = self.out_dir / check
        d.mkdir(parents=True, exist_ok=True)
        return d
