# Musonius System Design

## Overview

Musonius is a local-first, CLI-based AI coding orchestrator that provides structured planning, persistent memory, and optimized context generation for AI coding agents. It sits between developer intent and AI agents, reducing token waste and improving implementation quality.

### Core Value Proposition

**Problem**: AI coding agents are powerful but drift—they hallucinate APIs, misread intent, and lose context in large codebases, burning tokens on exploration.

**Solution**: Musonius pre-computes codebase context locally, maintains persistent project memory, and generates optimized handoff documents so agents go straight to surgical execution.

### Design Principles

1. **Local-first, always** - Everything runs on the user's machine, no cloud dependency
2. **Agent-agnostic output** - Works with any AI coding tool via format adapters
3. **Token efficiency is the product** - Every design decision optimizes for fewer tokens
4. **Memory compounds** - Knowledge persists and grows across all sessions
5. **Free tier first** - Route 60-70% of operations through free/cheap models
6. **Specs are durable artifacts** - Everything in `.musonius/` is git-versioned

## System Architecture

### Five-Layer Pipeline

```
User Intent
    │
    ▼
┌──────────────────┐
│ L1: Intent Engine │  ← Captures intent, asks clarifying questions
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ L2: Context Engine│  ← Tree-sitter index, repo map, token budgeting
└────────┬─────────┘
         │               ◄── Project Memory (decisions, conventions, failures)
         ▼
┌──────────────────┐
│ L3: Planning      │  ← Decomposes work into phased file-level plans
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ L4: Orchestration │  ← Model routing, agent plugins, handoff generation
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ L5: Verification  │  ← Diff analysis, severity classification, memory recording
└──────────────────┘
```

### Layer Responsibilities

| Layer | Purpose | Key Innovation |
|-------|---------|----------------|
| **L1: Intent Engine** | Captures user intent, asks clarifying questions | Conversation-aware refinement with decision tree |
| **L2: Context Engine** | Indexes codebase, gathers relevant context, manages memory | AST graph + token-budgeted retrieval ($0 indexing) |
| **L3: Planning Engine** | Decomposes work into phased file-level plans | Hierarchical planning with progressive context |
| **L4: Orchestration Engine** | Routes to models/agents, manages handoffs, format adaptation | BYOK multi-model router + universal agent plugins |
| **L5: Verification Engine** | Reviews changes vs spec, runs checks, generates fix suggestions | Severity-categorized verification + linter-in-loop |

## Component Architecture

### Package Structure

```
musonius/
├── cli/                    # CLI commands (Typer)
│   ├── main.py            # Entry point
│   ├── init.py            # musonius init
│   ├── plan.py            # musonius plan
│   ├── prep.py            # musonius prep
│   ├── verify.py          # musonius verify
│   ├── review.py          # musonius review
│   ├── rollback.py        # musonius rollback
│   ├── memory.py          # musonius memory
│   ├── agents.py          # musonius agents
│   ├── status.py          # musonius status
│   └── utils.py           # Shared CLI utilities
├── intent/                # L1: Intent capture
│   └── engine.py
├── context/               # L2: Context assembly
│   ├── engine.py          # Context assembly engine
│   ├── indexer.py         # Tree-sitter AST indexer
│   ├── models.py          # Symbol, FileInfo, DependencyGraph
│   ├── repo_map.py        # Multi-level repo map
│   ├── budget.py          # Token budgeting
│   └── agents/            # Agent plugin system
│       ├── base.py        # AgentPlugin abstract base
│       ├── registry.py    # Plugin discovery
│       ├── claude.py      # Claude Code XML-structured format
│       ├── gemini.py      # Gemini natural language format
│       └── generic.py     # Generic markdown fallback
├── planning/              # L3: Plan generation
│   ├── engine.py          # Planning engine
│   ├── schemas.py         # Pydantic models (Plan, Phase, FileChange)
│   └── prompts.py         # Prompt templates
├── orchestration/         # L4: Model routing + handoff
│   ├── engine.py          # Orchestration coordinator
│   ├── router.py          # LiteLLM model router
│   └── usage.py           # Token usage tracking
├── verification/          # L5: Verification pipeline
│   └── engine.py          # Diff analysis + severity classification
├── memory/                # Persistent knowledge
│   └── store.py           # SQLite backend
├── config/                # Configuration management
│   ├── defaults.py        # Default values
│   └── loader.py          # YAML config loading
└── mcp/                   # MCP server
    └── server.py          # FastMCP tools for IDE integration
```

### User Project Structure

```
.musonius/
├── config.yaml            # Project configuration
├── index/
│   ├── repo-map.json     # Pre-computed AST graph
│   └── checksums.json    # File change detection
├── memory/
│   └── decisions.db      # SQLite: decisions, conventions, failures
├── epics/
│   └── epic-{id}/
│       ├── spec.md       # Epic specification
│       └── phases/
│           └── phase-{n}.md
├── sot/                  # Source of Truth documents
└── templates/            # Handoff templates
```

## Data Models

### Plan Schema (Pydantic)

