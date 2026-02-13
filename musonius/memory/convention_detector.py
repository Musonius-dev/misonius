"""Auto-detect coding conventions from indexed codebase files.

Analyzes Python source files to detect naming conventions, docstring style,
import organization, test framework, linter/formatter usage, and other
project patterns. Results are stored in the memory store as conventions.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class DetectedConvention:
    """A single detected coding convention.

    Attributes:
        pattern: Convention category (naming, docstring, imports, testing, tooling).
        rule: Human-readable description of the convention.
        confidence: Detection confidence 0.0-1.0.
        evidence_count: Number of files/symbols supporting this detection.
    """

    pattern: str
    rule: str
    confidence: float = 1.0
    evidence_count: int = 0


@dataclass
class ConventionReport:
    """Aggregated results from convention detection.

    Attributes:
        conventions: All detected conventions.
        files_analyzed: Number of source files scanned.
        language: Detected primary language.
    """

    conventions: list[DetectedConvention] = field(default_factory=list)
    files_analyzed: int = 0
    language: str = "python"


# ---------------------------------------------------------------------------
# Naming convention helpers
# ---------------------------------------------------------------------------

_SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$")
_CAMEL_CASE_RE = re.compile(r"^[a-z][a-zA-Z0-9]*$")
_PASCAL_CASE_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*$")
_UPPER_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9]*(_[A-Z0-9]+)*$")


def _classify_name(name: str) -> str:
    """Classify a name into a naming convention style.

    Args:
        name: The identifier to classify.

    Returns:
        One of 'snake_case', 'camelCase', 'PascalCase', 'UPPER_SNAKE', or 'other'.
    """
    if _UPPER_SNAKE_RE.match(name):
        return "UPPER_SNAKE"
    if _SNAKE_CASE_RE.match(name):
        return "snake_case"
    if _PASCAL_CASE_RE.match(name):
        return "PascalCase"
    if _CAMEL_CASE_RE.match(name):
        return "camelCase"
    return "other"


# ---------------------------------------------------------------------------
# Core detection functions
# ---------------------------------------------------------------------------


def detect_naming_conventions(
    symbols: list[dict[str, Any]],
) -> list[DetectedConvention]:
    """Detect naming conventions from extracted symbols.

    Checks functions for snake_case vs camelCase and classes for PascalCase.

    Args:
        symbols: List of symbol dicts with 'name' and 'type' keys.

    Returns:
        List of detected naming conventions.
    """
    results: list[DetectedConvention] = []
    func_styles: Counter[str] = Counter()
    class_styles: Counter[str] = Counter()

    for sym in symbols:
        name = sym.get("name", "")
        sym_type = sym.get("type", "")
        if not name or name.startswith("_"):
            continue  # skip private/dunder

        if sym_type in ("function", "method"):
            func_styles[_classify_name(name)] += 1
        elif sym_type == "class":
            class_styles[_classify_name(name)] += 1

    # Function naming
    total_funcs = sum(func_styles.values())
    if total_funcs > 0:
        dominant, count = func_styles.most_common(1)[0]
        confidence = count / total_funcs
        if confidence >= 0.6:
            results.append(
                DetectedConvention(
                    pattern="naming",
                    rule=f"Functions and methods use {dominant} naming convention",
                    confidence=round(confidence, 2),
                    evidence_count=count,
                )
            )

    # Class naming
    total_classes = sum(class_styles.values())
    if total_classes > 0:
        dominant, count = class_styles.most_common(1)[0]
        confidence = count / total_classes
        if confidence >= 0.6:
            results.append(
                DetectedConvention(
                    pattern="naming",
                    rule=f"Classes use {dominant} naming convention",
                    confidence=round(confidence, 2),
                    evidence_count=count,
                )
            )

    return results


def detect_docstring_style(file_contents: dict[str, str]) -> list[DetectedConvention]:
    """Detect docstring style (Google, NumPy, Sphinx, or none).

    Args:
        file_contents: Mapping of file path to file content string.

    Returns:
        List of detected docstring conventions.
    """
    style_votes: Counter[str] = Counter()
    files_with_docstrings = 0

    google_re = re.compile(r"^\s+(Args|Returns|Raises|Yields|Examples):\s*$", re.MULTILINE)
    numpy_re = re.compile(r"^\s+(Parameters|Returns|Raises)\s*\n\s+-{3,}", re.MULTILINE)
    sphinx_re = re.compile(r"^\s+:(param|type|returns|rtype|raises)\s", re.MULTILINE)

    for content in file_contents.values():
        if '"""' not in content and "'''" not in content:
            continue

        files_with_docstrings += 1
        if google_re.search(content):
            style_votes["Google-style"] += 1
        if numpy_re.search(content):
            style_votes["NumPy-style"] += 1
        if sphinx_re.search(content):
            style_votes["Sphinx-style"] += 1

    results: list[DetectedConvention] = []
    total = sum(style_votes.values())
    if total > 0:
        dominant, count = style_votes.most_common(1)[0]
        confidence = count / max(files_with_docstrings, 1)
        results.append(
            DetectedConvention(
                pattern="docstring",
                rule=f"Docstrings follow {dominant} format",
                confidence=round(min(confidence, 1.0), 2),
                evidence_count=count,
            )
        )
    elif files_with_docstrings == 0 and len(file_contents) > 3:
        results.append(
            DetectedConvention(
                pattern="docstring",
                rule="No docstrings detected — consider adding Google-style docstrings",
                confidence=0.8,
                evidence_count=0,
            )
        )

    return results


