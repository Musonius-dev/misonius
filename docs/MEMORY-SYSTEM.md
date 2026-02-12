# Persistent Memory System

## Overview

Musonius's most significant innovation over Traycer: every session starts cold in Traycer, but Musonius maintains a persistent, queryable knowledge graph that makes session #50 smarter than session #1.

## What Gets Stored

### Architecture Decisions
"We chose Redis for rate limiting because X. Decision made in Phase 2 of epic-047."

### Code Conventions
"This project uses barrel exports, Zod for validation, and snake_case for DB columns."

### Past Failures
"Approach X was tried in epic-031 and caused regression Y. Avoid."

### Dependency Map
Live graph of which services/modules depend on each other, updated after each task.

### Verification Patterns
Common issues the verification engine catches repeatedly, used to pre-filter plans.

## How Memory Reduces Tokens

1. **No redundant scouting** — If memory knows which files handle rate limiting, scouts don't search again.
2. **Convention-aware planning** — Plans are generated with conventions baked in, reducing verification failures.
3. **Failure avoidance** — Known-bad approaches excluded from plans before generation, saving entire plan→verify cycles.

## Storage Architecture

| Store | Technology | Contents |
|-------|-----------|----------|
| Decisions | SQLite | Architectural decisions with rationale, task provenance |
| Conventions | JSON | Coding patterns, naming conventions, framework preferences |
| Failures | JSON | Failed approaches with context and alternative that worked |
| Dependency Graph | NetworkX (serialized) | File/module relationships, updated incrementally |
| Semantic Index | ChromaDB (optional, v0.2) | Vector search over decisions and code patterns |

## SQLite Schema (Decisions)

```sql
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY,
    epic_id TEXT,
    phase_id TEXT,
    category TEXT,          -- "architecture", "dependency", "pattern", "convention"
    summary TEXT NOT NULL,
    rationale TEXT,
    files_affected TEXT,    -- JSON array of file paths
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confidence REAL DEFAULT 1.0  -- 0-1, decays over time or on contradicting evidence
);

CREATE TABLE failures (
    id INTEGER PRIMARY KEY,
    epic_id TEXT,
    phase_id TEXT,
    approach TEXT NOT NULL,
    failure_reason TEXT NOT NULL,
    alternative TEXT,       -- What worked instead
    files_affected TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE conventions (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,   -- "naming", "imports", "testing", "error_handling"
    rule TEXT NOT NULL,
    source TEXT,             -- "detected", "user", "agents.md", "verification"
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Memory Lifecycle

1. **Seeding** — `musonius init` detects conventions from AGENTS.md, CLAUDE.md, .cursorrules, and codebase analysis
2. **Accumulation** — After each verification, decisions and patterns are extracted and stored
3. **Retrieval** — During planning and context generation, relevant memories are queried and included
4. **Decay** — Old decisions lose confidence over time; contradicted decisions are flagged
5. **Pruning** — `musonius memory` commands let users manage, correct, or remove memories

## Integration with Context Engine

When generating context for an agent:

```
Token budget: 50,000

Allocation:
  Task description:     ~500 tokens
  Plan:                 ~3,000 tokens
  Memory (decisions):   ~1,000 tokens   ← Retrieved from SQLite
  Memory (conventions): ~500 tokens     ← Retrieved from JSON
  Repo map (L1):        ~8,000 tokens   ← From pre-computed index
  File contents (L2):   ~37,000 tokens  ← Budget remainder
```

Memory is always included because it's high-value, low-token context that prevents drift.
