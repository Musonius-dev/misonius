"""Tests for the convention detection module."""

from __future__ import annotations

from pathlib import Path

import pytest

from musonius.memory.convention_detector import (
    ConventionReport,
    DetectedConvention,
    detect_conventions,
    detect_docstring_style,
    detect_import_style,
    detect_naming_conventions,
    detect_test_framework,
    detect_tooling,
    detect_type_hint_usage,
    store_conventions,
)
from musonius.memory.store import MemoryStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture
def store(tmp_path: Path) -> MemoryStore:
    """Create a temporary memory store."""
    db_path = tmp_path / "test.db"
    s = MemoryStore(db_path)
    s.initialize()
    return s


# ---------------------------------------------------------------------------
# Naming conventions
# ---------------------------------------------------------------------------


class TestNamingConventions:
    """Tests for detect_naming_conventions."""

    def test_detects_snake_case_functions(self) -> None:
        """Should detect snake_case as dominant function naming."""
        symbols = [
            {"name": "get_user", "type": "function"},
            {"name": "load_config", "type": "function"},
            {"name": "parse_input", "type": "function"},
            {"name": "save_result", "type": "function"},
        ]
        results = detect_naming_conventions(symbols)
        func_conv = [r for r in results if "function" in r.rule.lower() or "method" in r.rule.lower()]
        assert len(func_conv) == 1
        assert "snake_case" in func_conv[0].rule

    def test_detects_camel_case_functions(self) -> None:
        """Should detect camelCase as dominant function naming."""
        symbols = [
            {"name": "getUser", "type": "function"},
            {"name": "loadConfig", "type": "function"},
            {"name": "parseInput", "type": "function"},
            {"name": "saveResult", "type": "function"},
        ]
        results = detect_naming_conventions(symbols)
        func_conv = [r for r in results if "function" in r.rule.lower() or "method" in r.rule.lower()]
        assert len(func_conv) == 1
        assert "camelCase" in func_conv[0].rule

    def test_detects_pascal_case_classes(self) -> None:
        """Should detect PascalCase as dominant class naming."""
        symbols = [
            {"name": "UserService", "type": "class"},
            {"name": "ConfigLoader", "type": "class"},
            {"name": "InputParser", "type": "class"},
        ]
        results = detect_naming_conventions(symbols)
        class_conv = [r for r in results if "class" in r.rule.lower()]
        assert len(class_conv) == 1
        assert "PascalCase" in class_conv[0].rule

    def test_skips_private_names(self) -> None:
        """Should skip names starting with underscore."""
        symbols = [
            {"name": "_private", "type": "function"},
            {"name": "__dunder", "type": "method"},
            {"name": "public_func", "type": "function"},
        ]
        results = detect_naming_conventions(symbols)
        # Should have at most one result, based on the single public function
        for r in results:
            assert "_private" not in r.rule
            assert "__dunder" not in r.rule

    def test_empty_symbols(self) -> None:
        """Should return nothing for empty symbol list."""
        results = detect_naming_conventions([])
        assert len(results) == 0

    def test_confidence_score(self) -> None:
        """Should report high confidence when naming is consistent."""
        symbols = [
            {"name": "func_a", "type": "function"},
            {"name": "func_b", "type": "function"},
            {"name": "func_c", "type": "function"},
            {"name": "func_d", "type": "function"},
            {"name": "funcE", "type": "function"},  # One outlier
        ]
        results = detect_naming_conventions(symbols)
        func_conv = [r for r in results if "function" in r.rule.lower() or "method" in r.rule.lower()]
        assert len(func_conv) == 1
        assert func_conv[0].confidence >= 0.6


# ---------------------------------------------------------------------------
# Docstring detection
# ---------------------------------------------------------------------------


