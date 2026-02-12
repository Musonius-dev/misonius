# ADR-002: Why Tree-sitter for Code Parsing

## Status

Accepted

## Context

Musonius needs to parse codebases to build dependency graphs and extract symbols (functions, classes, methods, imports). The parsing solution must:

- Support multiple languages (Python first, JS/TS, Go, Rust later)
- Be fast enough for large codebases (10K+ files in <5s)
- Provide accurate AST parsing (not regex-based)
- Work locally with zero API calls
- Handle syntax errors gracefully (partial parses, not crashes)

## Decision

Use **tree-sitter** for code parsing, wrapped by `Indexer` in `musonius/context/indexer.py`.

## Rationale

### Advantages

1. **Multi-Language Support**
   - 40+ languages supported via community-maintained grammars
   - Consistent API across all languages
   - Adding a new language requires only installing its grammar package

2. **Performance**
   - Incremental parsing — only re-parse changed files
   - Fast enough for real-time use on large codebases
   - Low memory overhead

3. **Accuracy**
   - True AST parsing (not regex pattern matching)
   - Handles syntax errors gracefully — tree-sitter produces partial trees for malformed code
   - Provides precise symbol locations (start line, end line, byte offsets)

4. **Local-First**
   - No API calls required
   - Works fully offline
   - Zero cost per parse

5. **Python Bindings**
   - `py-tree-sitter` and `tree-sitter-python` packages available on PyPI
   - Modern API with pre-built language binaries (no manual grammar compilation)
   - Active maintenance and well-documented

### Alternatives Considered

#### Regex-Based Parsing
- No dependencies, simple to implement
- Inaccurate — false positives on strings/comments, false negatives on complex syntax
- Breaks on multiline definitions, decorators, nested structures
- No AST structure — cannot distinguish methods from functions

#### Language-Specific Parsers (Python `ast`, esprima, etc.)
- Accurate for their specific language
- Different API for each language — no unified symbol extraction
- More dependencies as languages are added
- Python `ast` module rejects files with syntax errors entirely

#### LLM-Based Parsing
- Can handle any language
- Expensive (token costs per file parsed)
- Slow (API latency per file)
- Not deterministic — same file can produce different results
- Violates local-first principle

## Consequences

### Positive

- Accurate symbol extraction (functions, classes, methods, imports, docstrings)
- Fast indexing (<5s for 10K files)
- Supports multiple languages with the same `Indexer` architecture
- Incremental updates via checksum-based change detection
- Graceful handling of syntax errors — partial results instead of crashes

### Negative

- Requires language-specific grammar packages (`tree-sitter-python`, etc.)
- Learning curve for tree-sitter node types and tree traversal
- Binary dependencies (platform-specific compiled grammars)

### Mitigation

- Start with Python only (v0.1) — single grammar dependency
- Add JS/TS, Go, Rust in v0.2+ via additional `tree-sitter-{lang}` packages
- Helper functions (`_find_child_by_type`, `_node_text`, `_get_signature`, `_get_docstring`) encapsulate tree-sitter traversal patterns
- Pre-built binaries available on PyPI — no manual compilation needed

## Implementation

### Indexer (`musonius/context/indexer.py`)

The `Indexer` class wraps tree-sitter with:

- **Python grammar loading** via `tree-sitter-python` package (modern API, no manual `.so` builds)
- **Recursive symbol extraction** — walks the AST to find functions, classes, methods (including decorated definitions)
- **Import extraction** — captures `import` and `from ... import` statements including relative imports
- **Import resolution** — maps import names to project files and builds dependency edges
- **Caching** — saves/loads the dependency graph as JSON with SHA-256 checksums for incremental reindexing
- **Directory filtering** — skips `__pycache__`, `.git`, `node_modules`, `.venv`, `.musonius`, and other irrelevant directories

```python
from musonius.context.indexer import Indexer
from pathlib import Path

# Index a project
indexer = Indexer(Path("/path/to/project"))
graph = indexer.index_codebase()

# Query results
print(f"Files: {graph.file_count}, Symbols: {graph.symbol_count}")

for file_info in graph.get_all_files():
    for symbol in file_info.symbols:
        print(f"  {symbol.type}: {symbol.qualified_name} (line {symbol.line_number})")

# Cache for incremental reindex
cache_dir = Path(".musonius/index")
indexer.save_cache(graph, cache_dir)

# Check what changed
changed = indexer.needs_reindex(cache_dir)
```

### Data Models (`musonius/context/models.py`)

- **`Symbol`** — extracted code symbol with name, type (`function`/`class`/`method`), file path, line numbers, signature, docstring, and parent class
- **`FileInfo`** — file metadata with path, SHA-256 checksum, symbols, and imports
- **`DependencyGraph`** — NetworkX-backed directed graph with file nodes, symbol nodes, and dependency edges. Supports JSON serialization roundtrip.

### Grammar Setup

The modern `tree-sitter-python` package provides pre-compiled binaries:

```python
import tree_sitter_python as tspython
from tree_sitter import Language, Parser

PY_LANGUAGE = Language(tspython.language())
parser = Parser(PY_LANGUAGE)
tree = parser.parse(source_code)
```

No manual grammar compilation or `.so` file management required.

### Symbol Extraction Strategy

The indexer extracts symbols by walking tree-sitter node types:

| Node Type | Extracted As | Notes |
|-----------|-------------|-------|
| `function_definition` | `function` or `method` | `method` when inside a class body |
| `class_definition` | `class` | Recurses into body for methods |
| `decorated_definition` | Unwraps to inner function/class | Handles `@decorator` syntax |
| `import_statement` | Import (dotted name) | `import foo.bar` |
| `import_from_statement` | Import (module name) | `from foo import bar` |

## References

- Tree-sitter: https://tree-sitter.github.io/tree-sitter/
- py-tree-sitter: https://github.com/tree-sitter/py-tree-sitter
- tree-sitter-python: https://github.com/tree-sitter/tree-sitter-python
- Implementation: `musonius/context/indexer.py`
- Data models: `musonius/context/models.py`
- Tests: `tests/test_indexer.py`
