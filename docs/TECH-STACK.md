# Tech Stack & Implementation Roadmap

## Core Tech Stack

| Component | Technology | Why |
|-----------|-----------|-----|
| Language | Python 3.12+ | LLM ecosystem, tree-sitter bindings, rapid dev |
| Package manager | uv | Fast, modern, replaces pip/poetry |
| CLI framework | Typer | Type-safe CLI with auto-generated help |
| LLM routing | LiteLLM | 100+ providers, BYOK, unified interface |
| AST parsing | py-tree-sitter | Local codebase indexing, 40+ languages |
| Graph | NetworkX | Dependency graph, serializable |
| Storage | SQLite | Project memory, zero-config, portable |
| Schemas | Pydantic | Structured plan/spec validation |
| Vector search | ChromaDB (optional) | Semantic search over memory (v0.2) |
| MCP | FastMCP | Expose as MCP server for IDE integration |
| Testing | pytest | Standard Python testing |
| Linting | Ruff | Fast Python linting |

## Package Structure

```
musonius/
├── __init__.py
├── __main__.py              # CLI entry point
├── cli/
│   ├── __init__.py
│   ├── main.py              # Typer app, top-level commands
│   ├── plan.py              # musonius plan
│   ├── prep.py              # musonius prep
│   ├── verify.py            # musonius verify
│   ├── review.py            # musonius review
│   ├── epic.py              # musonius epic (v0.2)
│   ├── agents.py            # musonius agents
│   ├── memory.py            # musonius memory
│   └── init.py              # musonius init
├── intent/
│   ├── __init__.py
│   ├── engine.py            # L1: Intent capture + clarification
│   └── clarifier.py         # Scout agent question generation
├── context/
│   ├── __init__.py
│   ├── engine.py            # L2: Context assembly + budgeting
│   ├── indexer.py           # Tree-sitter AST indexer
│   ├── repo_map.py          # Multi-level repo map generator
│   ├── budget.py            # Token budget allocation
│   └── agents/
│       ├── __init__.py
│       ├── base.py          # AgentPlugin ABC + AgentCapabilities
│       ├── registry.py      # Plugin discovery + registration
│       ├── claude.py        # Claude Code formatter
│       ├── gemini.py        # Gemini CLI formatter
│       ├── grok.py          # Grok formatter
│       ├── cursor.py        # Cursor rules formatter
│       ├── copilot.py       # GitHub Copilot formatter
│       ├── aider.py         # Aider formatter
│       ├── generic.py       # Universal markdown fallback
│       └── custom.py        # YAML-defined custom agents
├── planning/
│   ├── __init__.py
│   ├── engine.py            # L3: Plan generation + decomposition
│   ├── phaser.py            # Multi-phase decomposition logic
│   └── schemas.py           # Pydantic models for plans
├── orchestration/
│   ├── __init__.py
│   ├── engine.py            # L4: Model routing + agent handoff
│   ├── router.py            # LiteLLM model router wrapper
│   └── handoff.py           # Context file generation + delivery
├── verification/
│   ├── __init__.py
│   ├── engine.py            # L5: Verification pipeline
│   ├── diff_analyzer.py     # Diff vs plan comparison
│   ├── severity.py          # Critical/Major/Minor/Outdated
│   └── linter.py            # Integrated linter-in-the-loop
├── memory/
│   ├── __init__.py
│   ├── store.py             # SQLite memory backend
│   ├── conventions.py       # Convention detection + storage
│   ├── decisions.py         # Architectural decision tracking
│   └── failures.py          # Past failure pattern tracking
├── config/
│   ├── __init__.py
│   ├── loader.py            # Config file loading + merging
│   └── defaults.py          # Default configuration values
└── mcp/
    ├── __init__.py
    └── server.py            # FastMCP server for IDE integration
```

---

## Implementation Roadmap

### Phase 1: Core CLI + Planning (Weeks 1-3)
**Goal:** Working CLI that generates plans better than Traycer with zero credit limits.

**Deliverables:**
- `musonius init` — project setup, tree-sitter indexing, convention detection
- `musonius plan` — intent capture + single-phase plan generation
- Basic LiteLLM routing with BYOK (scout: Gemini Flash, planner: Claude/GPT)
- Tree-sitter AST indexer → NetworkX graph → L0-L1 repo maps
- Token counting on every LLM call
- CLI via Typer

**Key files:** `cli/main.py`, `cli/init.py`, `cli/plan.py`, `context/indexer.py`, `context/repo_map.py`, `planning/engine.py`, `orchestration/router.py`

### Phase 2: Verification + Memory (Weeks 4-6)
**Goal:** Full plan→verify loop with persistent memory.

**Deliverables:**
- `musonius verify` — severity-categorized verification
- `musonius memory` — view/manage project knowledge
- SQLite memory backend (decisions, conventions, failures)
- Token budget system with cost reporting
- Intent clarification step (scout asks 3-5 questions)

**Key files:** `verification/engine.py`, `verification/severity.py`, `memory/store.py`, `intent/clarifier.py`, `context/budget.py`

### Phase 3: Agent Handoff + Automation (Weeks 7-10)
**Goal:** Universal agent support and configurable automation.

**Deliverables:**
- `musonius prep` — format context for any agent
- Agent plugin system (built-in: Claude, Gemini, Grok, Cursor, Generic)
- Custom YAML agent definitions
- Handoff templates
- `musonius run` with autonomy levels 0-3
- `musonius review` standalone code review
- AGENTS.md auto-detection during init

**Key files:** `context/agents/`, `cli/prep.py`, `cli/agents.py`, `orchestration/handoff.py`

### Phase 4: Advanced Features (Weeks 11-14)
**Goal:** Epic mode, parallel execution, MCP server.

**Deliverables:**
- `musonius epic` — full spec → ticket → phase workflow
- Multi-phase planning with context carryover
- MCP server for IDE integration
- Mermaid diagram generation from dependency graph
- Autonomy levels 4-5 (YOLO modes)
- Prompt caching optimization
- Per-task cost analytics

**Key files:** `cli/epic.py`, `mcp/server.py`, `planning/phaser.py`

### Phase 5: Scale + Community (Weeks 15+)
**Goal:** Team features, community plugin ecosystem.

**Deliverables:**
- GitHub issue integration (`--from-issue`)
- Git worktree parallel phase execution
- Community plugin entry points (`pip install musonius-agent-*`)
- Team shared memory
- Web dashboard for analytics
- Compressor distillation (local model for summarization)

---

## Configuration Reference

```yaml
# .musonius/config.yaml

# Model routing (BYOK)
models:
  scout: "gemini/gemini-2.0-flash"
  planner: "anthropic/claude-sonnet-4-20250514"
  verifier: "gemini/gemini-2.0-flash"
  summarizer: "ollama/llama3.2"

# Default agent for handoff
default_agent: "claude"

# Automation level (0-5)
autonomy:
  level: 2
  max_retries: 3
  stop_on: "critical"  # critical | major | minor | never

# Token budgets
budgets:
  plan: 8000           # Max tokens for plan generation input
  verify: 6000         # Max tokens for verification input
  prep: null           # Auto-detect from agent's context window

# Project settings
project:
  language: "python"
  test_command: "pytest"
  lint_command: "ruff check ."
  build_command: null
```
