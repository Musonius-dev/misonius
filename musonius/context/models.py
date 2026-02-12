"""Data models for the context engine — Symbol, DependencyGraph."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

logger = logging.getLogger(__name__)


@dataclass
class Symbol:
    """A code symbol extracted by tree-sitter.

    Attributes:
        name: Symbol name (function name, class name, etc.).
        type: Symbol kind — "function", "class", "method", "import".
        file_path: Path to the file containing the symbol.
        line_number: 1-based line number of the definition.
        end_line_number: 1-based end line number of the definition.
        signature: The full signature string.
        docstring: Docstring if present, None otherwise.
        parent: Parent symbol name (for methods inside classes).
    """

    name: str
    type: str
    file_path: Path
    line_number: int
    end_line_number: int = 0
    signature: str = ""
    docstring: str | None = None
    parent: str | None = None

    @property
    def qualified_name(self) -> str:
        """Fully qualified name including parent class."""
        if self.parent:
            return f"{self.parent}.{self.name}"
        return self.name

    @property
    def node_id(self) -> str:
        """Unique node ID for the dependency graph."""
        return f"{self.file_path}::{self.qualified_name}"


@dataclass
class FileInfo:
    """Metadata about an indexed file.

    Attributes:
        path: Relative path from project root.
        checksum: SHA-256 hex digest of file contents.
        symbols: Symbols found in this file.
        imports: Import statements found in this file.
    """

    path: Path
    checksum: str = ""
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)


class DependencyGraph:
    """Directed graph of file and symbol dependencies.

    Wraps NetworkX DiGraph to provide a clean API for building
    and querying the codebase dependency graph.
    """

    def __init__(self) -> None:
        self.graph: nx.DiGraph = nx.DiGraph()
        self._files: dict[str, FileInfo] = {}

    @property
    def file_count(self) -> int:
        """Number of indexed files."""
        return len(self._files)

    @property
    def symbol_count(self) -> int:
        """Total number of symbols across all files."""
        return sum(len(fi.symbols) for fi in self._files.values())

    def add_file(self, file_info: FileInfo) -> None:
        """Add a file node to the graph.

        Args:
            file_info: File metadata.
        """
        path_str = str(file_info.path)
        self._files[path_str] = file_info
        self.graph.add_node(path_str, type="file", checksum=file_info.checksum)

    def add_symbol(self, symbol: Symbol) -> None:
        """Add a symbol node to the graph.

        Args:
            symbol: Symbol to add.
        """
        self.graph.add_node(
            symbol.node_id,
            type="symbol",
            symbol_type=symbol.type,
            name=symbol.name,
            file=str(symbol.file_path),
            line=symbol.line_number,
        )
        # Edge from file to symbol
        self.graph.add_edge(str(symbol.file_path), symbol.node_id, relation="defines")

    def add_dependency(self, from_node: str, to_node: str, relation: str = "imports") -> None:
        """Add a dependency edge between nodes.

        Args:
            from_node: Source node ID.
            to_node: Target node ID.
            relation: Relationship type.
        """
        self.graph.add_edge(from_node, to_node, relation=relation)

    def get_file_symbols(self, file_path: Path) -> list[Symbol]:
        """Get all symbols defined in a file.

        Args:
            file_path: Path to the file.

        Returns:
            List of symbols in the file.
        """
        path_str = str(file_path)
        if path_str in self._files:
            return self._files[path_str].symbols
        return []

    def get_dependencies(self, node: str) -> list[str]:
        """Get all nodes that a given node depends on.

        Args:
            node: Node ID to query.

        Returns:
            List of dependency node IDs.
        """
        if node not in self.graph:
            return []
        return list(self.graph.successors(node))

    def get_dependents(self, node: str) -> list[str]:
        """Get all nodes that depend on a given node.

        Args:
            node: Node ID to query.

        Returns:
            List of dependent node IDs.
        """
        if node not in self.graph:
            return []
        return list(self.graph.predecessors(node))

    def get_all_files(self) -> list[FileInfo]:
        """Get all indexed files.

        Returns:
            List of FileInfo objects.
        """
        return list(self._files.values())

    def to_json(self) -> str:
        """Serialize the graph to JSON.

        Returns:
            JSON string representation.
        """
        data: dict[str, Any] = {
            "files": {},
            "edges": [],
        }
        for path_str, file_info in self._files.items():
            data["files"][path_str] = {
                "checksum": file_info.checksum,
                "imports": file_info.imports,
                "symbols": [
                    {
                        "name": s.name,
                        "type": s.type,
                        "line": s.line_number,
                        "end_line": s.end_line_number,
                        "signature": s.signature,
                        "docstring": s.docstring,
                        "parent": s.parent,
                    }
                    for s in file_info.symbols
                ],
            }
        for u, v, attrs in self.graph.edges(data=True):
            data["edges"].append({"from": u, "to": v, "relation": attrs.get("relation", "")})

        return json.dumps(data, indent=2)

    @classmethod
    def from_json(cls, json_str: str, project_root: Path) -> DependencyGraph:
        """Deserialize a graph from JSON.

        Args:
            json_str: JSON string from to_json().
            project_root: Project root for resolving paths.

        Returns:
            Reconstructed DependencyGraph.
        """
        data = json.loads(json_str)
        graph = cls()

        for path_str, file_data in data.get("files", {}).items():
            symbols = [
                Symbol(
                    name=s["name"],
                    type=s["type"],
                    file_path=Path(path_str),
                    line_number=s["line"],
                    end_line_number=s.get("end_line", 0),
                    signature=s.get("signature", ""),
                    docstring=s.get("docstring"),
                    parent=s.get("parent"),
                )
                for s in file_data.get("symbols", [])
            ]
            file_info = FileInfo(
                path=Path(path_str),
                checksum=file_data.get("checksum", ""),
                symbols=symbols,
                imports=file_data.get("imports", []),
            )
            graph.add_file(file_info)
            for symbol in symbols:
                graph.add_symbol(symbol)

        for edge in data.get("edges", []):
            graph.add_dependency(edge["from"], edge["to"], edge.get("relation", ""))

        return graph
