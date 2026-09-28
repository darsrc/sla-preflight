"""Command line: sla-preflight run <file.sla> --profile print_label_final"""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__
from .api import explain, list_checks, run_checks

EXIT = {"pass": 0, "skipped": 0, "warn": 1, "fail": 2, "error": 3}
MARK = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "error": "ERR ", "skipped": "SKIP"}


def _print_report(report: dict) -> None:
    print(f"profile: {report['profile']}   overall: {report['status'].upper()}")
    print(f"evidence: {report['out_dir']}")
    for r in report["results"]:
        print(f"[{MARK[r['status']]}] {r['check']}: {r['summary']}")
        for f in r.get("findings", []):
            if r["status"] in ("pass", "skipped"):
                continue
            bits = [f.get("object") or "-"]
            if f.get("measured"):
                bits.append(f"measured={f['measured']}")
            if f.get("threshold"):
                bits.append(f"threshold={f['threshold']}")
            if f.get("rule"):
                bits.append(f"rule={f['rule']}")
            if f.get("message"):
                bits.append(f["message"])
            print("       - " + "  ".join(str(b) for b in bits))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="sla-preflight", description=__doc__)
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a profile's checks on a .sla file")
    r.add_argument("sla")
    r.add_argument("--profile", required=True)
    r.add_argument("--pdf", help="exported PDF for the export checks")
    r.add_argument("--brand-pack", help="brand pack YAML kept outside the repo")
    r.add_argument("--approved-render", help="approved PNG for render_regression")
    r.add_argument("--out", help="folder for evidence crops (default: a temp folder)")
    r.add_argument("--check", action="append", help="run only this check (repeatable)")
    r.add_argument("--json", action="store_true", help="print the full JSON report")

    l = sub.add_parser("list", help="list checks")
    l.add_argument("--profile")

    e = sub.add_parser("explain", help="explain one check")
    e.add_argument("check")

    a = ap.parse_args(argv)
    if a.cmd == "list":
        for c in list_checks(a.profile):
            tag = " (v0.2, not built)" if c.get("deferred") else ""
            print(f"{c['name']:<26} {c['kind']:<13} {c['description']}{tag}")
        return 0
    if a.cmd == "explain":
        print(json.dumps(explain(a.check), indent=2))
        return 0
    report = run_checks(
        a.sla, a.profile, pdf_path=a.pdf, brand_pack=a.brand_pack,
        out_dir=a.out, approved_render=a.approved_render, only=a.check,
    )
    if a.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return EXIT[report["status"]]


if __name__ == "__main__":
    sys.exit(main())