def detect_import_style(file_contents: dict[str, str]) -> list[DetectedConvention]:
    """Detect import organization patterns.

    Checks for: future annotations, isort-style grouping, relative vs absolute imports.

    Args:
        file_contents: Mapping of file path to file content string.

    Returns:
        List of detected import conventions.
    """
    results: list[DetectedConvention] = []
    future_count = 0
    relative_import_count = 0
    absolute_import_count = 0
    total_files = len(file_contents)

    for content in file_contents.values():
        if "from __future__ import annotations" in content:
            future_count += 1
        # Count relative imports (from . import / from .. import)
        relative_import_count += len(re.findall(r"^from \.\S*\s+import", content, re.MULTILINE))
        absolute_import_count += len(
            re.findall(r"^(?:import|from)\s+(?!\.)[\w.]+", content, re.MULTILINE)
        )

    if total_files > 0:
        future_ratio = future_count / total_files
        if future_ratio >= 0.5:
            results.append(
                DetectedConvention(
                    pattern="imports",
                    rule="All files use `from __future__ import annotations`",
                    confidence=round(future_ratio, 2),
                    evidence_count=future_count,
                )
            )

    total_imports = relative_import_count + absolute_import_count
    if total_imports > 0:
        abs_ratio = absolute_import_count / total_imports
        if abs_ratio >= 0.8:
            results.append(
                DetectedConvention(
                    pattern="imports",
                    rule="Prefers absolute imports over relative imports",
                    confidence=round(abs_ratio, 2),
                    evidence_count=absolute_import_count,
                )
            )

    return results


