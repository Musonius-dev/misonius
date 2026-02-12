"""Diff analysis — extracts and structures git diff information."""

from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class FileChange:
    """A structured representation of changes to a single file.

    Attributes:
        file_path: Path to the changed file.
        change_type: Type of change (added, modified, deleted, renamed).
        added_lines: Lines added (without leading +).
        removed_lines: Lines removed (without leading -).
        hunks: Raw hunk strings from the diff.
        added_count: Number of added lines.
        removed_count: Number of removed lines.
    """

    file_path: str
    change_type: str = "modified"
    added_lines: list[str] = field(default_factory=list)
    removed_lines: list[str] = field(default_factory=list)
    hunks: list[str] = field(default_factory=list)
    added_count: int = 0
    removed_count: int = 0


@dataclass
class Diff:
    """A complete git diff with metadata.

    Attributes:
        raw: The raw diff string.
        base: Base commit/branch.
        target: Target commit/branch (None = working tree).
        files: List of changed files.
    """

    raw: str
    base: str = "HEAD"
    target: str | None = None
    files: list[FileChange] = field(default_factory=list)


class DiffAnalyzer:
    """Extracts and analyzes git diffs.

    Handles git diff extraction via subprocess and parses the output
    into structured FileChange objects for downstream analysis.

    Args:
        repo_path: Path to the git repository root.
    """

    def __init__(self, repo_path: Path | None = None) -> None:
        self.repo_path = repo_path or Path.cwd()

    def get_diff(
        self,
        base: str = "HEAD",
        target: str | None = None,
        staged: bool = False,
    ) -> Diff:
        """Get git diff between base and target.

        Args:
            base: Base commit/branch.
            target: Target commit/branch (None = working tree).
            staged: If True, show only staged changes.

        Returns:
            Diff object with parsed file changes.

        Raises:
            RuntimeError: If git diff command fails.
        """
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--staged")
        elif target:
            cmd.extend([base, target])
        else:
            cmd.append(base)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=self.repo_path,
                check=True,
            )
            raw_diff = result.stdout
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"git diff failed: {e.stderr}") from e
        except FileNotFoundError as e:
            raise RuntimeError("git not found on PATH") from e

        diff = Diff(raw=raw_diff, base=base, target=target)
        diff.files = self.extract_changes(raw_diff)
        return diff

    def extract_changes(self, raw_diff: str) -> list[FileChange]:
        """Extract structured changes from a raw diff string.

        Args:
            raw_diff: Raw git diff output.

        Returns:
            List of FileChange objects with parsed line data.
        """
        if not raw_diff.strip():
            return []

        files: list[FileChange] = []
        current_file: FileChange | None = None
        current_hunk_lines: list[str] = []

        for line in raw_diff.split("\n"):
            if line.startswith("diff --git"):
                # Flush previous hunk
                if current_file and current_hunk_lines:
                    current_file.hunks.append("\n".join(current_hunk_lines))

                # Start new file
                match = re.search(r"b/(.+)$", line)
                path = match.group(1) if match else "unknown"
                current_file = FileChange(file_path=path)
                files.append(current_file)
                current_hunk_lines = []

            elif line.startswith("new file"):
                if current_file:
                    current_file.change_type = "added"

            elif line.startswith("deleted file"):
                if current_file:
                    current_file.change_type = "deleted"

            elif line.startswith("rename"):
                if current_file:
                    current_file.change_type = "renamed"

            elif line.startswith("@@") and current_file:
                if current_hunk_lines:
                    current_file.hunks.append("\n".join(current_hunk_lines))
                current_hunk_lines = [line]

            elif current_file:
                current_hunk_lines.append(line)
                if line.startswith("+") and not line.startswith("+++"):
                    current_file.added_lines.append(line[1:])
                    current_file.added_count += 1
                elif line.startswith("-") and not line.startswith("---"):
                    current_file.removed_lines.append(line[1:])
                    current_file.removed_count += 1

        # Flush last hunk
        if current_file and current_hunk_lines:
            current_file.hunks.append("\n".join(current_hunk_lines))

        return files

    def get_changed_file_paths(self, diff: Diff) -> list[Path]:
        """Get list of absolute file paths that were changed.

        Args:
            diff: Parsed Diff object.

        Returns:
            List of absolute paths to changed files.
        """
        return [self.repo_path / fc.file_path for fc in diff.files]
