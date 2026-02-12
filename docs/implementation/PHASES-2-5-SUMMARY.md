# Implementation Roadmap — Phases 2-5

> This document provides a high-level overview of the remaining implementation phases after Phase 1 (Core CLI + Planning). Detailed tickets for each component will be created as Phase 1 completes.

---

## Phase 2: Verification + Memory (Weeks 4-6)

**Goal:** Full plan → verify loop with persistent memory that compounds across sessions.

### Key Components

#### 1. Memory System (8 hours)

The Memory System is Musonius's key differentiator — it makes session #50 smarter than session #1.

**Files:**
- `musonius/memory/store.py` — SQLite backend with `decisions`, `failures`, `conventions`, and `verification_patterns` tables
- `musonius/memory/conventions.py` — Convention detection from codebase analysis (naming, imports, docstrings, error handling)
- `musonius/memory/decisions.py` — Architectural decision tracking with rationale and confidence decay
- `musonius/memory/failures.py` — Failed approach recording to avoid repeating mistakes

**Key interfaces:**
- `MemoryStore` — CRUD for decisions, conventions, and failures with text search and category filtering
- `ConventionDetector` — Detects naming conventions (snake_case vs camelCase), import organization, docstring style from existing code
- AGENTS.md / CLAUDE.md / .cursorrules import during `musonius init` seeding

**SQLite tables:** `decisions`, `failures`, `conventions`, `verification_patterns` (see `docs/design/MEMORY-SYSTEM-DESIGN.md` for full schema)

**Memory lifecycle:** Seeding (init) → Accumulation (after verification) → Retrieval (during planning/context) → Decay (confidence reduction over time) → Pruning (user management)

#### 2. Verification Engine (10 hours)

Provides the quality gate ensuring implementations match specifications.

**Files:**
- `musonius/verification/engine.py` — Main verification orchestrator
- `musonius/verification/diff_analyzer.py` — Git diff extraction and structured change analysis
- `musonius/verification/severity.py` — Severity classification (Critical/Major/Minor/Outdated)
- `musonius/verification/linter.py` — Project linter integration (ruff, mypy, eslint, etc.)

**Key interfaces:**
- `VerificationEngine.verify(epic_id, phase_id, auto_fix)` → `VerificationResult` with categorized findings
- `DiffAnalyzer.get_diff(base, target)` → Structured `FileChange` objects
- `SeverityClassifier.classify(finding, plan)` → `Severity` enum
- `LinterIntegration.run_linters(files)` → `LintFinding` list

**Severity levels:**
- **Critical** — Blocks core functionality, security vulnerabilities, acceptance criteria failures
- **Major** — Significant behavior changes, performance regressions, missing error handling
- **Minor** — Code style, missing docs, suboptimal implementations
- **Outdated** — Plan references stale files or architecture

#### 3. Intent Engine (6 hours)

Prevents "garbage in, garbage out" by refining user intent before planning.

**Files:**
- `musonius/intent/engine.py` — Intent capture and refinement orchestrator
- `musonius/intent/clarifier.py` — Scout-based question generation (uses free-tier Gemini Flash)

**Key interfaces:**
- `IntentEngine.capture_intent(task_description, auto_clarify)` → `Intent` with business goals, constraints, edge cases, success criteria
- `IntentEngine.ask_clarifying_questions(task, context)` → 3-5 targeted `Question` objects across categories: business, architecture, constraints, edge_cases
- `IntentEngine.refine_intent(original, answers)` → Refined `Intent`

**Cost optimization:** All question generation via Gemini Flash (free tier), cached common patterns, limited to 3-5 questions per round.

### Deliverables
- `musonius verify` command working with severity-categorized output
- `musonius memory` command working (show, search, add, forget, stats, export)
- Persistent memory across sessions via SQLite
- Convention detection from codebase during init
- AGENTS.md import during init
- Intent clarification step in `musonius plan` (3-5 questions via scout model)

### Success Metrics
- Memory reduces token usage by 40%+ via shortcutting redundant scouting
- Verification accuracy >90% (detects 95%+ of plan violations)
- Convention detection accuracy >90%
- Clarification improves plan quality (measured by verification pass rate)
- False positive rate <10% for verification findings

---

## Phase 3: Agent Handoff + Automation (Weeks 7-10)

**Goal:** Universal agent support with configurable automation and format-specific handoffs.

### Key Components

#### 1. Agent Plugin System (12 hours)

Enables Musonius to format context for any AI coding agent through a clean abstraction layer.