def detect_test_framework(project_root: Path) -> list[DetectedConvention]:
    """Detect testing framework from project configuration and file patterns.

    Args:
        project_root: Root directory of the project.

    Returns:
        List of detected testing conventions.
    """
    results: list[DetectedConvention] = []

    # Check pyproject.toml for pytest config
    pyproject = project_root / "pyproject.toml"
    has_pytest_config = False
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8")
            if "[tool.pytest" in content:
                has_pytest_config = True
        except OSError:
            pass

    # Check for conftest.py (strong pytest signal)
    conftest_files = list(project_root.rglob("conftest.py"))

    # Check for test files
    test_files = list(project_root.rglob("test_*.py")) + list(project_root.rglob("*_test.py"))
    tests_dir = project_root / "tests"

    if has_pytest_config or conftest_files:
        results.append(
            DetectedConvention(
                pattern="testing",
                rule="Uses pytest as the test framework",
                confidence=0.95,
                evidence_count=len(test_files),
            )
        )
    elif test_files:
        # Check first test file for unittest vs pytest style
        try:
            sample = test_files[0].read_text(encoding="utf-8")
            if "import unittest" in sample or "class Test" in sample:
                results.append(
                    DetectedConvention(
                        pattern="testing",
                        rule="Uses unittest-style test classes",
                        confidence=0.7,
                        evidence_count=len(test_files),
                    )
                )
            else:
                results.append(
                    DetectedConvention(
                        pattern="testing",
                        rule="Uses pytest (function-style tests)",
                        confidence=0.8,
                        evidence_count=len(test_files),
                    )
                )
        except OSError:
            pass

    if tests_dir.is_dir():
        results.append(
            DetectedConvention(
                pattern="testing",
                rule="Tests live in a top-level `tests/` directory",
                confidence=0.9,
                evidence_count=len(test_files),
            )
        )

    # Check test naming pattern
    prefix_count = len(list(project_root.rglob("test_*.py")))
    suffix_count = len(list(project_root.rglob("*_test.py")))
    if prefix_count > suffix_count and prefix_count > 0:
        results.append(
            DetectedConvention(
                pattern="testing",
                rule="Test files use `test_` prefix naming (e.g., test_module.py)",
                confidence=0.9,
                evidence_count=prefix_count,
            )
        )
    elif suffix_count > prefix_count and suffix_count > 0:
        results.append(
            DetectedConvention(
                pattern="testing",
                rule="Test files use `_test` suffix naming (e.g., module_test.py)",
                confidence=0.9,
                evidence_count=suffix_count,
            )
        )

    return results


def detect_tooling(project_root: Path) -> list[DetectedConvention]:
    """Detect linter, formatter, and build tooling from project configuration.

    Args:
        project_root: Root directory of the project.

    Returns:
        List of detected tooling conventions.
    """
    results: list[DetectedConvention] = []
    pyproject = project_root / "pyproject.toml"

    config_content = ""
    if pyproject.exists():
        try:
            config_content = pyproject.read_text(encoding="utf-8")
        except OSError:
            pass

    # Ruff
    if "[tool.ruff" in config_content or (project_root / "ruff.toml").exists():
        results.append(
            DetectedConvention(
                pattern="tooling",
                rule="Uses ruff for linting and formatting",
                confidence=0.95,
                evidence_count=1,
            )
        )

    # Black
    if "[tool.black" in config_content or (project_root / ".black.toml").exists():
        results.append(
            DetectedConvention(
                pattern="tooling",
                rule="Uses black for code formatting",
                confidence=0.95,
                evidence_count=1,
            )
        )

    # Mypy
    if "[tool.mypy" in config_content or (project_root / "mypy.ini").exists():
        results.append(
            DetectedConvention(
                pattern="tooling",
                rule="Uses mypy for static type checking",
                confidence=0.95,
                evidence_count=1,
            )
        )

    # isort
    if "[tool.isort" in config_content:
        results.append(
            DetectedConvention(
                pattern="tooling",
                rule="Uses isort for import sorting",
                confidence=0.95,
                evidence_count=1,
            )
        )

    # Build backend
    if "hatchling" in config_content:
        results.append(
            DetectedConvention(
                pattern="tooling",
                rule="Uses hatchling as the build backend",
                confidence=0.95,
                evidence_count=1,
            )
        )
    elif "setuptools" in config_content:
        results.append(
            DetectedConvention(
                pattern="tooling",
                rule="Uses setuptools as the build backend",
                confidence=0.95,
                evidence_count=1,
            )
        )
    elif "flit" in config_content:
        results.append(
            DetectedConvention(
                pattern="tooling",
                rule="Uses flit as the build backend",
                confidence=0.95,
                evidence_count=1,
            )
        )

    # Type hints prevalence (check for -> in function signatures)
    setup_cfg = project_root / "setup.cfg"
    if (
        "disallow_untyped_defs" in config_content
        or (setup_cfg.exists() and "disallow_untyped_defs" in setup_cfg.read_text(encoding="utf-8"))
    ):
        results.append(
            DetectedConvention(
                pattern="tooling",
                rule="Enforces type hints on all function definitions (mypy strict)",
                confidence=0.95,
                evidence_count=1,
            )
        )

    return results


