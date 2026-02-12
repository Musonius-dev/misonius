"""L5: Verification Engine — compares implementation against plan."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from musonius.verification.diff_analyzer import Diff, DiffAnalyzer, FileChange
from musonius.verification.linter import LintFinding, LinterIntegration
from musonius.verification.severity import (
    Finding,
    FixSuggestion,
    Severity,
    SeverityClassifier,
)

if TYPE_CHECKING:
    from musonius.memory.store import MemoryStore
    from musonius.orchestration.router import ModelRouter

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Complete verification result.

    Attributes:
        epic_id: Epic identifier.
        phase_id: Phase identifier.
        findings: List of verification findings.
        lint_results: List of linter findings.
        summary: Human-readable summary.
        passed: True if no critical findings.
        verified_at: Timestamp of verification.
        diff_summary: Human-readable diff summary.
        files_changed: List of changed file paths.
        fix_suggestions: Optional list of fix suggestions.
    """

    epic_id: str = ""
    phase_id: str = ""
    findings: list[Finding] = field(default_factory=list)
    lint_results: list[LintFinding] = field(default_factory=list)
    summary: str = ""
    passed: bool = True
    verified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    diff_summary: str = ""
    files_changed: list[str] = field(default_factory=list)
    fix_suggestions: list[FixSuggestion] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        """Number of critical findings."""
        return sum(1 for f in self.findings if f.severity == Severity.CRITICAL)

    @property
    def major_count(self) -> int:
        """Number of major findings."""
        return sum(1 for f in self.findings if f.severity == Severity.MAJOR)

    @property
    def minor_count(self) -> int:
        """Number of minor findings."""
        return sum(1 for f in self.findings if f.severity == Severity.MINOR)

    @property
    def outdated_count(self) -> int:
        """Number of outdated findings."""
        return sum(1 for f in self.findings if f.severity == Severity.OUTDATED)


VERIFY_SYSTEM_PROMPT = """\
You are a code review assistant. Analyze the git diff and compare it against the plan.
Report findings in JSON format:

{
  "findings": [
    {
      "category": "missing|incorrect|extra|outdated",
      "severity": "critical|major|minor|outdated",
      "file_path": "path/to/file.py",
      "line_number": 42,
      "description": "Description of the finding",
      "plan_reference": "Which plan requirement this relates to",
      "suggestion": "How to fix it"
    }
  ],
  "summary": "Overall assessment"
}

Categories:
- missing: Required by plan but not implemented
- incorrect: Implemented but doesn't match plan
- extra: Changes not described in plan
- outdated: Plan references that are no longer accurate

Severities:
- critical: Breaks core functionality, security vulnerability, missing required feature
- major: Significant deviation from plan, missing tests, logic errors
- minor: Style issues, minor deviations, could be improved
- outdated: Plan is stale, references old architecture
"""

VERIFY_USER_TEMPLATE = """\
## Plan
{plan}

### Acceptance Criteria
{acceptance_criteria}

## Implementation (Git Diff)
```diff
{diff}
```

## Lint Results
{lint_results}

## Instructions
Review the implementation and identify:
1. Missing requirements from the plan
2. Incorrect implementations
3. Unexpected changes not in the plan
4. Acceptance criteria not met

For each finding, specify category, severity, file, line, description, plan_reference, and suggestion.
Return as JSON.
"""


