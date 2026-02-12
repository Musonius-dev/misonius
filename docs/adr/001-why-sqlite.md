# ADR-001: Why SQLite for Memory Storage

## Status

Accepted

## Context

Musonius needs persistent storage for project memory (decisions, conventions, failures). The storage solution must be:

- **Local-first** — no cloud dependency
- **Zero-config** — works out of the box after `musonius init`
- **Portable** — works across Windows, macOS, and Linux
- **Git-friendly** — schema can be versioned
- **Fast enough** — sub-100ms for typical queries on <10K records

## Decision

Use SQLite via Python's `sqlite3` stdlib module as the memory storage backend. The database file lives at `.musonius/memory/decisions.db`.

## Rationale

### Advantages

1. **Zero Configuration**
   - No server setup required
   - No connection strings or credentials
   - Works immediately after `musonius init`

2. **Local-First**
   - Database file lives in `.musonius/memory/`
   - No network dependency
   - Works fully offline

3. **Portable**
   - Single file database
   - Cross-platform (Windows, macOS, Linux)
   - Can be copied/backed up by copying the `.musonius/` directory

4. **Git-Friendly**
   - Text-based schema definition in Python source
   - Deterministic file format
   - Database can be excluded from git while schema is versioned

5. **Performance**
   - Fast for read-heavy workloads (project memory is mostly reads)
   - Sufficient for <10K decisions per project
   - Built-in full-text search (FTS5) available for future use

6. **Python Integration**
   - `sqlite3` is in the standard library — no additional dependencies
   - `sqlite3.Row` factory provides dict-like access
   - Parameterized queries prevent SQL injection by design

### Alternatives Considered

#### PostgreSQL

- Requires server setup and connection management
- Not portable — depends on running service
- Overkill for local-first, single-user use case
- Better suited for future team/shared memory (v0.2+)

#### JSON Files

- Simple and naturally git-friendly
- No indexing — slow queries on large datasets
- No transactions — corruption risk on concurrent writes
- No full-text search capability

#### ChromaDB (Vector Database)

- Enables semantic search over decisions
- Requires additional dependencies (chromadb, embedding models)
- Overkill for v0.1 keyword-based search
- Consider for v0.2 as a hybrid approach (SQLite + ChromaDB)

## Implementation

The `MemoryStore` class in `musonius/memory/store.py` manages three tables:

| Table | Purpose | Key Fields |
|-------|---------|------------|
| `decisions` | Architectural decisions with rationale | `summary`, `rationale`, `category`, `confidence`, `files_affected` |
| `conventions` | Code patterns and standards | `pattern`, `rule`, `source`, `confidence` |
| `failures` | Failed approaches (anti-pattern library) | `approach`, `failure_reason`, `alternative` |

```python
# musonius/memory/store.py
from pathlib import Path
import sqlite3

class MemoryStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create the database and tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_connection()
        conn.executescript(SCHEMA_SQL)
        conn.commit()
```

Key design choices:
- **Lazy connection** — connection is created on first use, not at init
- **Parameterized queries** — all queries use `?` placeholders (never raw SQL interpolation)
- **Row factory** — `sqlite3.Row` provides dict-like access to results
- **Explicit close** — `close()` method for deterministic resource cleanup

## Consequences

### Positive

- Developers can start using Musonius immediately with zero setup
- Memory persists across sessions and tool invocations
- Fast queries for typical project workloads (<10K records)
- Entire project state is backed up by copying `.musonius/`

### Negative

- Not ideal for team collaboration (file locking issues with concurrent access)
- Limited to single-machine use (no built-in sync)
- Keyword search via `LIKE` is less powerful than dedicated search engines

### Mitigation

- For team use (v0.2+): add PostgreSQL backend option behind the same `MemoryStore` interface
- For semantic search (v0.2+): add ChromaDB integration as a supplementary index
- Document backup/restore procedures in user documentation

## References

- SQLite documentation: https://www.sqlite.org/docs.html
- Python sqlite3 module: https://docs.python.org/3/library/sqlite3.html
- Implementation: `musonius/memory/store.py`
- Tests: `tests/test_memory.py`
