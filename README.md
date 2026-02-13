# Musonius

> "Philosophy must be practical, not theoretical. Specs must be actionable, not ephemeral."
> — Musonius Rufus, 30–101 AD

**Stop burning tokens on exploration.** Musonius pre-computes your codebase context locally so your AI coding agent goes straight to surgical execution.

Musonius is an open-source CLI tool that sits between your intent and your AI coding agents. It indexes your codebase with tree-sitter, maintains persistent project memory, and generates optimized handoff documents for any downstream agent — Claude Code, Gemini CLI, Cursor, Aider, Codex, or anything else that reads markdown.

Musonius is the coach, not the player. It doesn't write code — it makes every tool that does write code 3–5x more effective.

## Install

Requires Python 3.12+.

```bash
pip install musonius
```

Or install from source:

```bash
git clone https://github.com/musonius-dev/musonius.git
cd musonius
pip install -e ".[dev]"
```

## Quick Start

### 1. Initialize your project

```bash
cd your-project
musonius init
```

This indexes your codebase with tree-sitter, auto-detects coding conventions (naming style, docstring format, test framework, linting tools), and creates a `.musonius/` directory with your project's dependency graph and memory store.

### 2. Plan a task

```bash
musonius plan "add rate limiting to the public API"
```

Decomposes your task into phased implementation steps using a scout model (Gemini Flash, free tier). Each phase includes specific files to modify, acceptance criteria, and estimated token budgets.

### 3. Generate a handoff

```bash
musonius prep --agent claude
```

Produces an optimized context file (`HANDOFF.md`) tailored to your chosen agent. Includes only the relevant portion of your codebase — function signatures, dependency chains, conventions, and prior decisions — so the agent skips exploration and goes straight to implementation.

Supported agents: `claude`, `gemini`, `grok`, `cursor`, `generic` (or any custom agent plugin).

### 4. Verify changes

```bash
musonius verify
```

Captures your git diff and runs cross-model adversarial review. A different model reviews the implementation for correctness, security, and adherence to project conventions.

## CLI Reference

| Command | Purpose |
|---------|---------|
| `musonius init` | Index codebase, detect conventions, create `.musonius/` scaffold |
| `musonius plan "task"` | Decompose task into phased plan via scout agent |
| `musonius prep --agent <name>` | Generate optimized handoff for chosen agent |
| `musonius verify` | Cross-model adversarial review of git diff |
| `musonius review` | Review current changes against plan |
| `musonius memory search "query"` | Search project decisions, conventions, failures |
| `musonius memory add` | Add a decision or convention manually |
| `musonius status` | Token usage, phase progress, memory stats |
| `musonius rollback <epic> <phase>` | Restore to a phase checkpoint |
| `musonius serve` | Start the MCP server for IDE integration |
| `musonius agents list` | List available agent plugins |

## MCP Server (IDE Integration)

Musonius exposes an MCP server so Claude Code, Cursor, and other MCP-compatible tools can query your project context directly.

### Claude Code

Add to your Claude Code MCP config (`~/.claude/mcp.json`):

```json
{
  "mcpServers": {
    "musonius": {
      "command": "musonius",
      "args": ["serve"],
      "env": {}
    }
  }
}
```

### Cursor

Add to your Cursor MCP settings (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "musonius": {
      "command": "musonius",
      "args": ["serve"],
      "env": {}
    }
  }
}
```

### Available MCP Tools

Once connected, your AI agent gains access to:

- **musonius_get_plan** — Get the current phase plan with optimized context
- **musonius_get_context** — Get token-budgeted context for a specific file or function
- **musonius_verify** — Trigger cross-model verification of current changes
- **musonius_memory_query** — Search project decisions, conventions, and failure records
- **musonius_record_decision** — Record an architectural decision to project memory
- **musonius_status** — Get project health: index stats, memory counts, epic progress

## How It Works

Musonius uses 7 optimization strategies to reduce token consumption by downstream agents:

1. **AST-aware progressive context** — Tree-sitter parses your code into 4 levels: L0 (file paths), L1 (function signatures), L2 (signatures + docstrings), L3 (full implementation). Only the relevant level is included.

2. **Compact serialization** — 65% smaller than raw JSON for dependency graphs and symbol tables.

3. **Hierarchical summarization** — Long files are summarized with anchored compression, preserving key signatures while reducing bulk.

4. **Scout/thinker separation** — Cheap models (Gemini Flash, free tier) handle scouting and verification. Premium models are reserved for implementation.

5. **Prompt caching optimization** — Handoff documents are prefix-optimized for 30-50% cost reduction on models that support prompt caching.

6. **Tool schema pruning** — Strips unused tool definitions from context, saving 1,000-2,000 tokens per call.

7. **Diff-based verification** — Reviews only changed code (git diff), not entire files. 60-80% reduction vs full-file review.

## Project Memory

Every completed task enriches your project's persistent memory. Musonius stores:

- **Conventions** — Detected and user-defined coding patterns (naming, docstrings, imports, tooling)
- **Decisions** — Architectural choices with rationale (tech stack, API contracts, dependencies)
- **Failures** — Approaches that didn't work and why (anti-pattern library)

Memory persists across sessions, across tools, and across team members. A new developer running `musonius init` on a 6-month project gets instant tribal knowledge.

## Configuration

Musonius stores configuration in `.musonius/config.yaml`:

```yaml
models:
  scout: gemini/gemini-2.0-flash
  planner: anthropic/claude-sonnet-4-20250514
  verifier: gemini/gemini-2.0-flash
  summarizer: ollama/llama3.2
default_agent: claude
autonomy:
  level: 2
  max_retries: 3
  stop_on: critical
project:
  language: python
  test_command: pytest
  lint_command: ruff check .
```

All model routing goes through LiteLLM, supporting 100+ providers including Claude, Gemini, OpenAI, Ollama, and any OpenAI-compatible endpoint.

## Development

```bash
git clone https://github.com/musonius-dev/musonius.git
cd musonius
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check .
ruff format --check .

# Type check
mypy musonius/
```

## License

MIT