def detect_type_hint_usage(file_contents: dict[str, str]) -> list[DetectedConvention]:
    """Detect type hint usage patterns across the codebase.

    Args:
        file_contents: Mapping of file path to file content string.

    Returns:
        List of detected type hint conventions.
    """
    results: list[DetectedConvention] = []
    typed_funcs = 0
    untyped_funcs = 0

    # Match any def line — then check if it contains ->
    def_line_re = re.compile(r"^\s*def\s+\w+\(", re.MULTILINE)
    arrow_re = re.compile(r"->")

    for content in file_contents.values():
        for match in def_line_re.finditer(content):
            # Look at the rest of the line (up to the colon ending the signature)
            start = match.start()
            # Find the end of the signature (the colon after the closing paren)
            rest = content[start:]
            colon_pos = rest.find(":\n")
            if colon_pos == -1:
                colon_pos = rest.find(":\r")
            if colon_pos == -1:
                # single-line file or last line
                colon_pos = len(rest)
            sig = rest[:colon_pos]
            if arrow_re.search(sig):
                typed_funcs += 1
            else:
                untyped_funcs += 1

    total_funcs = typed_funcs + untyped_funcs
    if total_funcs > 5:
        ratio = typed_funcs / total_funcs
        if ratio >= 0.7:
            results.append(
                DetectedConvention(
                    pattern="type_hints",
                    rule="Functions consistently use return type annotations",
                    confidence=round(ratio, 2),
                    evidence_count=typed_funcs,
                )
            )
        elif ratio <= 0.2:
            results.append(
                DetectedConvention(
                    pattern="type_hints",
                    rule="Functions rarely use type annotations",
                    confidence=round(1 - ratio, 2),
                    evidence_count=untyped_funcs,
                )
            )

    return results


# ---------------------------------------------------------------------------
# Main detection orchestrator
# ---------------------------------------------------------------------------


def detect_conventions(
    project_root: Path,
    graph: Any | None = None,
) -> ConventionReport:
    """Run all convention detectors against the project.

    This is the main entry point. It reads source files, extracts symbol info
    from the dependency graph (if available), and runs all detectors.

    Args:
        project_root: Root directory of the project.
        graph: Optional DependencyGraph from the indexer.

    Returns:
        ConventionReport with all detected conventions.
    """
    report = ConventionReport()

    # Collect Python source files
    py_files: list[Path] = []
    for pattern in ("**/*.py",):
        py_files.extend(
            p
            for p in project_root.rglob(pattern)
            if ".musonius" not in str(p)
            and ".venv" not in str(p)
            and "venv" not in str(p)
            and "__pycache__" not in str(p)
            and "node_modules" not in str(p)
            and ".git" not in str(p)
        )

    # Read file contents (capped at 500 files to avoid huge repos)
    file_contents: dict[str, str] = {}
    for py_file in py_files[:500]:
        try:
            file_contents[str(py_file)] = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

    report.files_analyzed = len(file_contents)
    logger.info("Convention detection analyzing %d files", report.files_analyzed)

    # Extract symbols from graph if available
    symbols: list[dict[str, Any]] = []
    if graph is not None:
        for file_info in graph.get_all_files():
            for sym in file_info.symbols:
                symbols.append(
                    {
                        "name": sym.name,
                        "type": sym.type,
                        "file_path": str(sym.file_path),
                    }
                )

    # Run all detectors
    report.conventions.extend(detect_naming_conventions(symbols))
    report.conventions.extend(detect_docstring_style(file_contents))
    report.conventions.extend(detect_import_style(file_contents))
    report.conventions.extend(detect_test_framework(project_root))
    report.conventions.extend(detect_tooling(project_root))
    report.conventions.extend(detect_type_hint_usage(file_contents))

    logger.info("Detected %d conventions", len(report.conventions))
    return report


def store_conventions(
    report: ConventionReport,
    store: Any,
) -> int:
    """Persist detected conventions into the memory store.

    Args:
        report: ConventionReport from detect_conventions().
        store: MemoryStore instance with add_convention() method.

    Returns:
        Number of conventions stored.
    """
    count = 0
    for conv in report.conventions:
        try:
            store.add_convention(
                pattern=conv.pattern,
                rule=conv.rule,
                source="detected",
                confidence=conv.confidence,
            )
            count += 1
        except Exception as exc:
            logger.warning("Failed to store convention '%s': %s", conv.rule, exc)
    return count