class TestDocstringDetection:
    """Tests for detect_docstring_style."""

    def test_detects_google_style(self) -> None:
        """Should detect Google-style docstrings."""
        contents = {
            "a.py": '''
def foo():
    """Do something.

    Args:
        x: The input.

    Returns:
        The result.
    """
    pass
'''
        }
        results = detect_docstring_style(contents)
        assert len(results) == 1
        assert "Google" in results[0].rule

    def test_detects_numpy_style(self) -> None:
        """Should detect NumPy-style docstrings."""
        contents = {
            "a.py": '''
def foo():
    """Do something.

    Parameters
    ----------
    x : int
        The input.

    Returns
    -------
    int
        The result.
    """
    pass
'''
        }
        results = detect_docstring_style(contents)
        assert len(results) == 1
        assert "NumPy" in results[0].rule

    def test_detects_sphinx_style(self) -> None:
        """Should detect Sphinx-style docstrings."""
        contents = {
            "a.py": '''
def foo():
    """Do something.

    :param x: The input.
    :returns: The result.
    :rtype: int
    """
    pass
'''
        }
        results = detect_docstring_style(contents)
        assert len(results) == 1
        assert "Sphinx" in results[0].rule

    def test_no_docstrings(self) -> None:
        """Should report no docstrings when none found (with enough files)."""
        contents = {
            "a.py": "x = 1",
            "b.py": "y = 2",
            "c.py": "z = 3",
            "d.py": "w = 4",
        }
        results = detect_docstring_style(contents)
        assert len(results) == 1
        assert "No docstrings" in results[0].rule


# ---------------------------------------------------------------------------
# Import detection
# ---------------------------------------------------------------------------


class TestImportDetection:
    """Tests for detect_import_style."""

    def test_detects_future_annotations(self) -> None:
        """Should detect from __future__ import annotations usage."""
        contents = {
            "a.py": "from __future__ import annotations\nimport os\n",
            "b.py": "from __future__ import annotations\nimport sys\n",
        }
        results = detect_import_style(contents)
        future_conv = [r for r in results if "__future__" in r.rule]
        assert len(future_conv) == 1
        assert future_conv[0].confidence == 1.0

    def test_detects_absolute_imports(self) -> None:
        """Should detect preference for absolute imports."""
        contents = {
            "a.py": "import os\nimport sys\nfrom pathlib import Path\n",
            "b.py": "import json\nfrom typing import Any\n",
        }
        results = detect_import_style(contents)
        abs_conv = [r for r in results if "absolute" in r.rule.lower()]
        assert len(abs_conv) == 1


# ---------------------------------------------------------------------------
# Test framework detection
# ---------------------------------------------------------------------------


class TestTestFrameworkDetection:
    """Tests for detect_test_framework."""

    def test_detects_pytest(self, tmp_path: Path) -> None:
        """Should detect pytest from pyproject.toml config."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.pytest.ini_options]\ntestpaths = ['tests']\n")

        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_foo.py").write_text("def test_bar(): pass\n")

        results = detect_test_framework(tmp_path)
        pytest_conv = [r for r in results if "pytest" in r.rule.lower()]
        assert len(pytest_conv) >= 1

    def test_detects_tests_directory(self, tmp_path: Path) -> None:
        """Should detect that tests live in tests/ directory."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_a.py").write_text("def test_a(): pass\n")

        results = detect_test_framework(tmp_path)
        dir_conv = [r for r in results if "tests/" in r.rule]
        assert len(dir_conv) == 1

    def test_detects_prefix_naming(self, tmp_path: Path) -> None:
        """Should detect test_ prefix naming convention."""
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_one.py").write_text("")
        (tests_dir / "test_two.py").write_text("")

        results = detect_test_framework(tmp_path)
        prefix_conv = [r for r in results if "test_" in r.rule and "prefix" in r.rule]
        assert len(prefix_conv) == 1


# ---------------------------------------------------------------------------
# Tooling detection
# ---------------------------------------------------------------------------


