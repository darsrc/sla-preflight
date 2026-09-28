#!/usr/bin/env python3
"""Refuse to publish private material. Runs as a pre-commit hook and in CI.

Scans every file in the git index (what the next commit and push contain):

1. Private patterns: client names, people, machine names. They are never
   written in this repo. Put one regex per line in ``.safety-patterns``
   (gitignored) and/or in $SLA_PREFLIGHT_SAFETY_PATTERNS (newline-separated;
   in CI, a repository secret). Matching is case-sensitive; start a
   pattern with (?i) to ignore case.
2. Absolute user paths (machine details).
3. Artwork and client files: .sla/.pdf/images/design files are never
   committed. Test fixtures are generated at test time.
4. Brand packs other than the public example (client packs live outside
   the repo).

Exit 0 when clean, 1 with a list of problems otherwise.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERN_FILE = ROOT / ".safety-patterns"

USER_PATHS = re.compile(r"/(?:home|Users)/[A-Za-z0-9_.-]+|[A-Za-z]:\\\\?Users\\\\?")
BLOCKED_SUFFIXES = {
    ".sla", ".sla.gz", ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd",
    ".ai", ".eps", ".indd", ".idml", ".svg", ".docx", ".xlsx", ".eml", ".msg",
}
PUBLIC_BRAND_PACKS = {"rules/brand/example_brand.yaml"}
# lines that may legitimately show a user-path shape, e.g. documentation
# of this very rule; keep this list tiny
ALLOWED_PATH_LINES = ("scripts/safety_check.py",)


def private_patterns() -> list[re.Pattern]:
    raw: list[str] = []
    if PATTERN_FILE.is_file():
        raw += PATTERN_FILE.read_text(encoding="utf-8").splitlines()
    raw += os.environ.get("SLA_PREFLIGHT_SAFETY_PATTERNS", "").splitlines()
    pats = []
    for line in raw:
        line = line.strip()
        if line and not line.startswith("#"):
            pats.append(re.compile(line))
    return pats


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z", "--cached"], cwd=ROOT,
                         capture_output=True, check=True).stdout
    return [f for f in out.decode().split("\0") if f]


def scan(files: list[str], pats: list[re.Pattern]) -> list[str]:
    problems = []
    for rel in files:
        path = ROOT / rel
        low = rel.lower()
        if any(low.endswith(s) for s in BLOCKED_SUFFIXES):
            problems.append(f"{rel}: artwork/client file type is never committed")
        if low.startswith("rules/brand/") and rel not in PUBLIC_BRAND_PACKS:
            problems.append(f"{rel}: brand packs other than the example stay outside the repo")
        for p in pats:
            if p.search(rel):
                problems.append(f"{rel}: file name matches a private pattern")
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"{rel}: binary file; review by hand")
            continue
        for n, line in enumerate(text.splitlines(), 1):
            for p in pats:
                if p.search(line):
                    # never echo the pattern or the match: logs may be public
                    problems.append(f"{rel}:{n}: matches a private pattern")
            if rel not in ALLOWED_PATH_LINES and USER_PATHS.search(line):
                problems.append(f"{rel}:{n}: absolute user path")
    return problems


def main() -> int:
    pats = private_patterns()
    files = tracked_files()
    problems = scan(files, pats)
    if problems:
        print("safety check FAILED; nothing private may be committed:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        return 1
    note = f"{len(pats)} private pattern(s)" if pats else "no private patterns configured"
    print(f"safety check passed: {len(files)} files, {note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
