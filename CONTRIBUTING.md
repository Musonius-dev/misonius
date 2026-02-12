# Contributing to Musonius

## Development Setup

```bash
# Clone the repository
git clone https://github.com/your-org/musonius.git
cd musonius

# Install with dev dependencies (requires uv)
uv pip install -e ".[dev]"

# Verify installation
musonius --help
```

## Development Workflow

1. Create a branch: `feat/short-description`, `fix/short-description`, or `refactor/short-description`
2. Make changes following the coding standards below
3. Run checks before committing:

```bash
# Linting
ruff check .

# Type checking
mypy musonius/

# Tests
pytest
```

4. Commit with conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`

## Coding Standards

- **Type hints everywhere.** All function signatures must have complete type annotations. Use `from __future__ import annotations` in every file.
- **Docstrings on all public functions.** Google-style docstrings.
- **No classes where functions suffice.** Prefer pure functions. Use dataclasses or Pydantic models for data.
- **Explicit over implicit.** No magic. Name side-effecting functions clearly.
- **Error handling:** Use specific exceptions, never bare `except`.
- **No print statements.** Use `rich.console` for user-facing output, `logging` for debug.
- **Imports:** stdlib, third-party, local — separated by blank lines. No wildcard imports.

## Testing

- Every module gets a corresponding `tests/test_{module}.py`
- Test the contract, not the implementation
- Use fixtures for SQLite and temp directories
- Mock all LLM calls in tests

## File Naming

- Python files: `snake_case.py`
- Config files: `snake_case.yaml` or `snake_case.json`
- Test files: `test_{module_name}.py`
