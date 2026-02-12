"""Tests for the tree-sitter indexer."""

from __future__ import annotations

from pathlib import Path

import pytest

from musonius.context.indexer import Indexer
from musonius.context.models import DependencyGraph, FileInfo, Symbol

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture
def indexer() -> Indexer:
    """Create an indexer pointed at the sample project."""
    return Indexer(FIXTURES_DIR)


class TestIndexer:
    """Tests for the Indexer class."""

    def test_index_codebase(self, indexer: Indexer) -> None:
        """Should index all Python files in the fixture project."""
        graph = indexer.index_codebase()
        assert graph.file_count >= 2
        assert graph.symbol_count > 0

    def test_extracts_functions(self, indexer: Indexer) -> None:
        """Should extract function definitions."""
        graph = indexer.index_codebase()
        all_files = graph.get_all_files()

        # Find main.py symbols
        main_file = next((f for f in all_files if f.path.name == "main.py"), None)
        assert main_file is not None

        func_names = [s.name for s in main_file.symbols if s.type == "function"]
        assert "hello" in func_names
        assert "goodbye" in func_names

    def test_extracts_classes(self, indexer: Indexer) -> None:
        """Should extract class definitions."""
        graph = indexer.index_codebase()
        all_files = graph.get_all_files()

        main_file = next((f for f in all_files if f.path.name == "main.py"), None)
        assert main_file is not None

        class_names = [s.name for s in main_file.symbols if s.type == "class"]
        assert "Greeter" in class_names

    def test_extracts_methods(self, indexer: Indexer) -> None:
        """Should extract methods inside classes."""
        graph = indexer.index_codebase()
        all_files = graph.get_all_files()

        main_file = next((f for f in all_files if f.path.name == "main.py"), None)
        assert main_file is not None

        methods = [s for s in main_file.symbols if s.type == "method"]
        method_names = [m.name for m in methods]
        assert "greet" in method_names
        assert "farewell" in method_names

        # Methods should have parent set
        greet = next(m for m in methods if m.name == "greet")
        assert greet.parent == "Greeter"

    def test_extracts_docstrings(self, indexer: Indexer) -> None:
        """Should extract docstrings from functions."""
        graph = indexer.index_codebase()
        all_files = graph.get_all_files()

        main_file = next((f for f in all_files if f.path.name == "main.py"), None)
        assert main_file is not None

        hello_func = next(
            (s for s in main_file.symbols if s.name == "hello" and s.type == "function"),
            None,
        )
        assert hello_func is not None
        assert hello_func.docstring is not None
        assert "hello" in hello_func.docstring.lower()

    def test_extracts_imports(self, indexer: Indexer) -> None:
        """Should extract import statements."""
        graph = indexer.index_codebase()
        all_files = graph.get_all_files()

        main_file = next((f for f in all_files if f.path.name == "main.py"), None)
        assert main_file is not None
        assert len(main_file.imports) > 0

    def test_handles_empty_file(self, tmp_path: Path) -> None:
        """Should handle empty Python files gracefully."""
        empty_file = tmp_path / "empty.py"
        empty_file.write_text("")

        indexer = Indexer(tmp_path)
        file_info = indexer.index_file(empty_file)
        assert file_info.path.name == "empty.py"
        assert len(file_info.symbols) == 0

    def test_handles_syntax_error(self, tmp_path: Path) -> None:
        """Should handle files with syntax errors gracefully."""
        bad_file = tmp_path / "bad.py"
        bad_file.write_text("def broken(:\n  pass\n")

        indexer = Indexer(tmp_path)
        # Should not raise
        graph = indexer.index_codebase()
        assert graph.file_count >= 0


class TestDependencyGraph:
    """Tests for the DependencyGraph class."""

    def test_add_file(self) -> None:
        """Should add files to the graph."""
        graph = DependencyGraph()
        fi = FileInfo(path=Path("test.py"), checksum="abc123")
        graph.add_file(fi)
        assert graph.file_count == 1

    def test_add_symbol(self) -> None:
        """Should add symbols to the graph."""
        graph = DependencyGraph()
        fi = FileInfo(
            path=Path("test.py"),
            checksum="abc",
            symbols=[
                Symbol(
                    name="hello",
                    type="function",
                    file_path=Path("test.py"),
                    line_number=1,
                    signature="def hello()",
                )
            ],
        )
        graph.add_file(fi)
        for s in fi.symbols:
            graph.add_symbol(s)
        assert graph.symbol_count == 1

    def test_json_roundtrip(self) -> None:
        """Should serialize and deserialize correctly."""
        graph = DependencyGraph()
        fi = FileInfo(
            path=Path("test.py"),
            checksum="abc",
            symbols=[
                Symbol(
                    name="hello",
                    type="function",
                    file_path=Path("test.py"),
                    line_number=1,
                    signature="def hello()",
                    docstring="Says hello.",
                )
            ],
        )
        graph.add_file(fi)
        for s in fi.symbols:
            graph.add_symbol(s)

        json_str = graph.to_json()
        restored = DependencyGraph.from_json(json_str, Path("."))

        assert restored.file_count == 1
        assert restored.symbol_count == 1

    def test_get_dependencies(self) -> None:
        """Should track dependency edges."""
        graph = DependencyGraph()
        graph.graph.add_node("a.py", type="file")
        graph.graph.add_node("b.py", type="file")
        graph.add_dependency("a.py", "b.py", relation="imports")

        deps = graph.get_dependencies("a.py")
        assert "b.py" in deps

    def test_get_dependents(self) -> None:
        """Should find reverse dependencies."""
        graph = DependencyGraph()
        graph.graph.add_node("a.py", type="file")
        graph.graph.add_node("b.py", type="file")
        graph.add_dependency("a.py", "b.py", relation="imports")

        dependents = graph.get_dependents("b.py")
        assert "a.py" in dependents
