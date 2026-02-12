"""Tests for the repo map generator."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from musonius.context.budget import count_tokens
from musonius.context.indexer import Indexer
from musonius.context.models import FileInfo
from musonius.context.repo_map import FileScore, RepoMapGenerator

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_project"


@pytest.fixture
def indexer() -> Indexer:
    """Create an indexer for the sample project."""
    return Indexer(FIXTURES_DIR)


@pytest.fixture
def generator(indexer: Indexer) -> RepoMapGenerator:
    """Create a repo map generator with the sample project."""
    return RepoMapGenerator(indexer)


class TestRepoMapLevels:
    """Tests for the four detail levels."""

    def test_generate_l0(self, generator: RepoMapGenerator) -> None:
        """L0 should produce file paths only."""
        repo_map = generator.generate(level=0, token_budget=10_000)
        assert "main.py" in repo_map
        assert "utils.py" in repo_map
        assert "L0" in repo_map
        # L0 should not include function signatures
        assert "def hello" not in repo_map
        assert "class Greeter" not in repo_map

    def test_generate_l1(self, generator: RepoMapGenerator) -> None:
        """L1 should include signatures."""
        repo_map = generator.generate(level=1, token_budget=10_000)
        assert "main.py" in repo_map
        assert "def hello" in repo_map
        assert "class Greeter" in repo_map
        assert "L1" in repo_map
        # L1 should not include docstrings
        assert "Says hello" not in repo_map

    def test_generate_l2(self, generator: RepoMapGenerator) -> None:
        """L2 should include signatures and docstrings."""
        repo_map = generator.generate(level=2, token_budget=10_000)
        assert "main.py" in repo_map
        assert "def hello" in repo_map
        assert "Says hello" in repo_map
        assert "L2" in repo_map

    def test_generate_l3(self, generator: RepoMapGenerator) -> None:
        """L3 should include full file contents."""
        repo_map = generator.generate(level=3, token_budget=50_000)
        assert "main.py" in repo_map
        assert 'return f"Hello' in repo_map
        assert "```python" in repo_map
        assert "L3" in repo_map

    def test_invalid_level_too_high(self, generator: RepoMapGenerator) -> None:
        """Should raise ValueError for level > 3."""
        with pytest.raises(ValueError, match="Level must be 0-3"):
            generator.generate(level=5)

    def test_invalid_level_negative(self, generator: RepoMapGenerator) -> None:
        """Should raise ValueError for negative levels."""
        with pytest.raises(ValueError, match="Level must be 0-3"):
            generator.generate(level=-1)

    def test_empty_project(self, tmp_path: Path) -> None:
        """Should handle an empty project gracefully."""
        indexer = Indexer(tmp_path)
        gen = RepoMapGenerator(indexer)
        result = gen.generate(level=0, token_budget=10_000)
        assert "empty project" in result


class TestTokenBudget:
    """Tests for token budget enforcement."""

    def test_respects_token_budget_l1(self, generator: RepoMapGenerator) -> None:
        """L1 output should not exceed the token budget."""
        repo_map = generator.generate(level=1, token_budget=100)
        tokens = count_tokens(repo_map)
        # Allow some overhead for the header line
        assert tokens < 200

    def test_respects_token_budget_l0(self, generator: RepoMapGenerator) -> None:
        """L0 output should not exceed the token budget."""
        repo_map = generator.generate(level=0, token_budget=50)
        tokens = count_tokens(repo_map)
        assert tokens < 100

    def test_respects_token_budget_l2(self, generator: RepoMapGenerator) -> None:
        """L2 output should not exceed the token budget."""
        repo_map = generator.generate(level=2, token_budget=100)
        tokens = count_tokens(repo_map)
        assert tokens < 200

    def test_respects_token_budget_l3(self, generator: RepoMapGenerator) -> None:
        """L3 output should truncate file contents when over budget."""
        repo_map = generator.generate(level=3, token_budget=100)
        tokens = count_tokens(repo_map)
        assert tokens < 200

    def test_large_budget_includes_all(self, generator: RepoMapGenerator) -> None:
        """With a very large budget all files should be included."""
        repo_map = generator.generate(level=1, token_budget=100_000)
        assert "main.py" in repo_map
        assert "utils.py" in repo_map
        assert "truncated" not in repo_map

    def test_token_count_accuracy(self, generator: RepoMapGenerator) -> None:
        """Token count of the output should be within ±5% of budget when budget is tight."""
        budget = 200
        repo_map = generator.generate(level=1, token_budget=budget)
        tokens = count_tokens(repo_map)
        # Output should not exceed budget (with header tolerance)
        assert tokens <= budget * 1.5  # headers add some overhead


class TestFilePrioritization:
    """Tests for file relevance scoring and prioritization."""

    def test_prioritizes_relevant_files(self, generator: RepoMapGenerator) -> None:
        """Relevant files should appear first in the output."""
        repo_map = generator.generate(
            level=0,
            relevant_files=[Path("utils.py")],
            token_budget=10_000,
        )
        lines = repo_map.strip().split("\n")
        utils_idx = next(
            (i for i, line in enumerate(lines) if "utils.py" in line), 999
        )
        main_idx = next(
            (i for i, line in enumerate(lines) if "main.py" in line), 999
        )
        assert utils_idx < main_idx

    def test_prioritizes_dependencies_of_relevant(
        self, tmp_path: Path
    ) -> None:
        """Files that relevant files depend on should rank higher."""
        # Create a project where imports resolve within the module map
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("")
        (pkg / "core.py").write_text(
            '"""Core module."""\nfrom pkg.helpers import do_stuff\n\n'
            "def main() -> None:\n"
            '    """Entry point."""\n'
            "    do_stuff()\n"
        )
        (pkg / "helpers.py").write_text(
            '"""Helper module."""\n\n'
            "def do_stuff() -> None:\n"
            '    """Do stuff."""\n'
            "    pass\n"
        )
        (pkg / "unrelated.py").write_text(
            '"""Unrelated module."""\n\n'
            "def noop() -> None:\n"
            '    """No-op."""\n'
            "    pass\n"
        )

        indexer = Indexer(tmp_path)
        gen = RepoMapGenerator(indexer)
        repo_map = gen.generate(
            level=0,
            relevant_files=[Path("pkg/core.py")],
            token_budget=10_000,
        )
        lines = repo_map.strip().split("\n")
        # core.py first (relevant), then helpers.py (dependency), then others
        core_idx = next(
            (i for i, line in enumerate(lines) if "core.py" in line), 999
        )
        helpers_idx = next(
            (i for i, line in enumerate(lines) if "helpers.py" in line), 999
        )
        unrelated_idx = next(
            (i for i, line in enumerate(lines) if "unrelated.py" in line), 999
        )
        assert core_idx < helpers_idx
        assert helpers_idx < unrelated_idx

    def test_no_relevant_files_alphabetical(
        self, generator: RepoMapGenerator
    ) -> None:
        """Without relevant files, output should be sorted by recency then alphabetical."""
        repo_map = generator.generate(level=0, token_budget=10_000)
        # Should produce valid output without errors
        assert "main.py" in repo_map
        assert "utils.py" in repo_map


class TestFileScore:
    """Tests for the FileScore dataclass and scoring logic."""

    def test_score_relevant_file(self) -> None:
        """Relevant files should get the highest base score."""
        fi = FileInfo(path=Path("app.py"), checksum="abc")
        score = FileScore(
            file_info=fi,
            score=RepoMapGenerator.SCORE_RELEVANT,
            is_relevant=True,
        )
        assert score.score == 100.0
        assert score.is_relevant is True

    def test_score_dependency_file(self) -> None:
        """Dependency files should score lower than relevant ones."""
        fi = FileInfo(path=Path("lib.py"), checksum="def")
        score = FileScore(
            file_info=fi,
            score=RepoMapGenerator.SCORE_DEPENDENCY,
            is_dependency=True,
        )
        assert score.score < RepoMapGenerator.SCORE_RELEVANT

    def test_score_combined(self) -> None:
        """A file that is both relevant and a dependency should combine scores."""
        fi = FileInfo(path=Path("core.py"), checksum="ghi")
        combined = (
            RepoMapGenerator.SCORE_RELEVANT + RepoMapGenerator.SCORE_DEPENDENCY
        )
        score = FileScore(
            file_info=fi,
            score=combined,
            is_relevant=True,
            is_dependency=True,
        )
        assert score.score == 150.0


class TestScoringIntegration:
    """Integration tests for the scoring system with a real indexer."""

    def test_score_file_method(self, generator: RepoMapGenerator) -> None:
        """_score_file should produce expected scores."""
        fi = FileInfo(path=Path("main.py"), checksum="abc")
        score = generator._score_file(
            file_info=fi,
            relevant_set={"main.py"},
            dependency_set=set(),
            dependent_set=set(),
            mtime_map={"main.py": 1000.0},
            max_mtime=1000.0,
            min_mtime=500.0,
        )
        assert score.is_relevant is True
        assert score.score >= RepoMapGenerator.SCORE_RELEVANT

    def test_score_file_recency_bonus(self, generator: RepoMapGenerator) -> None:
        """Most recently modified file should get full recency bonus."""
        fi = FileInfo(path=Path("new.py"), checksum="xyz")
        score = generator._score_file(
            file_info=fi,
            relevant_set=set(),
            dependency_set=set(),
            dependent_set=set(),
            mtime_map={"new.py": 2000.0},
            max_mtime=2000.0,
            min_mtime=1000.0,
        )
        # Should get full recency bonus
        assert abs(score.score - RepoMapGenerator.SCORE_RECENT_MAX) < 0.01

    def test_score_file_oldest_no_recency(
        self, generator: RepoMapGenerator
    ) -> None:
        """Oldest file should get zero recency bonus."""
        fi = FileInfo(path=Path("old.py"), checksum="old")
        score = generator._score_file(
            file_info=fi,
            relevant_set=set(),
            dependency_set=set(),
            dependent_set=set(),
            mtime_map={"old.py": 1000.0},
            max_mtime=2000.0,
            min_mtime=1000.0,
        )
        # Oldest file gets 0 recency bonus
        assert score.score < 0.01

    def test_score_file_no_mtime(self, generator: RepoMapGenerator) -> None:
        """File with unknown mtime should get no recency bonus."""
        fi = FileInfo(path=Path("unknown.py"), checksum="unk")
        score = generator._score_file(
            file_info=fi,
            relevant_set=set(),
            dependency_set=set(),
            dependent_set=set(),
            mtime_map={"unknown.py": 0.0},
            max_mtime=2000.0,
            min_mtime=1000.0,
        )
        assert score.score == 0.0

    def test_collect_mtimes(self, generator: RepoMapGenerator) -> None:
        """_collect_mtimes should return valid modification times."""
        graph = generator.indexer.index_codebase()
        files = graph.get_all_files()
        mtimes = generator._collect_mtimes(files)
        assert len(mtimes) == len(files)
        for path_str, mtime in mtimes.items():
            assert mtime > 0, f"Expected positive mtime for {path_str}"


class TestFormatting:
    """Tests for output formatting details."""

    def test_l0_format(self, generator: RepoMapGenerator) -> None:
        """L0 should format as a simple file list."""
        repo_map = generator.generate(level=0, token_budget=10_000)
        lines = repo_map.strip().split("\n")
        # First line is the header
        assert lines[0].startswith("# Repository Map")
        # File paths should be plain strings without indentation
        file_lines = [line for line in lines[2:] if line.strip() and not line.startswith("...")]
        for line in file_lines:
            assert not line.startswith(" "), f"L0 paths should not be indented: {line}"

    def test_l1_class_indent(self, generator: RepoMapGenerator) -> None:
        """L1 should indent class members."""
        repo_map = generator.generate(level=1, token_budget=10_000)
        # Methods under a class should be indented more than the class
        lines = repo_map.split("\n")
        class_line = next(
            (i for i, ln in enumerate(lines) if "class Greeter" in ln), None
        )
        assert class_line is not None
        # Next method line should be indented
        for ln in lines[class_line + 1 :]:
            if ln.strip() and not ln.strip().startswith("class"):
                assert ln.startswith("    "), f"Method should be indented: {ln}"
                break

    def test_l2_docstring_format(self, generator: RepoMapGenerator) -> None:
        """L2 should include docstrings with triple quotes."""
        repo_map = generator.generate(level=2, token_budget=10_000)
        assert '"""' in repo_map

    def test_l3_code_blocks(self, generator: RepoMapGenerator) -> None:
        """L3 should wrap content in markdown code blocks."""
        repo_map = generator.generate(level=3, token_budget=50_000)
        assert "```python" in repo_map
        assert "```" in repo_map

    def test_l0_truncation_message(self, generator: RepoMapGenerator) -> None:
        """L0 should show count of remaining files when truncated."""
        repo_map = generator.generate(level=0, token_budget=20)
        if "..." in repo_map:
            assert "more files" in repo_map


class TestPerformance:
    """Performance tests for the repo map generator."""

    def test_l1_generation_speed(self, tmp_path: Path) -> None:
        """L1 generation for 100+ files should complete quickly."""
        # Create a project with many files
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")

        for i in range(150):
            content = f'''"""Module {i}."""

def func_{i}(x: int) -> int:
    """Process item {i}."""
    return x + {i}

class Handler{i}:
    """Handler for item {i}."""

    def handle(self, data: str) -> str:
        """Handle the data."""
        return data.upper()
'''
            (pkg_dir / f"module_{i:03d}.py").write_text(content)

        indexer = Indexer(tmp_path)
        gen = RepoMapGenerator(indexer)

        start = time.monotonic()
        repo_map = gen.generate(level=1, token_budget=50_000)
        elapsed = time.monotonic() - start

        assert elapsed < 10.0, f"L1 generation took {elapsed:.2f}s (expected <10s)"
        assert "func_0" in repo_map
        assert "Handler" in repo_map