class TestToolingDetection:
    """Tests for detect_tooling."""

    def test_detects_ruff(self, tmp_path: Path) -> None:
        """Should detect ruff from pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.ruff]\ntarget-version = 'py312'\n")

        results = detect_tooling(tmp_path)
        ruff_conv = [r for r in results if "ruff" in r.rule.lower()]
        assert len(ruff_conv) == 1

    def test_detects_mypy(self, tmp_path: Path) -> None:
        """Should detect mypy from pyproject.toml."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text("[tool.mypy]\npython_version = '3.12'\n")

        results = detect_tooling(tmp_path)
        mypy_conv = [r for r in results if "mypy" in r.rule.lower()]
        assert len(mypy_conv) == 1

    def test_detects_hatchling(self, tmp_path: Path) -> None:
        """Should detect hatchling build backend."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[build-system]\nrequires = ["hatchling"]\n')

        results = detect_tooling(tmp_path)
        hatch_conv = [r for r in results if "hatchling" in r.rule.lower()]
        assert len(hatch_conv) == 1

    def test_no_config(self, tmp_path: Path) -> None:
        """Should return nothing when no pyproject.toml exists."""
        results = detect_tooling(tmp_path)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Type hint detection
# ---------------------------------------------------------------------------


class TestTypeHintDetection:
    """Tests for detect_type_hint_usage."""

    def test_detects_consistent_type_hints(self) -> None:
        """Should detect consistent return type annotations."""
        contents = {
            "a.py": "def foo(x: int) -> str:\n    pass\ndef bar(y: float) -> int:\n    pass\n",
            "b.py": "def baz() -> None:\n    pass\ndef qux(z: str) -> list:\n    pass\n",
            "c.py": "def alpha() -> dict:\n    pass\ndef beta(a: int) -> bool:\n    pass\n",
        }
        results = detect_type_hint_usage(contents)
        assert len(results) == 1
        assert "consistently" in results[0].rule.lower() or "annotation" in results[0].rule.lower()
        assert results[0].confidence >= 0.7

    def test_detects_missing_type_hints(self) -> None:
        """Should detect lack of type annotations."""
        contents = {
            "a.py": "def foo(x):\n    pass\ndef bar(y):\n    pass\n",
            "b.py": "def baz():\n    pass\ndef qux(z):\n    pass\n",
            "c.py": "def alpha():\n    pass\ndef beta(a):\n    pass\n",
        }
        results = detect_type_hint_usage(contents)
        assert len(results) == 1
        assert "rarely" in results[0].rule.lower()


# ---------------------------------------------------------------------------
# Full detection orchestration
# ---------------------------------------------------------------------------


class TestFullDetection:
    """Tests for the full detect_conventions orchestrator."""

    def test_detects_conventions_on_sample_project(self) -> None:
        """Should detect conventions from the sample fixture project."""
        report = detect_conventions(FIXTURES_DIR)
        assert report.files_analyzed >= 2
        assert len(report.conventions) > 0

    def test_detects_conventions_on_musonius_itself(self) -> None:
        """Should detect conventions from the Musonius project root."""
        project_root = Path(__file__).parent.parent
        report = detect_conventions(project_root)
        assert report.files_analyzed > 10
        assert len(report.conventions) > 3

        # Should detect Google-style docstrings (Musonius uses them)
        docstring_convs = [c for c in report.conventions if c.pattern == "docstring"]
        assert len(docstring_convs) >= 1
        assert "Google" in docstring_convs[0].rule

    def test_stores_conventions(self, store: MemoryStore) -> None:
        """Should persist conventions to the memory store."""
        report = ConventionReport(
            conventions=[
                DetectedConvention(pattern="naming", rule="Functions use snake_case", confidence=0.95),
                DetectedConvention(pattern="tooling", rule="Uses ruff", confidence=0.9),
            ],
            files_analyzed=10,
        )
        count = store_conventions(report, store)
        assert count == 2

        stored = store.get_all_conventions()
        assert len(stored) == 2
        rules = [c["rule"] for c in stored]
        assert "Functions use snake_case" in rules
        assert "Uses ruff" in rules