**Files:**
- `musonius/context/agents/base.py` — `AgentPlugin` ABC + `AgentCapabilities` dataclass
- `musonius/context/agents/registry.py` — Plugin discovery (project YAML → user YAML → built-in → pip entry points)
- `musonius/context/agents/claude.py` — Claude Code plugin (XML-structured format)
- `musonius/context/agents/gemini.py` — Gemini CLI plugin (natural language format)
- `musonius/context/agents/grok.py` — Grok plugin
- `musonius/context/agents/cursor.py` — Cursor plugin (.cursorrules format)
- `musonius/context/agents/generic.py` — Universal markdown fallback (AGENTS.md)
- `musonius/context/agents/custom.py` — YAML-defined custom agent loader

**Plugin interface:**
- `AgentPlugin.capabilities()` → `AgentCapabilities` (name, slug, max_context_tokens, handoff_method, supports_xml, etc.)
- `AgentPlugin.format_context(task, plan, repo_map, memory, token_budget)` → Formatted string
- `AgentPlugin.handoff_command(context_file)` → CLI command or None

**Custom agents via YAML:**
```yaml
# .musonius/agents/roo-code.yaml
name: "Roo Code"
slug: "roo-code"
format: "generic"
preferences:
  max_tokens: 128000
  tone: "direct"
handoff:
  method: "file"
  output_path: ".roo/"
```

#### 2. Handoff Generator (6 hours)

Generates token-budgeted, agent-specific context files.

**Files:**
- `musonius/orchestration/handoff.py` — Context file generation and delivery

**Key responsibilities:**
- Format adaptation per agent (XML for Claude, natural language for Gemini, .cursorrules for Cursor)
- Token budget allocation: 30% for task/plan/memory, 70% for repo context
- Detail level selection (L0-L3) based on budget
- Handoff delivery: file, clipboard, stdin, CLI argument

#### 3. Prep Command (4 hours)

Wires the agent plugin system into the CLI.

**Files:**
- `musonius/cli/prep.py` — Context file generation command
- `musonius/cli/agents.py` — Agent management commands (list, info, add)

**CLI usage:**
```bash
musonius prep epic-004 --agent claude    # Generate CLAUDE.md
musonius prep epic-004 --agent gemini    # Generate GEMINI.md
musonius prep epic-004 --agent grok      # Generate context for Grok
musonius agents list                      # List available agents
musonius agents info claude               # Show agent capabilities
```

### Deliverables
- `musonius prep` command working with agent-specific formatting
- `musonius agents` command working (list, info, add)
- 5+ built-in agent plugins (Claude, Gemini, Grok, Cursor, Generic)
- Custom YAML agent definitions supported
- Handoff templates with token budget enforcement
- AGENTS.md auto-detection during init

### Success Metrics
- 5+ agent plugins produce correctly formatted context
- Custom YAML agents load and format successfully
- Plugin discovery resolves priority correctly (project > user > built-in)
- Context formatting respects token budgets
- Handoff completes in <5s

---

## Phase 4: Advanced Features (Weeks 11-14)

**Goal:** Epic mode with multi-phase planning, standalone code review, and MCP server for IDE integration.

### Key Components

#### 1. Multi-Phase Planning (8 hours)

Extends the planning engine to decompose large tasks into ordered phases with dependency analysis.

**Files:**
- `musonius/planning/phaser.py` — Multi-phase decomposition logic
- `musonius/planning/engine.py` — Extended with phase dependency analysis

**Key capabilities:**
- Phase decomposition with file-level instructions and acceptance criteria per phase
- Dependency analysis between phases (which phases block others)
- Context carryover: Phase N+1 receives verification results and decisions from Phase N
- Progressive context loading: each phase only sees relevant files

**CLI usage:**
```bash
musonius plan "add auth system" --phases     # Multi-phase plan
musonius plan "add auth system" --phases 3   # Limit to 3 phases
```

#### 2. Review Mode (6 hours)

Standalone code review without requiring a plan — useful for PR reviews and general code quality.

**Files:**
- `musonius/cli/review.py` — Review command
- `musonius/verification/engine.py` — Extended with plan-less review mode

**Review categories:** Bug, Performance, Security, Clarity

**CLI usage:**
```bash
musonius review                        # Review current changes
musonius review --file src/auth.py     # Review specific file
musonius review --severity critical    # Filter by severity
```

#### 3. MCP Server (10 hours)

Exposes Musonius as an MCP server for universal IDE integration (VS Code, JetBrains, Cursor, etc.).

**Files:**
- `musonius/mcp/server.py` — FastMCP server implementation

