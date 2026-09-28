"""Result schema shared by every check (spec section 3).

A check returns one CheckResult. Each CheckResult carries findings; each
finding carries the evidence: object, measured values, the threshold used,
and the rule it came from (reference, source, verified flag).

Regulatory rules start unverified. A result that depends on an unverified
rule is downgraded to ``warn``: it can never pass or fail a release.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

Status = Literal["pass", "warn", "fail", "error", "skipped"]
Kind = Literal["deterministic", "judgment"]

STATUSES: tuple[str, ...] = ("pass", "warn", "fail", "error", "skipped")
KINDS: tuple[str, ...] = ("deterministic", "judgment")


@dataclass
class Finding:
    object: str | None
    measured: dict[str, Any] = field(default_factory=dict)
    threshold: dict[str, Any] = field(default_factory=dict)
    rule: str | None = None
    rule_source: str | None = None
    rule_verified: bool | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    # What this finding means before the unverified-rule downgrade:
    # "fail" (violation), "warn" (advisory) or "info" (context only).
    severity: Literal["fail", "warn", "info"] = "fail"
    message: str | None = None

    @classmethod
    def from_rule(cls, rule, object: str | None, **kw) -> "Finding":
        """Build a finding that cites ``rule`` (a rules.Rule)."""
        return cls(
            object=object,
            rule=rule.ref,
            rule_source=rule.source,
            rule_verified=rule.verified,
            **kw,
        )

    def effective_severity(self) -> str:
        if self.severity == "fail" and self.rule_verified is False:
            return "warn"
        return self.severity

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Drop empty optional keys so a small model sees a compact record.
        return {k: v for k, v in d.items() if v not in (None, {}, [])}


@dataclass
class CheckResult:
    check: str
    kind: Kind
    status: Status
    summary: str
    findings: list[Finding] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"bad status {self.status!r}")
        if self.kind not in KINDS:
            raise ValueError(f"bad kind {self.kind!r}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "kind": self.kind,
            "status": self.status,
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
        }


def finalize(
    check: str,
    kind: Kind,
    findings: list[Finding],
    rules_used: list,
    pass_summary: str,
    fail_summary: str,
) -> CheckResult:
    """Derive a check's status from its findings and the rules it used.

    * any verified violation                  -> fail
    * any unverified violation / advisory     -> warn
    * clean, but some rule used is unverified -> warn (never pass)
    * clean with only verified rules          -> pass
    Judgment checks never return pass on their own (principle 3):
    a clean judgment result is reported as warn for human confirmation.
    """
    sev = [f.effective_severity() for f in findings]
    unverified = [r for r in rules_used if not r.verified]
    if "fail" in sev:
        status: Status = "fail"
        summary = fail_summary
    elif "warn" in sev:
        status = "warn"
        summary = fail_summary
    else:
        status = "pass"
        summary = pass_summary
    if unverified and status == "pass":
        status = "warn"
        refs = ", ".join(r.ref for r in unverified)
        summary = f"{pass_summary} Advisory only: rule not yet verified ({refs})."
        for r in unverified:
            findings.append(
                Finding.from_rule(
                    r, None, severity="info",
                    message=f"Rule unverified; source: {r.source}",
                )
            )
    elif unverified and status in ("fail", "warn") and "fail" not in sev:
        summary = f"{fail_summary} Advisory only: rule not yet verified."
    if kind == "judgment" and status == "pass":
        status = "warn"
        summary = f"{pass_summary} Judgment result; needs human confirmation."
    return CheckResult(check, kind, status, summary, findings)


def error_result(check: str, kind: Kind, message: str) -> CheckResult:
    return CheckResult(check, kind, "error", message)


def skipped_result(check: str, kind: Kind, message: str) -> CheckResult:
    return CheckResult(check, kind, "skipped", message)


def overall_status(results: list[CheckResult]) -> Status:
    """Spec section 7: fail if any deterministic fail; warn if only warns.

    A check that could not run (error) also blocks release, so it ranks
    as fail at the overall level unless nothing failed, in which case the
    overall status is ``error``.
    """
    det = [r for r in results if r.kind == "deterministic"]
    if any(r.status == "fail" for r in det):
        return "fail"
    if any(r.status == "error" for r in results):
        return "error"
    if any(r.status in ("warn", "fail") for r in results):
        return "warn"
    if results and all(r.status == "skipped" for r in results):
        return "skipped"
    return "pass"
