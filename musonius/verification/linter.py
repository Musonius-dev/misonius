"""Linter integration — runs project linters and parses their output."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class LintFinding:
    """A linter finding.

    Attributes:
        linter: Linter name (ruff, mypy, pylint, etc.).
        file_path: Path to the affected file.
        line_number: Line number of the finding.
        severity: Linter severity (error, warning, info).
        code: Linter rule code (E501, F401, etc.).
        message: Human-readable description.
    """

    linter: str
    file_path: str
    line_number: int
    severity: str
    code: str
    message: str


# Linter configurations: (command_name, check_args, output_parser)
_PYTHON_LINTERS = ["ruff", "mypy"]


class LinterIntegration:
    """Integrates project linters into verification.

    Auto-detects available linters and runs them on changed files,
    parsing output into structured LintFinding objects.

    Args:
        repo_path: Path to the repository root.
    """

    def __init__(self, repo_path: Path | None = None) -> None:
        self.repo_path = repo_path or Path.cwd()

    def run_linters(self, files: list[Path]) -> list[LintFinding]:
        """Run configured linters on the specified files.

        Detects available linters and runs them. Currently supports:
        - Python: ruff, mypy

        Args:
            files: List of file paths to lint.

        Returns:
            Combined list of LintFinding from all linters.
        """
        if not files:
            return []

        python_files = [f for f in files if f.suffix == ".py" and f.exists()]
        if not python_files:
            return []

        findings: list[LintFinding] = []

        # Run ruff if available
        if shutil.which("ruff"):
            findings.extend(self._run_ruff(python_files))

        # Run mypy if available
        if shutil.which("mypy"):
            findings.extend(self._run_mypy(python_files))

        return findings

    def _run_ruff(self, files: list[Path]) -> list[LintFinding]:
        """Run ruff check on files and parse output.

        Args:
            files: Python files to check.

        Returns:
            List of LintFinding from ruff.
        """
        str_files = [str(f) for f in files]
        cmd = ["ruff", "check", "--output-format=json", *str_files]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.repo_path,
                timeout=60,
            )
            # ruff returns exit code 1 when findings exist — that's expected
            return self._parse_ruff_json(result.stdout)
        except subprocess.TimeoutExpired:
            logger.warning("ruff timed out after 60s")
            return []
        except FileNotFoundError:
            logger.debug("ruff not found")
            return []
        except Exception as e:
            logger.warning("ruff failed: %s", e)
            return []

    def _parse_ruff_json(self, output: str) -> list[LintFinding]:
        """Parse ruff JSON output into LintFinding objects.

        Args:
            output: Raw JSON output from ruff.

        Returns:
            List of LintFinding.
        """
        if not output.strip():
            return []

        try:
            items = json.loads(output)
        except json.JSONDecodeError:
            logger.warning("Failed to parse ruff JSON output")
            return []

        findings: list[LintFinding] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            code = item.get("code", "")
            severity = "error" if code.startswith("E") else "warning"

            findings.append(
                LintFinding(
                    linter="ruff",
                    file_path=item.get("filename", ""),
                    line_number=item.get("location", {}).get("row", 0),
                    severity=severity,
                    code=code,
                    message=item.get("message", ""),
                )
            )

        return findings

    def _run_mypy(self, files: list[Path]) -> list[LintFinding]:
        """Run mypy on files and parse output.

        Args:
            files: Python files to check.

        Returns:
            List of LintFinding from mypy.
        """
        str_files = [str(f) for f in files]
        cmd = ["mypy", "--no-error-summary", "--no-color", *str_files]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.repo_path,
                timeout=120,
            )
            return self._parse_mypy_output(result.stdout)
        except subprocess.TimeoutExpired:
            logger.warning("mypy timed out after 120s")
            return []
        except FileNotFoundError:
            logger.debug("mypy not found")
            return []
        except Exception as e:
            logger.warning("mypy failed: %s", e)
            return []

    def _parse_mypy_output(self, output: str) -> list[LintFinding]:
        """Parse mypy text output into LintFinding objects.

        Expected format: file.py:line: severity: message  [code]

        Args:
            output: Raw text output from mypy.

        Returns:
            List of LintFinding.
        """
        findings: list[LintFinding] = []
        pattern = re.compile(
            r"^(.+?):(\d+):\s*(error|warning|note):\s*(.+?)(?:\s*\[(.+?)\])?\s*$"
        )

        for line in output.strip().split("\n"):
            match = pattern.match(line)
            if not match:
                continue

            file_path, line_num, severity, message, code = match.groups()
            findings.append(
                LintFinding(
                    linter="mypy",
                    file_path=file_path,
                    line_number=int(line_num),
                    severity=severity if severity != "note" else "info",
                    code=code or "",
                    message=message,
                )
            )

        return findings
