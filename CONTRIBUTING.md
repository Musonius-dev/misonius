# Contributing to Musonius

Thanks for your interest in Musonius! This guide covers everything you need to get started.

## Quick Setup

```bash
git clone https://github.com/your-org/musonius.git
cd musonius
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
musonius doctor  # Verify your environment
```

## Development Workflow

1. Create a branch: `git checkout -b feat/your-feature`
2. Make your changes following the coding standards below
3. Run tests: `pytest tests/ -v`
4. Run linter: `ruff check . && ruff format --check .`
5. Commit with conventional commits: `git commit -m "feat: add X"`
6. Open a PR against `main`

## Coding Standards

**Type hints everywhere.** All function signatures must have complete type annotations. Use `from __future__ import annotations` in every file.

**Google-style docstrings** on all public functions:

```python
def estimate_cost(model: str, tokens: int) -> float:
    """Estimate the cost of a model call.

    Args:
        model: LiteLLM model identifier.
        tokens: Estimated token count.

    Returns:
        Estimated cost in USD.
    """
```

**Prefer pure functions over classes.** Use dataclasses or Pydantic models for data structures. No inheritance hierarchies unless truly needed.

**Explicit naming.** Functions with side effects should say so: `write_memory`, not `process`. No magic.

**Error handling.** Use specific exceptions, never bare `except:`. Wrap external calls (LLM APIs, file I/O, git) in try/except with meaningful messages.

**No print statements.** Use `rich.console` for user-facing output, `logging` for debug output.

**Import ordering:** stdlib, then third-party, then local — separated by blank lines. No wildcard imports.

## Project Structure

```
musonius/
├── cli/           # Typer CLI commands
├── context/       # Context generation and repo maps
├── config/        # Configuration loading and defaults
├── indexer/       # Tree-sitter codebase parsing (reserved)
├── intent/        # Task intent clarification
├── memory/        # SQLite-backed project memory
├── mcp/           # MCP server for IDE integration
├── orchestration/ # Model routing and cost tracking
├── planning/      # Plan generation and validation
├── parallel/      # Git worktree parallel execution (v1.1)
├── utils/         # Shared utilities
└── verification/  # Diff analysis and code review
```

## Testing

Every module gets a corresponding `tests/test_{module}.py`. Test the contract, not the implementation.

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_planning.py -v

# Run with coverage
pytest tests/ --cov=musonius --cov-report=term-missing
```

**Mock all LLM calls in tests** using `unittest.mock.MagicMock` with `content=json.dumps(...)` to simulate model responses. Never make real API calls in tests.

**Use fixtures** for SQLite databases and temp directories via pytest's `tmp_path`.

Target: 80%+ coverage on core modules.

## Adding a New CLI Command

1. Create `musonius/cli/your_command.py`
2. Define a function decorated with `@handle_errors`
3. Register it in `musonius/cli/main.py`:
   ```python
   from musonius.cli.your_command import your_command  # noqa: E402
   app.command(name="your-command")(your_command)
   ```
4. Add tests in `tests/test_your_command.py`

## Adding a New MCP Tool

1. Add the tool function in `musonius/mcp/server.py`
2. Decorate with `@mcp.tool()`
3. Return structured data (dict or Pydantic model)
4. Add tests

## Git Conventions

- Branch naming: `feat/short-description`, `fix/short-description`, `refactor/short-description`
- Commit messages: conventional commits (`feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`)
- Keep PRs focused — one feature or fix per PR

## Architecture Decisions

Major decisions are recorded in `.musonius/sot/` as versioned markdown files (e.g., `ARCH-001.md`, `API-002.md`). If your contribution involves an architectural decision (new dependency, API contract change, pattern choice), document it there.

## What NOT to Do

- Don't add LangChain, LlamaIndex, or any orchestration framework
- Don't add cloud dependencies or telemetry
- Don't require API keys for local-only operations (init, prep, memory, status, doctor)
- Don't use raw SQL strings — always use parameterized queries
- Don't catch and silence exceptions
- Don't add features outside the current build phase without discussion

## Getting Help

- Run `musonius doctor` to diagnose environment issues
- Check existing issues before filing new ones
- For questions, open a discussion thread

## License

MIT. By contributing, you agree your contributions are licensed under MIT.
