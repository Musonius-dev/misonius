# Task Modes & CLI Reference

## Command Overview

```
musonius init          Initialize project (detect codebase, import conventions)
musonius plan          Generate implementation plan (single or phased)
musonius prep          Generate agent-ready context file from plan
musonius verify        Verify implementation against plan
musonius review        Standalone code review (not tied to a plan)
musonius epic          Full spec → ticket → phase workflow
musonius run           Execute plan with configured autonomy level
musonius agents        Manage agent plugins
musonius memory        View/manage project memory
musonius status        Show current epic/phase status
```

---

## Task Modes

Inspired by Traycer's four modes but improved with CLI-first design and persistent memory.

### Plan Mode (`musonius plan`)

Best for well-scoped tasks that can be implemented in a single session.

```bash
musonius plan "fix authentication bug in login handler"
musonius plan "add rate limiting to public API" --clarify  # Force intent clarification
musonius plan --from-issue 42                               # From GitHub issue (v0.2)
```

**Workflow:**
1. User describes task
2. Scout agent (free) analyzes codebase, asks 3-5 clarifying questions
3. Planner generates single-phase plan with file-level instructions
4. Plan saved to `.musonius/epics/{id}/phases/phase-01.md`

### Phases Mode (`musonius plan --phases`)

Best for complex features spanning multiple services.

```bash
musonius plan "add user authentication system" --phases
musonius plan "migrate database from Postgres to CockroachDB" --phases --max-phases 8
```

**Workflow:**
1. User describes complex task
2. Scout agent asks clarifying questions
3. Planner decomposes into sequenced phases with dependencies
4. Each phase gets its own plan file
5. Context carries forward between phases (decisions, file mappings)

### Review Mode (`musonius review`)

Standalone code review not tied to a plan. Categorized findings.

```bash
musonius review                          # Review uncommitted changes
musonius review --against main           # Review vs main branch
musonius review --against abc123         # Review vs specific commit
musonius review --focus security         # Focus on security issues
```

**Output categories:**
- **Bug** — Functional issues, logic errors
- **Performance** — Inefficiencies, bottlenecks
- **Security** — Vulnerabilities, unsafe practices
- **Clarity** — Readability, maintainability, documentation

### Epic Mode (`musonius epic`)

Full spec-driven workflow. Captures intent as mini-specs before implementation. (v0.2)

```bash
musonius epic "user authentication system"
musonius epic --from-spec .musonius/sot/auth-prd.md
```

**Workflow:**
1. Elicitation: AI asks pointed questions to surface constraints, edge cases, invisible rules
2. Spec generation: PRD, Tech Doc, API Spec, Design Spec as mini-specs
3. Ticket decomposition: Break specs into actionable implementation tickets
4. Phase planning: Tickets become phases with detailed plans
5. Execution + verification loop

**Spec types:**
- PRD — Product requirements
- Tech Doc — Architecture and technical approach
- API Spec — Endpoints, contracts, integration requirements
- Design Spec — User flows, UX decisions

All specs stored as git-versioned markdown in `.musonius/epics/{id}/specs/`.

---

## Verification (`musonius verify`)

Compares implementation against the plan. Severity-categorized output.

```bash
musonius verify                          # Verify current phase against plan
musonius verify --phase 2                # Verify specific phase
musonius verify --fix                    # Auto-generate fix suggestions
```

**Severity levels:**
- 🔴 **Critical** — Blocks core functionality or plan requirements
- 🟡 **Major** — Significant issues affecting behavior or UX
- 🔵 **Minor** — Small polish items that don't block functionality
- ⬜ **Outdated** — Plan references that are no longer accurate

**Verification results** stored in `.musonius/epics/{id}/verification/phase-{n}.json` and fed back into project memory.

---

## Autonomy Levels (`musonius run`)

Configurable automation depth from fully manual to fully autonomous.

```yaml
# .musonius/config.yaml
autonomy:
  level: 3
```

| Level | Name | Behavior |
|-------|------|----------|
| 0 | Manual | Generate plans only, never execute |
| 1 | Supervised | Execute with confirmation at each step |
| 2 | Guided | Execute phases, pause for verification review |
| 3 | Autonomous | Execute + verify, pause only on critical findings |
| 4 | YOLO | Full auto, stop only on test failures |
| 5 | YOLO+ | Full auto including auto-fix of verification findings |

```bash
musonius run epic-004 --autonomy 4       # YOLO mode for this epic
musonius run epic-004 --autonomy 1       # Supervised, confirm each step
```

---

## Context Generation (`musonius prep`)

Generates the agent-ready context file from a plan.

```bash
musonius prep epic-004                   # Use default agent from config
musonius prep epic-004 --agent grok      # Generate for Grok format
musonius prep epic-004 --agent claude    # Generate + auto-handoff via CLI
musonius prep epic-004 --phase 2         # Only phase 2
musonius prep epic-004 --dry-run         # Show what would be generated
```

**What goes into the context file:**
1. Task description
2. Relevant repo map (at appropriate detail level for agent's context window)
3. Project conventions from memory
4. Relevant architectural decisions from memory
5. Phased plan with file-level instructions
6. Known constraints and past failures

---

## Project Initialization (`musonius init`)

```bash
musonius init                            # Interactive setup
musonius init --auto                     # Auto-detect everything
```

**What `init` does:**
1. Creates `.musonius/` directory structure
2. Runs tree-sitter indexing to build repo map
3. Detects and imports existing agent configs (AGENTS.md, CLAUDE.md, .cursorrules)
4. Detects project language, framework, test runner
5. Creates initial `config.yaml` with sensible defaults
6. Stores detected conventions in memory

---

## Memory Management (`musonius memory`)

```bash
musonius memory show                     # Show all stored knowledge
musonius memory show --type decisions    # Filter by type
musonius memory search "rate limiting"   # Search memory
musonius memory add "Always use Redis for caching in this project"
musonius memory forget --id 42           # Remove specific memory
musonius memory export                   # Export as JSON
musonius memory stats                    # Token savings from memory
```

---

## Mermaid Diagrams in Plans

Plans include auto-generated Mermaid diagrams showing:
- File relationships and data flow for the phase
- Dependency graph of touched files
- Before/after architecture (for refactoring tasks)

Generated from the tree-sitter dependency graph, not LLM-generated (deterministic, $0).
