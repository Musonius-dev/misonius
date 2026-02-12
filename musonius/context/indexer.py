"""Tree-sitter based codebase indexer — parses Python files, extracts symbols, builds dependency graph."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

from musonius.context.models import DependencyGraph, FileInfo, Symbol

logger = logging.getLogger(__name__)

PY_LANGUAGE = Language(tspython.language())

# Directories to skip during indexing
SKIP_DIRS = {
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    ".tox",
    ".eggs",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".musonius",
}


class Indexer:
    """Tree-sitter based codebase indexer.

    Parses Python files, extracts symbols (functions, classes, methods,
    imports), and builds a dependency graph.

    Args:
        project_root: Root directory of the project to index.
    """

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self._parser = Parser(PY_LANGUAGE)

    def index_codebase(self) -> DependencyGraph:
        """Parse all Python files and build a dependency graph.

        Returns:
            Complete dependency graph of the codebase.
        """
        graph = DependencyGraph()
        python_files = self._find_python_files()

        logger.info("Indexing %d Python files in %s", len(python_files), self.project_root)

        for file_path in python_files:
            try:
                file_info = self._index_file(file_path)
                graph.add_file(file_info)
                for symbol in file_info.symbols:
                    graph.add_symbol(symbol)
            except Exception as e:
                logger.warning("Failed to index %s: %s", file_path, e)

        # Build import edges
        self._resolve_imports(graph)

        logger.info(
            "Indexed %d files, %d symbols",
            graph.file_count,
            graph.symbol_count,
        )

        return graph

    def index_file(self, file_path: Path) -> FileInfo:
        """Index a single file.

        Args:
            file_path: Path to the Python file.

        Returns:
            FileInfo with extracted symbols.
        """
        return self._index_file(file_path)

    def _find_python_files(self) -> list[Path]:
        """Find all Python files in the project, skipping irrelevant directories."""
        python_files: list[Path] = []

        for path in self.project_root.rglob("*.py"):
            # Skip files in excluded directories
            parts = path.relative_to(self.project_root).parts
            if any(part in SKIP_DIRS for part in parts):
                continue
            python_files.append(path)

        return sorted(python_files)

    def _index_file(self, file_path: Path) -> FileInfo:
        """Parse a single Python file and extract symbols.

        Args:
            file_path: Absolute or relative path to the file.

        Returns:
            FileInfo with symbols and metadata.
        """
        abs_path = file_path if file_path.is_absolute() else self.project_root / file_path
        source = abs_path.read_bytes()
        checksum = hashlib.sha256(source).hexdigest()

        rel_path = abs_path.relative_to(self.project_root)

        tree = self._parser.parse(source)
        root = tree.root_node

        symbols = self._extract_symbols(root, source, rel_path)
        imports = self._extract_imports(root, source)

        return FileInfo(
            path=rel_path,
            checksum=checksum,
            symbols=symbols,
            imports=imports,
        )

    def _extract_symbols(
        self, node: object, source: bytes, file_path: Path, parent: str | None = None
    ) -> list[Symbol]:
        """Recursively extract symbols from an AST node.

        Args:
            node: Tree-sitter node.
            source: Raw source bytes.
            file_path: Relative file path.
            parent: Parent class name, if inside a class.

        Returns:
            List of extracted symbols.
        """
        symbols: list[Symbol] = []

        for child in node.children:  # type: ignore[attr-defined]
            if child.type == "function_definition":
                sym = self._parse_function(child, source, file_path, parent)
                if sym:
                    symbols.append(sym)

            elif child.type == "class_definition":
                sym = self._parse_class(child, source, file_path)
                if sym:
                    symbols.append(sym)
                    # Recurse into class body for methods
                    body = _find_child_by_type(child, "block")
                    if body:
                        class_symbols = self._extract_symbols(
                            body, source, file_path, parent=sym.name
                        )
                        symbols.extend(class_symbols)

            elif child.type == "decorated_definition":
                # Handle decorated functions and classes
                for grandchild in child.children:
                    if grandchild.type == "function_definition":
                        sym = self._parse_function(grandchild, source, file_path, parent)
                        if sym:
                            symbols.append(sym)
                    elif grandchild.type == "class_definition":
                        sym = self._parse_class(grandchild, source, file_path)
                        if sym:
                            symbols.append(sym)
                            body = _find_child_by_type(grandchild, "block")
                            if body:
                                class_symbols = self._extract_symbols(
                                    body, source, file_path, parent=sym.name
                                )
                                symbols.extend(class_symbols)

        return symbols

    def _parse_function(
        self, node: object, source: bytes, file_path: Path, parent: str | None
    ) -> Symbol | None:
        """Extract a Symbol from a function_definition node."""
        name_node = _find_child_by_type(node, "identifier")
        if not name_node:
            return None

        name = _node_text(name_node, source)
        signature = _get_signature(node, source)
        docstring = _get_docstring(node, source)

        symbol_type = "method" if parent else "function"

        return Symbol(
            name=name,
            type=symbol_type,
            file_path=file_path,
            line_number=node.start_point[0] + 1,  # type: ignore[attr-defined]
            end_line_number=node.end_point[0] + 1,  # type: ignore[attr-defined]
            signature=signature,
            docstring=docstring,
            parent=parent,
        )

    def _parse_class(
        self, node: object, source: bytes, file_path: Path
    ) -> Symbol | None:
        """Extract a Symbol from a class_definition node."""
        name_node = _find_child_by_type(node, "identifier")
        if not name_node:
            return None

        name = _node_text(name_node, source)
        signature = _get_signature(node, source)
        docstring = _get_docstring(node, source)

        return Symbol(
            name=name,
            type="class",
            file_path=file_path,
            line_number=node.start_point[0] + 1,  # type: ignore[attr-defined]
            end_line_number=node.end_point[0] + 1,  # type: ignore[attr-defined]
            signature=signature,
            docstring=docstring,
        )

    def _extract_imports(self, root: object, source: bytes) -> list[str]:
        """Extract import statements from the AST root.

        Args:
            root: Root tree-sitter node.
            source: Raw source bytes.

        Returns:
            List of imported module names.
        """
        imports: list[str] = []

        for child in root.children:  # type: ignore[attr-defined]
            if child.type == "import_statement":
                # import foo, bar
                for name_child in child.children:
                    if name_child.type == "dotted_name":
                        imports.append(_node_text(name_child, source))

            elif child.type == "import_from_statement":
                # from foo import bar
                module_node = _find_child_by_type(child, "dotted_name")
                if module_node:
                    imports.append(_node_text(module_node, source))
                else:
                    # Handle relative imports like "from . import foo"
                    relative = _find_child_by_type(child, "relative_import")
                    if relative:
                        imports.append(_node_text(relative, source))

        return imports

    def _resolve_imports(self, graph: DependencyGraph) -> None:
        """Resolve import statements to file-level edges in the graph."""
        all_files = graph.get_all_files()
        module_map: dict[str, str] = {}

        for file_info in all_files:
            # Map module path to file path
            module_path = str(file_info.path).replace("/", ".").replace("\\", ".")
            if module_path.endswith(".py"):
                module_path = module_path[:-3]
            if module_path.endswith(".__init__"):
                module_path = module_path[: -len(".__init__")]
            module_map[module_path] = str(file_info.path)

        for file_info in all_files:
            for imp in file_info.imports:
                # Try to resolve the import to a file in the project
                target = module_map.get(imp)
                if target and target != str(file_info.path):
                    graph.add_dependency(str(file_info.path), target, relation="imports")

    def save_cache(self, graph: DependencyGraph, cache_dir: Path) -> None:
        """Save the dependency graph to a cache directory.

        Args:
            graph: Graph to cache.
            cache_dir: Directory to write cache files.
        """
        cache_dir.mkdir(parents=True, exist_ok=True)

        graph_path = cache_dir / "repo-map.json"
        graph_path.write_text(graph.to_json())

        checksums: dict[str, str] = {}
        for fi in graph.get_all_files():
            checksums[str(fi.path)] = fi.checksum

        checksums_path = cache_dir / "checksums.json"
        checksums_path.write_text(json.dumps(checksums, indent=2))

        logger.info("Saved index cache to %s", cache_dir)

    def load_cache(self, cache_dir: Path) -> DependencyGraph | None:
        """Load a cached dependency graph.

        Args:
            cache_dir: Directory containing cache files.

        Returns:
            Cached graph, or None if cache is invalid.
        """
        graph_path = cache_dir / "repo-map.json"
        if not graph_path.exists():
            return None

        try:
            json_str = graph_path.read_text()
            return DependencyGraph.from_json(json_str, self.project_root)
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning("Invalid cache at %s: %s", cache_dir, e)
            return None

    def needs_reindex(self, cache_dir: Path) -> set[Path]:
        """Check which files have changed since the last index.

        Args:
            cache_dir: Directory containing checksum cache.

        Returns:
            Set of file paths that have changed.
        """
        checksums_path = cache_dir / "checksums.json"
        if not checksums_path.exists():
            return set(self._find_python_files())

        try:
            old_checksums = json.loads(checksums_path.read_text())
        except (json.JSONDecodeError, OSError):
            return set(self._find_python_files())

        changed: set[Path] = set()
        for file_path in self._find_python_files():
            rel_path = str(file_path.relative_to(self.project_root))
            content = file_path.read_bytes()
            current_checksum = hashlib.sha256(content).hexdigest()

            if old_checksums.get(rel_path) != current_checksum:
                changed.add(file_path)

        return changed


# --- Tree-sitter helper functions ---


def _find_child_by_type(node: object, type_name: str) -> object | None:
    """Find the first child of a node with a given type."""
    for child in node.children:  # type: ignore[attr-defined]
        if child.type == type_name:  # type: ignore[attr-defined]
            result: object = child
            return result
    return None


def _node_text(node: object, source: bytes) -> str:
    """Extract the text of a tree-sitter node."""
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")  # type: ignore[attr-defined]


def _get_signature(node: object, source: bytes) -> str:
    """Extract the first line (signature) of a definition."""
    text = _node_text(node, source)
    first_line = text.split("\n")[0].rstrip(":")
    return first_line.strip()


def _get_docstring(node: object, source: bytes) -> str | None:
    """Extract the docstring from a function or class definition."""
    body = _find_child_by_type(node, "block")
    if not body:
        return None

    for child in body.children:  # type: ignore[attr-defined]
        if child.type == "expression_statement":  # type: ignore[attr-defined]
            for grandchild in child.children:  # type: ignore[attr-defined]
                if grandchild.type == "string":  # type: ignore[attr-defined]
                    text = _node_text(grandchild, source)
                    # Strip triple quotes
                    if text.startswith('"""') or text.startswith("'''"):
                        return text[3:-3].strip()
                    elif text.startswith('"') or text.startswith("'"):
                        return text[1:-1].strip()
            break
        elif child.type != "comment":  # type: ignore[attr-defined]
            break

    return None
