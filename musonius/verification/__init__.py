"""L5: Verification Engine — reviews changes against spec."""

from __future__ import annotations

from musonius.verification.diff_analyzer import Diff, DiffAnalyzer, FileChange
from musonius.verification.engine import VerificationEngine, VerificationResult
from musonius.verification.linter import LintFinding, LinterIntegration
from musonius.verification.severity import (
    Finding,
    FixSuggestion,
    Severity,
    SeverityClassifier,
)

__all__ = [
    "Diff",
    "DiffAnalyzer",
    "FileChange",
    "Finding",
    "FixSuggestion",
    "LintFinding",
    "LinterIntegration",
    "Severity",
    "SeverityClassifier",
    "VerificationEngine",
    "VerificationResult",
]
