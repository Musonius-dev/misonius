# Musonius Architecture

## Five-Layer Pipeline

Musonius is organized as five composable layers, each independently testable and replaceable.
The fundamental design principle: **never send a token you don't need to.**

```
┌──────────────────────────────────────────────────────────────────┐
│ L1: INTENT ENGINE                                                │
│ Captures user intent → asks clarifying questions → structured spec│
│ Innovation: Conversation-aware refinement with decision tree      │
├──────────────────────────────────────────────────────────────────┤
│ L2: CONTEXT ENGINE                                               │
│ Indexes codebase → gathers relevant context → manages memory     │
│ Innovation: AST graph + token-budgeted retrieval ($0 indexing)   │
├──────────────────────────────────────────────────────────────────┤
│ L3: PLANNING ENGINE                                              │
│ Decomposes work → generates phased file-level plans              │
│ Innovation: Hierarchical planning with progressive context       │
├──────────────────────────────────────────────────────────────────┤
│ L4: ORCHESTRATION ENGINE                                         │
│ Routes to models/agents → manages handoffs → format adaptation   │
│ Innovation: BYOK multi-model router + universal agent plugins    │
├──────────────────────────────────────────────────────────────────┤
│ L5: VERIFICATION ENGINE                                          │
│ Reviews changes vs spec → runs checks → generates fix suggestions│
│ Innovation: Severity-categorized verification + linter-in-loop   │
└──────────────────────────────────────────────────────────────────┘
```

## Data Flow

1. User describes intent in natural language
2. **Intent Engine** captures requirements, asks 3-5 targeted clarifying questions (via scout model, $0)
3. **Context Engine** fans out lightweight scouts to gather relevant files, dependencies, and docs. Context is token-budgeted.
4. **Planning Engine** receives spec + budgeted context, decomposes into ordered phases with file-level instructions and acceptance criteria
5. **Orchestration Engine** formats context for the target agent and hands off (CLI, file, clipboard)
6. **Verification Engine** reviews diffs against plan using a separate model, runs linting/tests, categorizes findings by severity (Critical/Major/Minor/Outdated)
7. **Project Memory** updates with decisions, patterns, and verification results for future sessions

## Directory Structure

```
project-root/
├── .musonius/
│   ├── config.yaml              # Project-level configuration
│   ├── index/
│   │   ├── repo-map.json        # Pre-computed AST-based file graph
│   │   ├── symbols.db           # Tree-sitter symbol index
│   │   └── checksums.json       # File change detection
│   ├── memory/
│   │   ├── decisions.db         # SQLite: architectural decisions
│   │   ├── conventions.json     # Learned coding conventions
│   │   └── failures.json        # Past approaches that failed
│   ├── epics/
│   │   ├── epic-001/
│   │   │   ├── spec.md          # Epic specification (PRD/Tech Doc)
│   │   │   ├── phases/
│   │   │   │   ├── phase-01.md  # Phase 1 plan
│   │   │   │   ├── phase-02.md  # Phase 2 plan
│   │   │   │   └── ...
│   │   │   └── verification/
│   │   │       ├── phase-01.json # Verification results
│   │   │       └── ...
│   │   └── ...
│   ├── sot/                     # Source of Truth documents
│   │   ├── architecture.md      # System architecture decisions
│   │   ├── conventions.md       # Coding standards
│   │   └── dependencies.md      # Key dependency decisions
│   ├── agents/                  # Custom agent definitions
│   │   ├── claude-dangerous.yaml
│   │   └── roo-code.yaml
│   └── templates/               # Handoff templates
│       ├── claude-handoff.md
│       ├── verify-prompt.md
│       └── generic-handoff.md
│
~/.musonius/                     # User-global configuration
├── config.yaml                  # Default model routing, API keys
├── agents/                      # User-global custom agents
│   └── my-agent.yaml
└── templates/                   # User-global templates
    └── default-handoff.md
```

## Repo Map Detail Levels

The Context Engine serves context at multiple granularity levels, controlled by token budget:

| Level | Name | Content | Tokens (1K files) | Use Case |
|-------|------|---------|-------------------|----------|
| L0 | Skeleton | File paths only | ~2K | Agent with tiny context (Cursor rules) |
| L1 | Signatures | Paths + function/class signatures | ~8K | Planning, most handoffs |
| L2 | Documented | Signatures + docstrings + key logic | ~20K | Detailed implementation handoff |
| L3 | Full | Complete file contents (relevant files) | Variable | Deep debugging, review |

The budget allocation algorithm:
1. Start with agent's `max_context_tokens`
2. Reserve 30% for task description + plan + memory
3. Allocate remaining 70% to repo context
4. Select detail level that fits within budget
5. Prioritize files mentioned in the plan, then direct dependencies, then broader context

## Token Optimization Strategies

### 1. AST-Based Local Indexing ($0)
Tree-sitter parses the codebase locally, building a NetworkX graph of definitions and references. No LLM tokens spent on codebase exploration.

### 2. Scout/Thinker Model Separation
- **Scout tasks** (file discovery, summarization, clarifying questions): Gemini Flash (free) or Ollama (local)
- **Thinker tasks** (planning, complex reasoning): Claude Sonnet/Opus or GPT-4
- 60-70% of operations are scout-tier, costing $0

### 3. Progressive Context Loading
Plans load context per-phase, not all-at-once. Phase 3 only sees files relevant to Phase 3, not the entire codebase.

### 4. Memory-Based Shortcutting
If the project memory already knows which files handle authentication, the scout doesn't need to search for them again.

### 5. Token Budgeting
Every LLM call has an explicit token budget. The system tracks actual usage and reports cost per task.

### 6. Prompt Caching Optimization
Prompts are ordered with stable prefixes (system prompt, repo map) first to maximize Anthropic/OpenAI cache hits.

### 7. Compressor Distillation (v2)
Small local model handles context compression, eliminating API costs for summarization entirely.
