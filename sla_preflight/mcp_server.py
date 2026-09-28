"""MCP server with exactly three tools (spec section 7). Uses the v1
FastMCP API (mcp>=1.9,<2). Run: sla-preflight-mcp  (stdio transport)."""
from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import api

mcp = FastMCP("sla-preflight")


@mcp.tool()
def list_checks(profile: str | None = None) -> list[dict[str, Any]]:
    """List checks: name, kind (deterministic/judgment), one-line description.
    Pass a profile name (e.g. print_label_final) to list only its checks."""
    return api.list_checks(profile)


@mcp.tool()
def run_checks(
    sla_path: str,
    profile: str,
    pdf_path: str | None = None,
    brand_pack: str | None = None,
) -> dict[str, Any]:
    """Run a profile's checks on a Scribus .sla file (and its exported PDF).
    Returns overall status (pass/warn/fail/error) and one result per check,
    each with a one-sentence summary you can relay verbatim."""
    return api.run_checks(sla_path, profile, pdf_path=pdf_path, brand_pack=brand_pack)


@mcp.tool()
def explain(check: str) -> dict[str, Any]:
    """Explain one check: what it checks, which rules it reads, how to fix a failure."""
    return api.explain(check)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
