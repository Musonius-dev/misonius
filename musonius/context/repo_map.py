"""Multi-level repo map generator — produces token-budgeted codebase overviews."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from musonius.context.budget import count_tokens, truncate_to_budget
from musonius.context.models import DependencyGraph, FileInfo

if TYPE_CHECKING:
    from musonius.context.indexer import Indexer

logger = logging.getLogger(__name__)


@dataclass
class FileScore:
    """Relevance score for a file used during prioritization.

    Attributes:
        file_info: The indexed file metadata.
        score: Combined relevance score (higher = more relevant).
        is_relevant: Whether the file was explicitly listed as relevant.
        is_dependency: Whether the file is a direct dependency of a relevant file.
        is_dependent: Whether the file depends on a relevant file.
        mtime: Last modification time (epoch seconds), or 0.0 if unknown.
    """

    file_info: FileInfo
    score: float = 0.0
    is_relevant: bool = False
    is_dependency: bool = False
    is_dependent: bool = False
    mtime: float = 0.0


class RepoMapGenerator:
    """Generates multi-level repository maps from the codebase index.

    Levels:
        L0 — File paths only
        L1 — Paths + function/class signatures
        L2 — Signatures + docstrings
        L3 — Full file contents

    Args:
        indexer: The codebase indexer to read data from.
    """

    # Scoring weights for file prioritization
    SCORE_RELEVANT: float = 100.0
    SCORE_DEPENDENCY: float = 50.0
    SCORE_DEPENDENT: float = 30.0
    SCORE_RECENT_MAX: float = 20.0

    def __init__(self, indexer: Indexer) -> None:
        self.indexer = indexer

    def generate(
        self,
        level: int,
        relevant_files: list[Path] | None = None,
        token_budget: int = 10_000,
    ) -> str:
        """Generate a repo map at the specified detail level.

        Args:
            level: Detail level 0-3.
            relevant_files: Files to prioritize (shown first, at higher detail).
            token_budget: Maximum tokens for the output.

        Returns:
            Formatted repo map string.
        """
        if level < 0 or level > 3:
            raise ValueError(f"Level must be 0-3, got {level}")

        graph = self.indexer.index_codebase()
        all_files = graph.get_all_files()

        if not all_files:
            return "# Repository Map\n\n(empty project)"

        prioritized = self._prioritize_files(all_files, relevant_files or [], graph)

        generators = {
            0: self._generate_l0,
            1: self._generate_l1,
            2: self._generate_l2,
            3: self._generate_l3,
        }

        generator = generators[level]
        return generator(prioritized, token_budget)

    def _score_file(
        self,
        file_info: FileInfo,
        relevant_set: set[str],
        dependency_set: set[str],
        dependent_set: set[str],
        mtime_map: dict[str, float],
        max_mtime: float,
        min_mtime: float,
    ) -> FileScore:
        """Compute a relevance score for a single file.

        Args:
            file_info: The file to score.
            relevant_set: Paths explicitly marked as relevant.
            dependency_set: Paths that relevant files depend on.
            dependent_set: Paths that depend on relevant files.
            mtime_map: Mapping of path strings to modification times.
            max_mtime: Most recent modification time across all files.
            min_mtime: Oldest modification time across all files.

        Returns:
            FileScore with computed relevance score.
        """
        path_str = str(file_info.path)
        score = 0.0

        is_relevant = path_str in relevant_set
        is_dependency = path_str in dependency_set
        is_dependent = path_str in dependent_set

        if is_relevant:
            score += self.SCORE_RELEVANT
        if is_dependency:
            score += self.SCORE_DEPENDENCY
        if is_dependent:
            score += self.SCORE_DEPENDENT

        # Recency bonus: normalized 0.0-1.0 scaled by SCORE_RECENT_MAX
        mtime = mtime_map.get(path_str, 0.0)
        mtime_range = max_mtime - min_mtime
        if mtime_range > 0 and mtime > 0:
            recency = (mtime - min_mtime) / mtime_range
            score += recency * self.SCORE_RECENT_MAX

        return FileScore(
            file_info=file_info,
            score=score,
            is_relevant=is_relevant,
            is_dependency=is_dependency,
            is_dependent=is_dependent,
            mtime=mtime,
        )

    def _prioritize_files(
        self,
        files: list[FileInfo],
        relevant: list[Path],
        graph: DependencyGraph,
    ) -> list[FileInfo]:
        """Sort files by relevance score: explicit > dependency > recent > alphabetical.

        Args:
            files: All indexed files.
            relevant: Paths to prioritize.
            graph: Dependency graph for computing dependency proximity.

        Returns:
            Sorted file list with most relevant first.
        """
        relevant_set = {str(p) for p in relevant}

        # Gather direct dependencies and dependents of relevant files
        dependency_set: set[str] = set()
        dependent_set: set[str] = set()

        for path_str in relevant_set:
            for dep in graph.get_dependencies(path_str):
                # Only include file-level nodes (not symbol nodes)
                if dep in graph._files:
                    dependency_set.add(dep)
            for dep in graph.get_dependents(path_str):
                if dep in graph._files:
                    dependent_set.add(dep)

        # Exclude the relevant files themselves from dependency/dependent sets
        dependency_set -= relevant_set
        dependent_set -= relevant_set

        # Collect modification times
        mtime_map = self._collect_mtimes(files)
        mtimes = [t for t in mtime_map.values() if t > 0]
        max_mtime = max(mtimes) if mtimes else 0.0
        min_mtime = min(mtimes) if mtimes else 0.0

        # Score all files
        scored = [
            self._score_file(
                f, relevant_set, dependency_set, dependent_set,
                mtime_map, max_mtime, min_mtime,
            )
            for f in files
        ]

        # Sort: highest score first, then alphabetical for ties
        scored.sort(key=lambda s: (-s.score, str(s.file_info.path)))

        return [s.file_info for s in scored]

    def _collect_mtimes(self, files: list[FileInfo]) -> dict[str, float]:
        """Collect file modification times.

        Args:
            files: Files to check.

        Returns:
            Mapping of path strings to modification epoch times.
        """
        mtime_map: dict[str, float] = {}
        for f in files:
            try:
                abs_path = self.indexer.project_root / f.path
                mtime_map[str(f.path)] = os.path.getmtime(abs_path)
            except OSError:
                mtime_map[str(f.path)] = 0.0
        return mtime_map

    def _generate_l0(self, files: list[FileInfo], budget: int) -> str:
        """L0: File paths only."""
        lines = ["# Repository Map (L0 — File Paths)", ""]
        for idx, f in enumerate(files):
            line = str(f.path)
            lines.append(line)
            if count_tokens("\n".join(lines)) > budget:
                lines.pop()
                remaining = len(files) - idx
                lines.append(f"... and {remaining} more files")
                break

        return "\n".join(lines)

    def _generate_l1(self, files: list[FileInfo], budget: int) -> str:
        """L1: Paths + signatures."""
        lines = ["# Repository Map (L1 — Signatures)", ""]
        for f in files:
            file_lines: list[str] = [str(f.path)]
            for sym in f.symbols:
                indent = "    " if sym.parent else "  "
                if sym.type == "class":
                    file_lines.append(f"  class {sym.name}:")
                elif sym.type in ("function", "method"):
                    file_lines.append(f"{indent}{sym.signature}")
            file_lines.append("")

            # Check budget before adding this file's block
            candidate = "\n".join(lines + file_lines)
            if count_tokens(candidate) > budget:
                lines.append(f"... truncated (budget: {budget} tokens)")
                break

            lines.extend(file_lines)

        return "\n".join(lines)

    def _generate_l2(self, files: list[FileInfo], budget: int) -> str:
        """L2: Signatures + docstrings."""
        lines = ["# Repository Map (L2 — Documented)", ""]
        for f in files:
            file_lines: list[str] = [str(f.path)]
            for sym in f.symbols:
                indent = "    " if sym.parent else "  "
                if sym.type == "class":
                    file_lines.append(f"  class {sym.name}:")
                    if sym.docstring:
                        file_lines.append(f"    \"\"\"{sym.docstring}\"\"\"")
                elif sym.type in ("function", "method"):
                    file_lines.append(f"{indent}{sym.signature}")
                    if sym.docstring:
                        doc_indent = indent + "  "
                        file_lines.append(f"{doc_indent}\"\"\"{sym.docstring}\"\"\"")
            file_lines.append("")

            candidate = "\n".join(lines + file_lines)
            if count_tokens(candidate) > budget:
                lines.append(f"... truncated (budget: {budget} tokens)")
                break

            lines.extend(file_lines)

        return "\n".join(lines)

    def _generate_l3(self, files: list[FileInfo], budget: int) -> str:
        """L3: Full file contents."""
        lines = ["# Repository Map (L3 — Full Contents)", ""]
        remaining_budget = budget - count_tokens("\n".join(lines))

        for f in files:
            header = f"## {f.path}"
            try:
                abs_path = self.indexer.project_root / f.path
                content = abs_path.read_text()
            except OSError:
                content = "(file not readable)"

            file_block = f"{header}\n\n```python\n{content}\n```\n"
            file_tokens = count_tokens(file_block)

            if file_tokens > remaining_budget:
                if remaining_budget > 50:
                    truncated = truncate_to_budget(content, remaining_budget - 50)
                    file_block = (
                        f"{header}\n\n```python\n{truncated}\n... (truncated)\n```\n"
                    )
                    lines.append(file_block)
                break

            lines.append(file_block)
            remaining_budget -= file_tokens

        return "\n".join(lines)
