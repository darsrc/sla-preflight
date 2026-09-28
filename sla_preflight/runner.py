"""Run a profile's checks and collect results."""
from __future__ import annotations

import tempfile
import traceback
from pathlib import Path
from typing import Any

from . import registry
from .context import Context
from .profiles import load_packs, load_profile
from .result import CheckResult, error_result, overall_status, skipped_result
from .rules import RulePackError
from .checks._common import CheckInputError
from .scribus import ScribusError
from .sla import SlaError


def run_one(spec: registry.CheckSpec, ctx: Context) -> CheckResult:
    """Run a single check. Never raises: problems become ``error``."""
    if spec.deferred or spec.func is None:
        return skipped_result(spec.name, spec.kind, f"{spec.name} is planned for v0.2 and not built yet.")
    missing = [i for i in spec.inputs if not ctx.has_input(i)]
    if missing:
        return skipped_result(spec.name, spec.kind, f"Skipped: no {', '.join(missing)} given.")
    if spec.rules and not any(ctx.rules.all(r) for r in spec.rules):
        return skipped_result(
            spec.name, spec.kind,
            f"Skipped: no rule {' or '.join(spec.rules)} in the loaded packs.",
        )
    try:
        return spec.func(ctx)
    except NotImplementedError:
        return error_result(spec.name, spec.kind, f"{spec.name} is not implemented yet.")
    except (SlaError, RulePackError, FileNotFoundError, CheckInputError, ScribusError) as e:
        return error_result(spec.name, spec.kind, f"Could not run: {e}")
    except Exception as e:  # a crash is an error, never a pass
        tb = traceback.format_exception_only(type(e), e)[-1].strip()
        return error_result(spec.name, spec.kind, f"Check crashed: {tb}")


def run_checks(
    sla_path: str | Path,
    profile: str | Path,
    pdf_path: str | Path | None = None,
    brand_pack: str | Path | None = None,
    out_dir: str | Path | None = None,
    approved_render: str | Path | None = None,
    only: list[str] | None = None,
) -> dict[str, Any]:
    """Run every check in ``profile``. Returns
    ``{"status", "profile", "out_dir", "results": [...]}``."""
    out = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="sla-preflight-"))
    try:
        prof = load_profile(profile)
        rules = load_packs(prof, brand_pack)
    except (RulePackError, OSError) as e:
        res = error_result("load_profile", "deterministic", f"Could not load profile or rule packs: {e}")
        return {"status": "error", "profile": str(profile), "out_dir": str(out), "results": [res.to_dict()]}
    out.mkdir(parents=True, exist_ok=True)
    ctx = Context(
        sla_path=Path(sla_path),
        rules=rules,
        out_dir=out,
        pdf_path=Path(pdf_path) if pdf_path else None,
        approved_render=Path(approved_render) if approved_render else None,
    )
    names = [n for n in prof.checks if only is None or n in only]
    results = [run_one(registry.get(n), ctx) for n in names]
    return {
        "status": overall_status(results),
        "profile": prof.name,
        "out_dir": str(out),
        "results": [r.to_dict() for r in results],
    }
