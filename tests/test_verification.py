"""Tests for the verification engine and its components."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from musonius.verification.diff_analyzer import Diff, DiffAnalyzer, FileChange
from musonius.verification.engine import VerificationEngine, VerificationResult
from musonius.verification.linter import LintFinding, LinterIntegration
from musonius.verification.severity import (
    Finding,
    FixSuggestion,
    Severity,
    SeverityClassifier,
)

SAMPLE_DIFF = """\
diff --git a/musonius/cli/init.py b/musonius/cli/init.py
index abc1234..def5678 100644
--- a/musonius/cli/init.py
+++ b/musonius/cli/init.py
@@ -10,6 +10,8 @@ from musonius.cli.utils import console

 logger = logging.getLogger(__name__)

+# New comment
+

 @handle_errors
 def init_command(
diff --git a/musonius/memory/store.py b/musonius/memory/store.py
index 1111111..2222222 100644
--- a/musonius/memory/store.py
+++ b/musonius/memory/store.py
@@ -5,7 +5,7 @@ import sqlite3

 class MemoryStore:
-    def old_method(self):
+    def new_method(self):
         pass
"""


# ──────────────────────────────────────────────────────────
# DiffAnalyzer tests
# ──────────────────────────────────────────────────────────


class TestDiffAnalyzer:
    """Tests for the DiffAnalyzer component."""

    def test_extract_changes_parses_files(self) -> None:
        analyzer = DiffAnalyzer()
        files = analyzer.extract_changes(SAMPLE_DIFF)
        assert len(files) == 2
        assert files[0].file_path == "musonius/cli/init.py"
        assert files[1].file_path == "musonius/memory/store.py"

    def test_extract_changes_counts_added(self) -> None:
        analyzer = DiffAnalyzer()
        files = analyzer.extract_changes(SAMPLE_DIFF)
        assert files[0].added_count == 2

    def test_extract_changes_counts_removed(self) -> None:
        analyzer = DiffAnalyzer()
        files = analyzer.extract_changes(SAMPLE_DIFF)
        assert files[1].removed_count == 1

    def test_extract_changes_captures_added_lines(self) -> None:
        analyzer = DiffAnalyzer()
        files = analyzer.extract_changes(SAMPLE_DIFF)
        assert "# New comment" in files[0].added_lines

    def test_extract_changes_captures_removed_lines(self) -> None:
        analyzer = DiffAnalyzer()
        files = analyzer.extract_changes(SAMPLE_DIFF)
        assert "    def old_method(self):" in files[1].removed_lines

    def test_extract_changes_empty_diff(self) -> None:
        analyzer = DiffAnalyzer()
        files = analyzer.extract_changes("")
        assert files == []

    def test_extract_changes_whitespace_diff(self) -> None:
        analyzer = DiffAnalyzer()
        files = analyzer.extract_changes("   \n   ")
        assert files == []

    def test_extract_changes_captures_hunks(self) -> None:
        analyzer = DiffAnalyzer()
        files = analyzer.extract_changes(SAMPLE_DIFF)
        assert len(files[0].hunks) >= 1

    def test_extract_changes_detects_new_file(self) -> None:
        diff = """\
diff --git a/new_file.py b/new_file.py
new file mode 100644
index 0000000..abc1234
--- /dev/null
+++ b/new_file.py
@@ -0,0 +1,3 @@
+def hello():
+    pass
"""
        analyzer = DiffAnalyzer()
        files = analyzer.extract_changes(diff)
        assert len(files) == 1
        assert files[0].change_type == "added"

    def test_extract_changes_detects_deleted_file(self) -> None:
        diff = """\
diff --git a/old_file.py b/old_file.py
deleted file mode 100644
index abc1234..0000000
--- a/old_file.py
+++ /dev/null
@@ -1,3 +0,0 @@
-def hello():
-    pass
"""
        analyzer = DiffAnalyzer()
        files = analyzer.extract_changes(diff)
        assert len(files) == 1
        assert files[0].change_type == "deleted"

    def test_get_changed_file_paths(self) -> None:
        analyzer = DiffAnalyzer(repo_path=Path("/project"))
        diff = Diff(
            raw=SAMPLE_DIFF,
            files=[
                FileChange(file_path="src/main.py"),
                FileChange(file_path="src/utils.py"),
            ],
        )
        paths = analyzer.get_changed_file_paths(diff)
        assert paths == [Path("/project/src/main.py"), Path("/project/src/utils.py")]

    @patch("subprocess.run")
    def test_get_diff_calls_git(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=SAMPLE_DIFF)
        analyzer = DiffAnalyzer(repo_path=Path("/project"))
        diff = analyzer.get_diff()

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "git" in cmd
        assert "diff" in cmd
        assert len(diff.files) == 2

    @patch("subprocess.run")
    def test_get_diff_staged(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=SAMPLE_DIFF)
        analyzer = DiffAnalyzer(repo_path=Path("/project"))
        analyzer.get_diff(staged=True)

        cmd = mock_run.call_args[0][0]
        assert "--staged" in cmd

    @patch("subprocess.run")
    def test_get_diff_target(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout=SAMPLE_DIFF)
        analyzer = DiffAnalyzer(repo_path=Path("/project"))
        analyzer.get_diff(base="main", target="feature")

        cmd = mock_run.call_args[0][0]
        assert "main" in cmd
        assert "feature" in cmd


# ──────────────────────────────────────────────────────────
# SeverityClassifier tests
# ──────────────────────────────────────────────────────────


class TestSeverityClassifier:
    """Tests for the SeverityClassifier component."""

    def test_classify_outdated_category(self) -> None:
        classifier = SeverityClassifier()
        result = classifier.classify("Some finding", "outdated")
        assert result == Severity.OUTDATED

    def test_classify_security_critical(self) -> None:
        classifier = SeverityClassifier()
        result = classifier.classify("SQL injection vulnerability found", "incorrect")
        assert result == Severity.CRITICAL

    def test_classify_missing_as_major(self) -> None:
        classifier = SeverityClassifier()
        result = classifier.classify("Some function not present", "missing")
        assert result == Severity.MAJOR

    def test_classify_extra_as_minor(self) -> None:
        classifier = SeverityClassifier()
        result = classifier.classify("Extra file modified", "extra")
        assert result == Severity.MINOR

    def test_classify_style_as_minor(self) -> None:
        classifier = SeverityClassifier()
        result = classifier.classify("Inconsistent naming", "style")
        assert result == Severity.MINOR

    def test_classify_performance_regression_as_major(self) -> None:
        classifier = SeverityClassifier()
        result = classifier.classify("Performance regression detected", "incorrect")
        assert result == Severity.MAJOR

    def test_classify_missing_error_handling_as_major(self) -> None:
        classifier = SeverityClassifier()
        result = classifier.classify("Missing error handling for API calls", "missing")
        assert result == Severity.MAJOR

    def test_classify_stale_as_outdated(self) -> None:
        classifier = SeverityClassifier()
        result = classifier.classify("This reference is stale", "general")
        assert result == Severity.OUTDATED

    def test_validate_severity_never_downgrades_critical(self) -> None:
        classifier = SeverityClassifier()
        finding = Finding(
            category="style",
            severity=Severity.CRITICAL,
            message="Some minor style issue",
        )
        result = classifier.validate_severity(finding)
        assert result == Severity.CRITICAL

    def test_validate_severity_allows_escalation(self) -> None:
        classifier = SeverityClassifier()
        finding = Finding(
            category="general",
            severity=Severity.MAJOR,
            message="Some general observation",
        )
        result = classifier.validate_severity(finding)
        assert result == Severity.MAJOR

    def test_severity_enum_has_outdated(self) -> None:
        assert Severity.OUTDATED.value == "outdated"


class TestFinding:
    """Tests for the Finding dataclass."""

    def test_finding_defaults(self) -> None:
        finding = Finding(category="test", severity=Severity.MINOR, message="test")
        assert finding.file_path is None
        assert finding.line_number is None
        assert finding.plan_reference == ""
        assert finding.suggestion is None

    def test_finding_with_all_fields(self) -> None:
        finding = Finding(
            category="missing",
            severity=Severity.CRITICAL,
            message="Required function missing",
            file_path="src/main.py",
            line_number=42,
            plan_reference="Phase 1: implement auth",
            suggestion="Add authenticate() function",
        )
        assert finding.file_path == "src/main.py"
        assert finding.line_number == 42
        assert finding.plan_reference == "Phase 1: implement auth"


class TestFixSuggestion:
    """Tests for the FixSuggestion dataclass."""

    def test_fix_suggestion_defaults(self) -> None:
        fix = FixSuggestion(finding_index=0, description="Add error handling")
        assert fix.diff == ""
        assert fix.confidence == 0.0

    def test_fix_suggestion_with_all_fields(self) -> None:
        fix = FixSuggestion(
            finding_index=1,
            description="Add try/except block",
            diff="--- a/file.py\n+++ b/file.py",
            confidence=0.85,
        )
        assert fix.confidence == 0.85


# ──────────────────────────────────────────────────────────
# LinterIntegration tests
# ──────────────────────────────────────────────────────────


class TestLinterIntegration:
    """Tests for the LinterIntegration component."""

    def test_run_linters_empty_files(self) -> None:
        linter = LinterIntegration()
        results = linter.run_linters([])
        assert results == []

    def test_run_linters_no_python_files(self) -> None:
        linter = LinterIntegration()
        results = linter.run_linters([Path("README.md")])
        assert results == []

    def test_parse_ruff_json_valid(self) -> None:
        linter = LinterIntegration()
        ruff_output = '[{"code": "E501", "message": "Line too long", "filename": "test.py", "location": {"row": 10}}]'
        results = linter._parse_ruff_json(ruff_output)
        assert len(results) == 1
        assert results[0].linter == "ruff"
        assert results[0].code == "E501"
        assert results[0].line_number == 10
        assert results[0].severity == "error"

    def test_parse_ruff_json_warning(self) -> None:
        linter = LinterIntegration()
        ruff_output = '[{"code": "F401", "message": "Unused import", "filename": "test.py", "location": {"row": 1}}]'
        results = linter._parse_ruff_json(ruff_output)
        assert len(results) == 1
        assert results[0].severity == "warning"

    def test_parse_ruff_json_empty(self) -> None:
        linter = LinterIntegration()
        results = linter._parse_ruff_json("")
        assert results == []

    def test_parse_ruff_json_invalid(self) -> None:
        linter = LinterIntegration()
        results = linter._parse_ruff_json("not json")
        assert results == []

    def test_parse_mypy_output_error(self) -> None:
        linter = LinterIntegration()
        mypy_output = "test.py:10: error: Incompatible return value type [return-value]"
        results = linter._parse_mypy_output(mypy_output)
        assert len(results) == 1
        assert results[0].linter == "mypy"
        assert results[0].line_number == 10
        assert results[0].severity == "error"
        assert results[0].code == "return-value"

    def test_parse_mypy_output_note(self) -> None:
        linter = LinterIntegration()
        mypy_output = "test.py:5: note: See docs for more info [note]"
        results = linter._parse_mypy_output(mypy_output)
        assert len(results) == 1
        assert results[0].severity == "info"

    def test_parse_mypy_output_empty(self) -> None:
        linter = LinterIntegration()
        results = linter._parse_mypy_output("")
        assert results == []

    def test_parse_mypy_output_no_code(self) -> None:
        linter = LinterIntegration()
        mypy_output = 'test.py:3: error: Name "foo" is not defined'
        results = linter._parse_mypy_output(mypy_output)
        assert len(results) == 1
        assert results[0].code == ""


class TestLintFinding:
    """Tests for the LintFinding dataclass."""

    def test_lint_finding_fields(self) -> None:
        finding = LintFinding(
            linter="ruff",
            file_path="test.py",
            line_number=10,
            severity="error",
            code="E501",
            message="Line too long",
        )
        assert finding.linter == "ruff"
        assert finding.file_path == "test.py"


# ──────────────────────────────────────────────────────────
# VerificationEngine tests
# ──────────────────────────────────────────────────────────


class TestVerificationEngine:
    """Tests for the verification engine."""

    def test_verify_diff_empty_returns_info(self) -> None:
        engine = VerificationEngine()
        result = engine.verify_diff(diff="", plan={})
        assert len(result.findings) == 1
        assert result.findings[0].severity == Severity.INFO
        assert result.findings[0].category == "empty_diff"

    def test_verify_diff_whitespace_returns_info(self) -> None:
        engine = VerificationEngine()
        result = engine.verify_diff(diff="   \n  ", plan={})
        assert result.findings[0].category == "empty_diff"

    def test_plan_coverage_missing_file(self) -> None:
        engine = VerificationEngine()
        plan = {
            "phases": [
                {
                    "title": "Phase 1",
                    "files": [
                        {"path": "musonius/cli/init.py", "action": "modify", "description": "test"},
                        {"path": "musonius/missing.py", "action": "create", "description": "test"},
                    ],
                }
            ]
        }
        result = engine.verify_diff(diff=SAMPLE_DIFF, plan=plan, use_llm=False)
        missing_findings = [f for f in result.findings if f.category == "missing"]
        assert len(missing_findings) == 1
        assert "musonius/missing.py" in missing_findings[0].message

    def test_plan_coverage_unplanned_file(self) -> None:
        engine = VerificationEngine()
        plan = {
            "phases": [
                {
                    "title": "Phase 1",
                    "files": [
                        {"path": "musonius/cli/init.py", "action": "modify", "description": "test"},
                    ],
                }
            ]
        }
        result = engine.verify_diff(diff=SAMPLE_DIFF, plan=plan, use_llm=False)
        unplanned = [f for f in result.findings if f.category == "extra"]
        assert len(unplanned) == 1
        assert "musonius/memory/store.py" in unplanned[0].message

    def test_detects_print_statements(self) -> None:
        engine = VerificationEngine()
        diff_with_print = """\
diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,4 @@
 def hello():
+    print("debug")
     pass
"""
        result = engine.verify_diff(diff=diff_with_print, plan={}, use_llm=False)
        style_findings = [f for f in result.findings if f.category == "style"]
        assert len(style_findings) >= 1

    def test_detects_bare_except(self) -> None:
        engine = VerificationEngine()
        diff_with_bare_except = """\
diff --git a/foo.py b/foo.py
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,5 @@
 def hello():
     try:
         pass
+    except:
+        pass
"""
        result = engine.verify_diff(diff=diff_with_bare_except, plan={}, use_llm=False)
        security_findings = [f for f in result.findings if f.category == "security"]
        assert len(security_findings) >= 1

    def test_detects_hardcoded_secrets(self) -> None:
        engine = VerificationEngine()
        diff_with_secret = """\
diff --git a/config.py b/config.py
--- a/config.py
+++ b/config.py
@@ -1,2 +1,3 @@
 settings = {
+    "api_key": "sk-12345abcdef"
 }
"""
        result = engine.verify_diff(diff=diff_with_secret, plan={}, use_llm=False)
        critical = [f for f in result.findings if f.severity == Severity.CRITICAL]
        assert len(critical) >= 1
        assert not result.passed

    def test_passed_with_clean_diff(self) -> None:
        engine = VerificationEngine()
        result = engine.verify_diff(diff=SAMPLE_DIFF, plan={}, use_llm=False)
        assert result.passed

    def test_diff_summary_populated(self) -> None:
        engine = VerificationEngine()
        result = engine.verify_diff(diff=SAMPLE_DIFF, plan={}, use_llm=False)
        assert "Changed 2 file(s)" in result.diff_summary

    def test_files_changed_tracked(self) -> None:
        engine = VerificationEngine()
        result = engine.verify_diff(diff=SAMPLE_DIFF, plan={}, use_llm=False)
        assert "musonius/cli/init.py" in result.files_changed
        assert "musonius/memory/store.py" in result.files_changed

    def test_plan_reference_on_coverage_findings(self) -> None:
        engine = VerificationEngine()
        plan = {
            "phases": [
                {
                    "title": "Phase 1",
                    "files": [
                        {"path": "musonius/missing.py", "action": "create", "description": "test"},
                    ],
                }
            ]
        }
        result = engine.verify_diff(diff=SAMPLE_DIFF, plan=plan, use_llm=False)
        missing = [f for f in result.findings if f.category == "missing"]
        assert missing[0].plan_reference == "planned files"

    def test_parse_llm_findings_valid_json(self) -> None:
        engine = VerificationEngine()
        response = '{"findings": [{"category": "missing", "severity": "critical", "description": "Missing auth", "file_path": "auth.py", "plan_reference": "Phase 1"}], "summary": "Test"}'
        findings = engine._parse_llm_findings(response)
        assert len(findings) == 1
        assert findings[0].severity == Severity.CRITICAL
        assert findings[0].plan_reference == "Phase 1"

    def test_parse_llm_findings_json_in_code_block(self) -> None:
        engine = VerificationEngine()
        response = '```json\n{"findings": [{"category": "minor", "severity": "minor", "description": "Test"}]}\n```'
        findings = engine._parse_llm_findings(response)
        assert len(findings) == 1

    def test_parse_llm_findings_invalid_json(self) -> None:
        engine = VerificationEngine()
        findings = engine._parse_llm_findings("not json at all")
        assert findings == []

    def test_parse_llm_findings_outdated_severity(self) -> None:
        engine = VerificationEngine()
        response = '{"findings": [{"category": "outdated", "severity": "outdated", "description": "Old ref"}]}'
        findings = engine._parse_llm_findings(response)
        assert len(findings) == 1
        assert findings[0].severity == Severity.OUTDATED

    def test_parse_llm_findings_uses_message_fallback(self) -> None:
        engine = VerificationEngine()
        response = '{"findings": [{"category": "test", "severity": "info", "message": "Fallback msg"}]}'
        findings = engine._parse_llm_findings(response)
        assert findings[0].message == "Fallback msg"

    def test_parse_llm_findings_uses_file_and_line_fallback(self) -> None:
        engine = VerificationEngine()
        response = '{"findings": [{"category": "test", "severity": "info", "description": "Test", "file": "a.py", "line": 5}]}'
        findings = engine._parse_llm_findings(response)
        assert findings[0].file_path == "a.py"
        assert findings[0].line_number == 5


class TestVerificationResult:
    """Tests for VerificationResult properties."""

    def test_critical_count(self) -> None:
        result = VerificationResult(
            findings=[
                Finding(category="test", severity=Severity.CRITICAL, message="a"),
                Finding(category="test", severity=Severity.MAJOR, message="b"),
                Finding(category="test", severity=Severity.CRITICAL, message="c"),
            ]
        )
        assert result.critical_count == 2

    def test_major_count(self) -> None:
        result = VerificationResult(
            findings=[
                Finding(category="test", severity=Severity.MAJOR, message="a"),
                Finding(category="test", severity=Severity.INFO, message="b"),
            ]
        )
        assert result.major_count == 1

    def test_minor_count(self) -> None:
        result = VerificationResult(
            findings=[
                Finding(category="test", severity=Severity.MINOR, message="a"),
                Finding(category="test", severity=Severity.MINOR, message="b"),
            ]
        )
        assert result.minor_count == 2

    def test_outdated_count(self) -> None:
        result = VerificationResult(
            findings=[
                Finding(category="test", severity=Severity.OUTDATED, message="a"),
            ]
        )
        assert result.outdated_count == 1

    def test_empty_findings(self) -> None:
        result = VerificationResult()
        assert result.critical_count == 0
        assert result.major_count == 0
        assert result.minor_count == 0
        assert result.outdated_count == 0

    def test_verified_at_populated(self) -> None:
        result = VerificationResult()
        assert result.verified_at is not None

    def test_result_has_epic_and_phase(self) -> None:
        result = VerificationResult(epic_id="epic-001", phase_id="01")
        assert result.epic_id == "epic-001"
        assert result.phase_id == "01"

    def test_result_lint_results(self) -> None:
        result = VerificationResult(
            lint_results=[
                LintFinding(
                    linter="ruff",
                    file_path="test.py",
                    line_number=1,
                    severity="error",
                    code="E501",
                    message="Line too long",
                )
            ]
        )
        assert len(result.lint_results) == 1

    def test_summary_building(self) -> None:
        engine = VerificationEngine()
        result = VerificationResult(
            findings=[
                Finding(category="test", severity=Severity.CRITICAL, message="a"),
                Finding(category="test", severity=Severity.MAJOR, message="b"),
            ],
            passed=False,
        )
        summary = engine._build_summary(result)
        assert "1 critical" in summary
        assert "1 major" in summary
        assert "FAILED" in summary

    def test_summary_passed(self) -> None:
        engine = VerificationEngine()
        result = VerificationResult(
            findings=[
                Finding(category="test", severity=Severity.MINOR, message="a"),
            ]
        )
        summary = engine._build_summary(result)
        assert "PASSED" in summary


# ──────────────────────────────────────────────────────────
# Memory integration tests
# ──────────────────────────────────────────────────────────


class TestMemoryIntegration:
    """Tests for verification memory integration."""

    def test_store_verification_patterns(self, tmp_path: Path) -> None:
        from musonius.memory.store import MemoryStore

        db_path = tmp_path / "test.db"
        memory = MemoryStore(db_path)
        memory.initialize()

        engine = VerificationEngine(memory=memory)
        result = VerificationResult(
            epic_id="epic-001",
            findings=[
                Finding(
                    category="security",
                    severity=Severity.CRITICAL,
                    message="SQL injection found",
                    file_path="api.py",
                    suggestion="Use parameterized queries",
                ),
            ],
        )
        engine._store_verification_patterns(result)

        decisions = memory.search_decisions("SQL injection")
        assert len(decisions) >= 1
        assert "SQL injection" in decisions[0]["summary"]

        memory.close()

    def test_learn_from_failures(self, tmp_path: Path) -> None:
        from musonius.memory.store import MemoryStore

        db_path = tmp_path / "test.db"
        memory = MemoryStore(db_path)
        memory.initialize()

        engine = VerificationEngine(memory=memory)
        result = VerificationResult(
            epic_id="epic-002",
            findings=[
                Finding(
                    category="missing",
                    severity=Severity.CRITICAL,
                    message="Auth endpoint missing",
                    file_path="routes.py",
                    plan_reference="Phase 1: implement auth",
                    suggestion="Add /auth endpoint",
                ),
            ],
        )
        engine._learn_from_failures(result)

        failures = memory.get_all_failures()
        assert len(failures) >= 1
        assert "routes.py" in failures[0]["approach"]

        memory.close()

    def test_no_memory_no_error(self) -> None:
        engine = VerificationEngine(memory=None)
        result = VerificationResult(
            findings=[
                Finding(category="test", severity=Severity.CRITICAL, message="test"),
            ],
        )
        # Should not raise
        engine._store_verification_patterns(result)
        engine._learn_from_failures(result)

    def test_non_critical_findings_not_stored_as_failures(self, tmp_path: Path) -> None:
        from musonius.memory.store import MemoryStore

        db_path = tmp_path / "test.db"
        memory = MemoryStore(db_path)
        memory.initialize()

        engine = VerificationEngine(memory=memory)
        result = VerificationResult(
            findings=[
                Finding(category="style", severity=Severity.MINOR, message="style issue"),
            ],
        )
        engine._learn_from_failures(result)

        failures = memory.get_all_failures()
        assert len(failures) == 0

        memory.close()