```python
class FileChange(BaseModel):
    path: str
    action: str  # create, modify, delete
    description: str
    key_changes: list[str]

class Phase(BaseModel):
    id: str
    title: str
    description: str
    files: list[FileChange]
    dependencies: list[str]
    acceptance_criteria: list[str]
    test_strategy: str
    estimated_tokens: int

class Plan(BaseModel):
    epic_id: str
    task_description: str
    phases: list[Phase]
    total_estimated_tokens: int
    created_at: datetime
```

### Memory Schema (SQLite)

```sql
CREATE TABLE decisions (
    id INTEGER PRIMARY KEY,
    epic_id TEXT,
    category TEXT,
    summary TEXT NOT NULL,
    rationale TEXT,
    files_affected TEXT,
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMP
);

CREATE TABLE failures (
    id INTEGER PRIMARY KEY,
    epic_id TEXT,
    approach TEXT NOT NULL,
    failure_reason TEXT NOT NULL,
    alternative TEXT,
    files_affected TEXT,
    created_at TIMESTAMP
);

CREATE TABLE conventions (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,
    rule TEXT NOT NULL,
    source TEXT,
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMP
);
```

### Agent Capabilities

```python
@dataclass
class AgentCapabilities:
    name: str
    slug: str
    file_extension: str
    supports_xml: bool
    supports_mermaid: bool
    max_context_tokens: int
    handoff_method: str      # "file" | "stdin" | "clipboard"
    cli_command: str | None
```

## Key Workflows

### Initialize Project

```
musonius init
  → Parse codebase with tree-sitter
  → Build dependency graph (NetworkX)
  → Detect conventions from code
  → Create .musonius/ directory structure
  → Save index cache (repo-map.json + checksums.json)
  → Initialize SQLite memory store
```

### Plan Task

```
musonius plan "task description"
  → Ask clarifying questions
  → Load index cache and generate L1 repo map
  → Query memory for past decisions
  → Send context + intent to planner LLM
  → Parse response into Plan (phases + files + criteria)
  → Save plan to .musonius/epics/{id}/phases/
```

### Generate Handoff

```
musonius prep --agent claude
  → Load latest plan from .musonius/epics/
  → Load memory entries (decisions + conventions)
  → Generate token-budgeted repo map from index
  → Format everything via agent plugin (Claude XML / Gemini NL / Generic MD)
  → Write handoff file (HANDOFF.md)
```

### Verify Changes

```
musonius verify
  → Capture git diff
  → Parse diff into structured file changes
  → Check plan coverage (missing/extra files)
  → Run heuristic checks (security, style, completeness)
  → Optional: LLM-based cross-model adversarial review
  → Classify findings by severity
  → Record critical/major findings in memory
```

## Token Optimization Strategies

1. **AST-Based Local Indexing ($0)** — Tree-sitter parses locally, no LLM tokens for exploration
2. **Scout/Thinker Model Separation** — 60-70% of calls through free/cheap models (Gemini Flash)
3. **Progressive Context Loading** — 4 detail levels (L0 paths → L3 full), load per-phase not all-at-once
4. **Memory-Based Shortcutting** — Known locations cached, conventions baked in, failed approaches excluded
5. **Prompt Caching Optimization** — Stable prefixes first, maximizes cache hits (30-50% cost reduction)
6. **Diff-Based Verification** — Only changed lines reviewed (60-80% reduction vs full-file)

## Configuration

```yaml
# .musonius/config.yaml
models:
  scout: "gemini/gemini-2.0-flash"
  planner: "anthropic/claude-sonnet-4-20250514"
  verifier: "gemini/gemini-2.0-flash"
  summarizer: "ollama/llama3.2"

default_agent: "claude"

autonomy:
  level: 2
  max_retries: 3
  stop_on: "critical"

budgets:
  plan: 8000
  verify: 6000
  prep: null  # Auto-detect from agent

project:
  language: "python"
  test_command: "pytest"
  lint_command: "ruff check ."
```

## MCP Server Tools

| Tool | Purpose |
|------|---------|
| `musonius_get_plan` | Returns current phase plan with optimized context |
| `musonius_get_context` | Returns token-budgeted context for a file/function |
| `musonius_verify` | Triggers verification of current changes |
| `musonius_memory_query` | Searches project memory for decisions and patterns |
| `musonius_record_decision` | Adds a new decision to project memory |

## Agent Plugin Interface

```python
class AgentPlugin(ABC):
    @abstractmethod
    def capabilities(self) -> AgentCapabilities: ...

    @abstractmethod
    def format_context(
        self,
        task: str,
        plan: dict,
        repo_map: str,
        memory: list[dict],
        token_budget: int,
    ) -> str: ...
```

Built-in plugins: Claude Code (XML), Gemini CLI (natural language), Generic (plain markdown).

## Success Metrics

- **Token reduction**: 60-70% vs raw agent usage
- **Context accuracy**: 95%+ relevant files included
- **Memory hit rate**: 40%+ queries answered from cache
- **Indexing speed**: <5s for 10K file codebase
- **Time to first plan**: <30s for typical task
- **Verification accuracy**: 90%+ true positives