class VerificationEngine:
    """Reviews implementation changes against the plan spec.

    Supports local heuristic checks, linter integration, and LLM-based
    cross-model review. Optionally stores verification patterns in memory.

    Args:
        router: Optional model router for LLM-based verification.
        memory: Optional memory store for pattern storage.
        repo_path: Path to the repository root.
    """

    def __init__(
        self,
        router: ModelRouter | None = None,
        memory: MemoryStore | None = None,
        repo_path: Path | None = None,
    ) -> None:
        self._router = router
        self._memory = memory
        self._repo_path = repo_path or Path.cwd()
        self.diff_analyzer = DiffAnalyzer(self._repo_path)
        self.severity_classifier = SeverityClassifier()
        self.linter = LinterIntegration(self._repo_path)

    def verify(
        self,
        epic_id: str = "",
        phase_id: str = "",
        base: str = "HEAD",
        target: str | None = None,
        staged: bool = False,
        auto_fix: bool = False,
        use_llm: bool = True,
        plan: dict[str, Any] | None = None,
    ) -> VerificationResult:
        """Verify implementation against plan.

        This is the main entry point that orchestrates the full verification
        pipeline: diff extraction, linting, heuristic checks, LLM review,
        and memory integration.

        Args:
            epic_id: Epic identifier.
            phase_id: Specific phase to verify.
            base: Base commit/branch for diff.
            target: Target commit/branch (None = working tree).
            staged: If True, only verify staged changes.
            auto_fix: Whether to generate fix suggestions.
            use_llm: Whether to use LLM for deep analysis.
            plan: Plan dictionary to verify against.

        Returns:
            VerificationResult with categorized findings.
        """
        plan = plan or {}

        # Extract diff
        try:
            diff = self.diff_analyzer.get_diff(base=base, target=target, staged=staged)
        except RuntimeError as e:
            logger.error("Failed to get diff: %s", e)
            return VerificationResult(
                epic_id=epic_id,
                phase_id=phase_id,
                findings=[
                    Finding(
                        category="error",
                        severity=Severity.INFO,
                        message=f"Failed to get diff: {e}",
                    )
                ],
            )

        if not diff.files:
            return VerificationResult(
                epic_id=epic_id,
                phase_id=phase_id,
                findings=[
                    Finding(
                        category="empty_diff",
                        severity=Severity.INFO,
                        message="No changes detected.",
                    )
                ],
            )

        result = VerificationResult(
            epic_id=epic_id,
            phase_id=phase_id,
            diff_summary=self._build_diff_summary(diff.files),
            files_changed=[fc.file_path for fc in diff.files],
        )

        # Run linters on changed files
        changed_paths = self.diff_analyzer.get_changed_file_paths(diff)
        result.lint_results = self.linter.run_linters(changed_paths)

        # Run local heuristic checks
        self._check_plan_coverage(result, diff.files, plan)
        self._check_common_issues(result, diff.files)

        # Run LLM-based verification if available
        if use_llm and self._router and plan:
            try:
                llm_findings = self._llm_verify(diff.raw, plan, result.lint_results)
                result.findings.extend(llm_findings)
            except Exception as e:
                logger.warning("LLM verification failed: %s", e)
                result.findings.append(
                    Finding(
                        category="verification",
                        severity=Severity.INFO,
                        message=f"LLM verification unavailable: {e}",
                    )
                )

        # Generate fix suggestions if requested
        if auto_fix and self._router and result.findings:
            result.fix_suggestions = self._generate_fix_suggestions(
                result.findings, diff.raw, plan
            )

        # Build summary
        result.summary = self._build_summary(result)

        # Determine pass/fail based on critical findings
        result.passed = result.critical_count == 0

        # Store patterns in memory
        if self._memory:
            self._store_verification_patterns(result)

        return result

    def verify_diff(
        self,
        diff: str,
        plan: dict[str, Any],
        use_llm: bool = True,
    ) -> VerificationResult:
        """Verify a raw git diff string against a plan.

        Backward-compatible method that accepts a raw diff string
        instead of using the DiffAnalyzer.

        Args:
            diff: Git diff string.
            plan: Plan dictionary to verify against.
            use_llm: Whether to use LLM for deep analysis.

        Returns:
            Verification result with findings.
        """
        if not diff.strip():
            return VerificationResult(
                findings=[
                    Finding(
                        category="empty_diff",
                        severity=Severity.INFO,
                        message="No changes detected.",
                    )
                ]
            )

        # Parse the diff
        diff_files = self.diff_analyzer.extract_changes(diff)
        changed_paths = [fc.file_path for fc in diff_files]

        result = VerificationResult(
            diff_summary=self._build_diff_summary(diff_files),
            files_changed=changed_paths,
        )

        # Run local heuristic checks
        self._check_plan_coverage(result, diff_files, plan)
        self._check_common_issues(result, diff_files)

        # Run LLM-based verification if available
        if use_llm and self._router and plan:
            try:
                llm_findings = self._llm_verify(diff, plan, [])
                result.findings.extend(llm_findings)
            except Exception as e:
                logger.warning("LLM verification failed: %s", e)
                result.findings.append(
                    Finding(
                        category="verification",
                        severity=Severity.INFO,
                        message=f"LLM verification unavailable: {e}",
                    )
                )

        # Determine pass/fail based on critical findings
        result.passed = result.critical_count == 0

        return result

    def _build_diff_summary(self, files: list[FileChange]) -> str:
        """Build a human-readable diff summary."""
        lines = [f"Changed {len(files)} file(s):"]
        for f in files:
            lines.append(f"  {f.file_path}: +{f.added_count} -{f.removed_count}")
        return "\n".join(lines)

    def _check_plan_coverage(
        self,
        result: VerificationResult,
        diff_files: list[FileChange],
        plan: dict[str, Any],
    ) -> None:
        """Check that all planned files are present in the diff."""
        planned_files: set[str] = set()
        for phase in plan.get("phases", []):
            for file_entry in phase.get("files", []):
                if isinstance(file_entry, dict):
                    path = file_entry.get("path", "")
                    if path:
                        planned_files.add(path)

        if not planned_files:
            return

        changed_set = {f.file_path for f in diff_files}

        # Files in plan but not in diff
        for missing in planned_files - changed_set:
            result.findings.append(
                Finding(
                    category="missing",
                    severity=Severity.MAJOR,
                    message=f"Planned file not modified: {missing}",
                    file_path=missing,
                    plan_reference="planned files",
                    suggestion=f"Implement changes for {missing} as described in the plan.",
                )
            )

        # Files in diff but not in plan
        for extra in changed_set - planned_files:
            result.findings.append(
                Finding(
                    category="extra",
                    severity=Severity.MINOR,
                    message=f"Modified file not in plan: {extra}",
                    file_path=extra,
                    plan_reference="planned files",
                    suggestion="Verify this change is intentional and update the plan.",
                )
            )

    def _check_common_issues(
        self, result: VerificationResult, diff_files: list[FileChange]
    ) -> None:
        """Run heuristic checks for common issues in the diff."""
        for diff_file in diff_files:
            full_content = "\n".join(diff_file.hunks)

            # Check for debug artifacts
            if re.search(r"\+.*\bprint\s*\(", full_content):
                result.findings.append(
                    Finding(
                        category="style",
                        severity=Severity.MINOR,
                        message="print() statement added — use logging instead.",
                        file_path=diff_file.file_path,
                        suggestion="Replace print() with logger calls.",
                    )
                )

            # Check for bare except
            if re.search(r"\+.*\bexcept\s*:", full_content):
                result.findings.append(
                    Finding(
                        category="security",
                        severity=Severity.MAJOR,
                        message="Bare except clause added.",
                        file_path=diff_file.file_path,
                        suggestion="Use specific exception types (e.g., except ValueError).",
                    )
                )

            # Check for TODO/FIXME/HACK
            for marker in ("TODO", "FIXME", "HACK", "XXX"):
                if re.search(rf"\+.*\b{marker}\b", full_content):
                    result.findings.append(
                        Finding(
                            category="completeness",
                            severity=Severity.INFO,
                            message=f"{marker} marker found in changes.",
                            file_path=diff_file.file_path,
                        )
                    )

            # Check for hardcoded secrets patterns
            if re.search(
                r"\+.*(password|secret|api_key|token)['\"]?\s*[:=]\s*['\"][^'\"]+['\"]",
                full_content,
                re.IGNORECASE,
            ):
                result.findings.append(
                    Finding(
                        category="security",
                        severity=Severity.CRITICAL,
                        message="Possible hardcoded secret detected.",
                        file_path=diff_file.file_path,
                        suggestion="Use environment variables or a secrets manager.",
                    )
                )

    def _llm_verify(
        self,
        diff: str,
        plan: dict[str, Any],
        lint_results: list[LintFinding],
    ) -> list[Finding]:
        """Run LLM-based verification against the plan.

        Args:
            diff: Git diff string.
            plan: Plan dictionary.
            lint_results: Linter findings for context.

        Returns:
            List of findings from LLM analysis.
        """
        if not self._router:
            return []

        plan_text = self._plan_to_text(plan)
        acceptance_criteria = self._extract_acceptance_criteria(plan)
        lint_text = self._format_lint_results(lint_results)

        # Truncate diff to prevent exceeding context window
        truncated_diff = diff[:10_000] if len(diff) > 10_000 else diff

        messages = [
            {"role": "system", "content": VERIFY_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": VERIFY_USER_TEMPLATE.format(
                    plan=plan_text,
                    acceptance_criteria=acceptance_criteria,
                    diff=truncated_diff,
                    lint_results=lint_text,
                ),
            },
        ]

        response = self._router.call_verifier(messages)
        return self._parse_llm_findings(response.content)

    def _plan_to_text(self, plan: dict[str, Any]) -> str:
        """Convert a plan dict to readable text for verification."""
        lines: list[str] = []
        for phase in plan.get("phases", []):
            if isinstance(phase, dict):
                title = phase.get("title", "Untitled")
                desc = phase.get("description", "")
                lines.append(f"## {title}")
                lines.append(desc)
                for f in phase.get("files", []):
                    if isinstance(f, dict):
                        lines.append(
                            f"- {f.get('action', 'modify')} {f.get('path', '')}: "
                            f"{f.get('description', '')}"
                        )
        return "\n".join(lines) if lines else "(no plan provided)"

    def _extract_acceptance_criteria(self, plan: dict[str, Any]) -> str:
        """Extract acceptance criteria from plan."""
        criteria: list[str] = []
        for phase in plan.get("phases", []):
            if isinstance(phase, dict):
                for c in phase.get("acceptance_criteria", []):
                    criteria.append(f"- [ ] {c}")
        return "\n".join(criteria) if criteria else "(no acceptance criteria)"

    def _format_lint_results(self, lint_results: list[LintFinding]) -> str:
        """Format lint results for LLM prompt."""
        if not lint_results:
            return "(no lint issues)"

        lines: list[str] = []
        for lr in lint_results[:20]:  # Limit to prevent token overflow
            lines.append(f"- [{lr.linter}] {lr.file_path}:{lr.line_number} {lr.code}: {lr.message}")
        if len(lint_results) > 20:
            lines.append(f"... and {len(lint_results) - 20} more")
        return "\n".join(lines)

    def _parse_llm_findings(self, response_text: str) -> list[Finding]:
        """Parse LLM response into Finding objects."""
        findings: list[Finding] = []

        # Try direct JSON parse
        data: dict[str, Any] | None = None
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            # Try extracting from code block
            if "```" in response_text:
                blocks = response_text.split("```")
                for block in blocks:
                    clean = block.strip()
                    if clean.startswith("json"):
                        clean = clean[4:].strip()
                    try:
                        data = json.loads(clean)
                        break
                    except json.JSONDecodeError:
                        continue

        if data is None:
            return findings

        severity_map = {
            "critical": Severity.CRITICAL,
            "major": Severity.MAJOR,
            "minor": Severity.MINOR,
            "outdated": Severity.OUTDATED,
            "info": Severity.INFO,
        }

        for item in data.get("findings", []):
            if not isinstance(item, dict):
                continue

            sev_str = item.get("severity", "info").lower()
            finding = Finding(
                category=item.get("category", "general"),
                severity=severity_map.get(sev_str, Severity.INFO),
                message=item.get("description", item.get("message", "")),
                file_path=item.get("file_path", item.get("file")),
                line_number=item.get("line_number", item.get("line")),
                plan_reference=item.get("plan_reference", ""),
                suggestion=item.get("suggestion"),
            )

            # Validate severity with classifier
            finding.severity = self.severity_classifier.validate_severity(finding)
            findings.append(finding)

        return findings

    def _generate_fix_suggestions(
        self,
        findings: list[Finding],
        diff: str,
        plan: dict[str, Any],
    ) -> list[FixSuggestion]:
        """Generate fix suggestions for findings using LLM.

        Args:
            findings: List of findings to generate fixes for.
            diff: Git diff string.
            plan: Plan dictionary.

        Returns:
            List of FixSuggestion objects.
        """
        if not self._router:
            return []

        # Only generate fixes for critical and major findings
        fixable = [
            (i, f) for i, f in enumerate(findings)
            if f.severity in (Severity.CRITICAL, Severity.MAJOR)
        ]
        if not fixable:
            return []

        findings_text = "\n".join(
            f"{i}. [{f.severity.value}] {f.message} (file: {f.file_path})"
            for i, f in fixable
        )

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a code fix assistant. Generate fix suggestions "
                    "for the following findings. Return JSON:\n"
                    '{"fixes": [{"finding_index": 0, "description": "...", '
                    '"diff": "unified diff", "confidence": 0.8}]}'
                ),
            },
            {
                "role": "user",
                "content": (
                    f"## Findings\n{findings_text}\n\n"
                    f"## Current Diff\n```diff\n{diff[:5000]}\n```\n\n"
                    f"## Plan\n{self._plan_to_text(plan)}"
                ),
            },
        ]

        try:
            response = self._router.call_verifier(messages)
            return self._parse_fix_suggestions(response.content)
        except Exception as e:
            logger.warning("Fix suggestion generation failed: %s", e)
            return []

    def _parse_fix_suggestions(self, response_text: str) -> list[FixSuggestion]:
        """Parse LLM response into FixSuggestion objects."""
        data: dict[str, Any] | None = None
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError:
            if "```" in response_text:
                for block in response_text.split("```"):
                    clean = block.strip()
                    if clean.startswith("json"):
                        clean = clean[4:].strip()
                    try:
                        data = json.loads(clean)
                        break
                    except json.JSONDecodeError:
                        continue

        if data is None:
            return []

        suggestions: list[FixSuggestion] = []
        for item in data.get("fixes", []):
            if not isinstance(item, dict):
                continue
            suggestions.append(
                FixSuggestion(
                    finding_index=item.get("finding_index", 0),
                    description=item.get("description", ""),
                    diff=item.get("diff", ""),
                    confidence=item.get("confidence", 0.0),
                )
            )

        return suggestions

    def _build_summary(self, result: VerificationResult) -> str:
        """Build a human-readable summary of the verification result."""
        parts: list[str] = []
        if result.critical_count:
            parts.append(f"{result.critical_count} critical")
        if result.major_count:
            parts.append(f"{result.major_count} major")
        if result.minor_count:
            parts.append(f"{result.minor_count} minor")
        if result.outdated_count:
            parts.append(f"{result.outdated_count} outdated")

        if not parts:
            return "No findings — all changes look good."

        status = "FAILED" if not result.passed else "PASSED"
        return f"{', '.join(parts)} findings. Status: {status}"

    def _store_verification_patterns(self, result: VerificationResult) -> None:
        """Store common verification patterns in memory.

        Captures frequently missed requirements, common implementation
        mistakes, and effective fix patterns.

        Args:
            result: The completed verification result.
        """
        if not self._memory:
            return

        try:
            # Store critical/major findings as decisions
            for finding in result.findings:
                if finding.severity in (Severity.CRITICAL, Severity.MAJOR):
                    self._memory.add_decision(
                        summary=f"Verification: {finding.message}",
                        rationale=finding.suggestion or "",
                        category="verification",
                        epic_id=result.epic_id or None,
                        files_affected=[finding.file_path] if finding.file_path else None,
                    )

            # Learn from failures — store critical findings as failed approaches
            self._learn_from_failures(result)
        except Exception as e:
            logger.debug("Failed to store verification patterns: %s", e)

    def _learn_from_failures(self, result: VerificationResult) -> None:
        """Update memory with failed approaches from critical findings.

        If critical findings are detected, stores what was attempted,
        why it failed, and what should be done instead.

        Args:
            result: The completed verification result.
        """
        if not self._memory:
            return

        critical_findings = [
            f for f in result.findings if f.severity == Severity.CRITICAL
        ]
        if not critical_findings:
            return

        for finding in critical_findings:
            approach = f"Implementation in {finding.file_path or 'unknown'}: {finding.message}"
            reason = f"Category: {finding.category}. {finding.plan_reference}"
            alternative = finding.suggestion

            try:
                self._memory.add_failure(
                    approach=approach,
                    failure_reason=reason,
                    alternative=alternative,
                    epic_id=result.epic_id or None,
                    files_affected=[finding.file_path] if finding.file_path else None,
                )
            except Exception as e:
                logger.debug("Failed to record failure: %s", e)