**MCP tools exposed:**
- `musonius_get_plan` — Returns current phase plan with optimized context
- `musonius_get_context` — Returns token-budgeted context for a file/function
- `musonius_verify` — Triggers cross-model verification of current changes
- `musonius_memory_query` — Searches project memory for decisions and patterns
- `musonius_record_decision` — Adds a new decision to Source of Truth

#### 4. Additional Features
- Mermaid diagram generation from dependency graph
- Autonomy levels 4-5 (YOLO modes with auto-apply)
- Prompt caching optimization for 30-50% cost reduction
- Per-task cost analytics and reporting

### Deliverables
- `musonius plan --phases` working with dependency analysis
- `musonius review` command working with category-based findings
- MCP server integrating with IDEs via FastMCP
- Mermaid diagram generation from repo graph
- Per-task cost analytics

### Success Metrics
- Multi-phase plans decompose correctly with valid dependencies
- Review mode finds 90%+ of issues across Bug/Performance/Security/Clarity
- MCP server integrates with VS Code and Cursor
- Prompt caching achieves 30%+ cost reduction

---

## Phase 5: Scale + Community (Weeks 15+)

**Goal:** Team features, GitHub integration, parallel execution, and community plugin ecosystem.

### Key Components

#### 1. GitHub Integration (8 hours)

Import issues directly as tasks, auto-generate plans from issue descriptions.

**Files:**
- `musonius/integrations/github.py` — GitHub API integration

**Key capabilities:**
- Issue import: `musonius plan --from-issue 42`
- Auto-plan from issue descriptions with label-based priority
- Ticket assist: generate implementation tickets from issues

#### 2. Parallel Execution (12 hours)

Execute independent phases concurrently using git worktrees.

**Files:**
- `musonius/parallel/worktree.py` — Worktree lifecycle management
- `musonius/parallel/coordinator.py` — Phase dependency analysis + parallel dispatch
- `musonius/parallel/merger.py` — Conflict detection and resolution

**Key capabilities:**
- Git worktree creation/cleanup for isolated phase execution
- Parallel dispatch of non-dependent phases
- Conflict detection between parallel branches
- Automated merge with conflict resolution assistance

#### 3. Community Features (ongoing)

Build the foundation for a community plugin ecosystem.

**Key capabilities:**
- Plugin entry points via pip (`pip install musonius-agent-*`)
- Community plugin ecosystem with shared registry
- Plugin templates for common patterns
- Team shared memory (sync across developers)
- Web dashboard for analytics and memory visualization

### Deliverables
- `musonius plan --from-issue` working with GitHub integration
- Parallel phase execution via git worktrees
- Plugin ecosystem foundation with pip entry points
- Comprehensive documentation and examples
- Web dashboard for analytics (optional)

### Success Metrics
- GitHub integration imports and plans from issues smoothly
- Parallel execution reduces total time by 50%+ for multi-phase tasks
- Community plugins installable via pip
- Documentation covers all commands, plugins, and configuration

---

## Cross-Phase Testing Strategy

Each phase includes:
- **Unit tests** for all new components (target: 80%+ coverage on core modules)
- **Integration tests** for end-to-end workflows
- **Performance benchmarks** for token usage and execution time
- **Documentation updates** for new commands and features

Test infrastructure:
- Mock all LLM calls using recorded responses
- Use fixtures for SQLite databases and temp directories
- Test the contract (inputs/outputs), not the implementation
- Every module gets a corresponding `tests/test_{module}.py`

---

## Dependencies Between Phases

```
Phase 1 (Core CLI + Planning)
    ├── Phase 2 (Verification + Memory)
    │       ├── Phase 3 (Agent Handoff + Automation)
    │       │       └── Phase 4 (Advanced Features)
    │       │               └── Phase 5 (Scale + Community)
    │       └── Phase 4 (MCP Server needs verification)
    └── Phase 3 (Agent plugins build on context engine)
```

- **Phase 2** requires Phase 1's indexer, context engine, and planning engine
- **Phase 3** requires Phase 2's memory system (for memory-enriched handoffs) and Phase 1's context engine
- **Phase 4** requires Phase 2's verification engine (for review mode) and Phase 3's agent plugins (for MCP)
- **Phase 5** requires Phase 4's multi-phase planning (for parallel execution)

---

## References

- Architecture overview: `docs/ARCHITECTURE.md`
- Tech stack and roadmap: `docs/TECH-STACK.md`
- Memory system: `docs/MEMORY-SYSTEM.md`
- Agent handoff protocol: `docs/AGENT-HANDOFF.md`
- System design: `docs/design/SYSTEM-DESIGN.md`
- Design specs: See epic design documents for detailed component specs
