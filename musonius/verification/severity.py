"""Severity classification for verification findings."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class Severity(Enum):
    """Severity levels for verification findings.

    Levels:
        CRITICAL: Blocks core functionality or plan requirements.
        MAJOR: Significant issues affecting behavior/UX.
        MINOR: Small polish items.
        OUTDATED: Plan references no longer accurate.
        INFO: Informational observation.
    """

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    OUTDATED = "outdated"
    INFO = "info"


SEVERITY_DISPLAY = {
    Severity.CRITICAL: ("red", "CRITICAL"),
    Severity.MAJOR: ("yellow", "MAJOR"),
    Severity.MINOR: ("cyan", "MINOR"),
    Severity.OUTDATED: ("dim", "OUTDATED"),
    Severity.INFO: ("dim", "INFO"),
}


@dataclass
class Finding:
    """A single verification finding.

    Attributes:
        category: Finding category (missing, incorrect, extra, outdated, style, security, completeness).
        severity: Severity level.
        message: Human-readable description.
        file_path: Path to the affected file.
        line_number: Line number in the file, if applicable.
        plan_reference: Which part of the plan this relates to.
        suggestion: Fix suggestion, if available.
    """

    category: str
    severity: Severity
    message: str
    file_path: str | None = None
    line_number: int | None = None
    plan_reference: str = ""
    suggestion: str | None = None


@dataclass
class FixSuggestion:
    """A suggested fix for a finding.

    Attributes:
        finding_index: Index of the finding this fix addresses.
        description: Human-readable description of the fix.
        diff: Suggested code change as unified diff.
        confidence: Confidence score 0.0-1.0.
    """

    finding_index: int
    description: str
    diff: str = ""
    confidence: float = 0.0


# Keywords that indicate severity escalation
_CRITICAL_PATTERNS = [
    r"security",
    r"vulnerability",
    r"injection",
    r"secret",
    r"password",
    r"credential",
    r"authentication.*bypass",
    r"authorization.*bypass",
    r"missing.*required",
    r"core.*functionality.*broken",
    r"acceptance.*criteria.*failed",
    r"breaking.*change",
]

_MAJOR_PATTERNS = [
    r"missing.*error.*handling",
    r"performance.*regression",
    r"significant.*deviation",
    r"missing.*test",
    r"logic.*error",
    r"incomplete.*implementation",
    r"unexpected.*behavior",
]

_OUTDATED_PATTERNS = [
    r"no longer exist",
    r"old architecture",
    r"stale",
    r"deprecated",
    r"removed",
    r"no longer relevant",
]


class SeverityClassifier:
    """Classifies verification findings by severity.

    Uses rule-based heuristics to classify findings when the LLM
    doesn't provide a severity, or to validate/override LLM classifications.
    """

    def classify(
        self,
        finding_text: str,
        category: str,
        plan: dict[str, Any] | None = None,
    ) -> Severity:
        """Classify finding severity based on content and category.

        Args:
            finding_text: The finding description text.
            category: Finding category (missing, incorrect, extra, outdated).
            plan: Optional plan dict for context-aware classification.

        Returns:
            Classified Severity level.
        """
        text_lower = finding_text.lower()

        # Category-based classification
        if category == "outdated":
            return Severity.OUTDATED

        # Pattern-based escalation
        for pattern in _CRITICAL_PATTERNS:
            if re.search(pattern, text_lower):
                return Severity.CRITICAL

        for pattern in _OUTDATED_PATTERNS:
            if re.search(pattern, text_lower):
                return Severity.OUTDATED

        for pattern in _MAJOR_PATTERNS:
            if re.search(pattern, text_lower):
                return Severity.MAJOR

        # Category-based defaults
        if category == "missing":
            return Severity.MAJOR
        if category == "incorrect":
            return Severity.MAJOR
        if category == "extra":
            return Severity.MINOR
        if category == "style":
            return Severity.MINOR

        return Severity.MINOR

    def validate_severity(
        self,
        finding: Finding,
        plan: dict[str, Any] | None = None,
    ) -> Severity:
        """Validate or adjust the severity of an existing finding.

        Checks if the finding's severity aligns with classification rules.
        Can be used to validate LLM-provided severities.

        Args:
            finding: Finding with an existing severity.
            plan: Optional plan dict for context.

        Returns:
            Validated (possibly adjusted) Severity.
        """
        classified = self.classify(finding.message, finding.category, plan)

        # Never downgrade CRITICAL from LLM
        if finding.severity == Severity.CRITICAL:
            return Severity.CRITICAL

        # Allow LLM to escalate beyond rule-based classification
        if _severity_rank(finding.severity) > _severity_rank(classified):
            return finding.severity

        return classified


def _severity_rank(severity: Severity) -> int:
    """Return numeric rank for severity comparison (higher = more severe)."""
    ranks = {
        Severity.INFO: 0,
        Severity.OUTDATED: 1,
        Severity.MINOR: 2,
        Severity.MAJOR: 3,
        Severity.CRITICAL: 4,
    }
    return ranks.get(severity, 0)
