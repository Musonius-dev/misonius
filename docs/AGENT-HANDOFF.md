# Universal Agent Handoff Architecture

## Overview

Musonius interacts with AI in two distinct ways that require separate extension points:

**Layer 1 — Internal Model Routing:** Models Musonius calls directly for scouting, planning, and verification. Handled by LiteLLM. Any OpenAI-compatible API works out of the box.

**Layer 2 — Agent Handoff:** Downstream coding tools that receive Musonius's context files. Each agent has different format preferences. This requires the plugin system.

```
┌─────────────────────────────────────────────────────────┐
│  INTERNAL MODEL ROUTING (LiteLLM)                       │
│  Models Musonius calls directly for its own work        │
│                                                         │
│  Scout → Gemini Flash (free) / Ollama (local)           │
│  Planner → Claude / Gemini Pro / Grok / Deepseek        │
│  Verifier → Gemini Flash / Grok / Local model           │
│                                                         │
│  Config: .musonius/config.yaml → models section         │
│  Extension: Just add LiteLLM-compatible model string    │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
              [Context Document]
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│  AGENT HANDOFF (Plugin System)                          │
│  Format + deliver context to downstream coding tools    │
│                                                         │
│  Claude Code → XML-structured CLAUDE.md                 │
│  Gemini CLI → Natural language GEMINI.md                │
│  Grok → Direct markdown GROK_CONTEXT.md                 │
│  Cursor → .cursorrules                                  │
│  Aider → File-list + diff format                        │
│  Any CLI → Custom YAML agent definition                 │
│                                                         │
│  Config: .musonius/agents/*.yaml or Python plugins      │
│  Extension: YAML config or pip-installable plugin       │
└─────────────────────────────────────────────────────────┘
```

Both layers are independently extensible. You can use Grok as your internal planner AND hand off to Claude Code for implementation.

---

## Internal Model Configuration

```yaml
# .musonius/config.yaml
models:
  scout: "gemini/gemini-2.0-flash"
  planner: "anthropic/claude-sonnet-4-20250514"
  verifier: "xai/grok-3"
  summarizer: "ollama/llama3.2"

  custom:
    - name: "deepseek-r1"
      provider: "openai"
      api_base: "https://api.deepseek.com/v1"
      api_key_env: "DEEPSEEK_API_KEY"
      model: "deepseek-reasoner"

    - name: "local-qwen"
      provider: "openai"
      api_base: "http://localhost:11434/v1"
      model: "qwen2.5-coder:32b"
```

LiteLLM supports 100+ providers natively: OpenAI, Anthropic, Google, xAI (Grok), Mistral, Cohere, Deepseek, Together, Groq, Fireworks, Ollama, vLLM, and anything OpenAI-compatible.

---

## Agent Plugin Interface

```python
# musonius/context/agents/base.py

@dataclass
class AgentCapabilities:
    name: str                    # Display name
    slug: str                    # CLI identifier (--agent slug)
    file_extension: str          # Output file extension
    file_name: str               # Output file name (e.g., "CLAUDE.md")
    supports_xml: bool           # Can it parse XML structured prompts?
    supports_mermaid: bool       # Can it render mermaid diagrams?
    supports_file_refs: bool     # Can it open files by path?
    supports_yolo: bool          # Can it run autonomously via CLI?
    max_context_tokens: int      # Rough context window size
    handoff_method: str          # "file" | "stdin" | "clipboard" | "cli_arg"
    cli_command: str | None      # Command to invoke (if CLI-based)
    description: str             # For --help output


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
        conventions: list[dict],
        token_budget: int,
    ) -> str: ...

    def format_verification_prompt(self, diff: str, plan: dict) -> str: ...
    def handoff_command(self, context_file: Path) -> str | None: ...
```

---

## Built-in Agent Plugins

```
musonius/context/agents/
├── base.py        # AgentPlugin ABC + AgentCapabilities
├── registry.py    # Plugin discovery and registration
├── claude.py      # Claude Code (XML-structured, tool-aware)
├── gemini.py      # Gemini CLI (natural language, concise)
├── cursor.py      # Cursor (.cursorrules format)
├── grok.py        # Grok (direct, concise markdown)
├── copilot.py     # GitHub Copilot (markdown with code fences)
├── aider.py       # Aider (diff-focused, file-list format)
├── codex.py       # OpenAI Codex CLI
├── cline.py       # Cline (VS Code extension)
├── windsurf.py    # Windsurf (Codeium)
├── generic.py     # AGENTS.md fallback (works with anything)
└── custom.py      # User-defined agent from YAML config
```

---

## Format Adaptation Matrix

All agents consume the same underlying data. The difference is presentation:

| Aspect | Claude | Gemini | Grok | Cursor | Generic |
|--------|--------|--------|------|--------|---------|
| Structure | XML tags | Headers + prose | Headers + prose | JSON-like rules | Markdown |
| Tone | Detailed, systematic | Concise, natural | Direct, minimal | Terse rule lists | Balanced |
| Code refs | Full paths + sigs | Paths + brief ctx | Paths only | Glob patterns | Paths + sigs |
| Memory format | `<project_knowledge>` | "Keep in mind:" | "Known constraints:" | Comment blocks | "## Context" |
| Max tokens | 200K | 1M+ | 131K | ~20K | 100K default |

Token budget automatically adjusts detail level: Cursor gets L0 (signatures only), Claude gets L2 (signatures + docstrings + key logic).

---

## Custom Agent YAML Format

Users define any agent without writing Python:

```yaml
# .musonius/agents/roo-code.yaml
name: "Roo Code"
slug: "roo-code"
description: "Roo Code VS Code extension"
file_name: "AGENTS.md"
format: "generic"            # Base formatter to use

preferences:
  use_xml: false
  use_mermaid: true
  max_tokens: 128000
  tone: "direct"             # direct | detailed | conversational
  include_full_file_contents: false
  include_test_examples: true

handoff:
  method: "file"             # file | clipboard | stdin | cli_arg
  command: null               # No CLI — manual copy
  output_path: ".roo/"       # Where to write context file

templates:
  prepend: |
    You are working on a Python project. Follow PEP 8.
    Always run tests after changes.
  append: |
    When done, create a summary of changes in CHANGELOG.md.
```

---

## Plugin Registry

- **Built-in plugins** registered via `@register("slug")` decorator
- **Custom YAML agents** discovered from `.musonius/agents/` (project) and `~/.musonius/agents/` (user)
- **Community plugins** (future) via pip entry points: `pip install musonius-agent-{name}`

Priority: Project YAML > User YAML > Built-in Python plugin

---

## CLI Commands

```bash
musonius agents list              # List all available agents
musonius agents info grok         # Show agent capabilities
musonius agents add               # Interactive custom agent creation
musonius prep epic-004 --agent grok     # Generate context for specific agent
musonius prep epic-004 --agent claude   # Generate + auto-handoff via CLI
```

---

## Adding a New Agent: Three Options

| Option | Effort | When to Use |
|--------|--------|-------------|
| YAML config | 2 min, no code | New agent that's similar to existing format |
| Python plugin | 30 min | Agent needs unique formatting logic |
| Pip-installable | Varies | Community contribution / complex integration |

---

## AGENTS.md Auto-Detection

During `musonius init`, the system detects and imports existing agent config files:

- `AGENTS.md` — Open standard for AI coding agents
- `CLAUDE.md` — Claude Code specific instructions
- `.cursorrules` — Cursor rules
- `.github/copilot-instructions.md` — GitHub Copilot

Conventions are imported into `.musonius/memory/conventions.json`. Musonius doesn't replace existing agent files — it enriches them.

---

## Handoff Templates

Templates wrap generated context with custom instructions using Handlebars-style tags:

```markdown
<!-- .musonius/templates/claude-handoff.md -->
Follow the below plan verbatim. Trust the files and references.
Do not re-verify what's written in the plan.

{{context}}

## After Implementation
- Run `pytest` to execute the full test suite
- Run `ruff check .` to verify linting
- If any tests fail, fix the issues before considering complete
```

Template scopes:
- `.musonius/templates/` — Project-specific
- `~/.musonius/templates/` — User-global defaults

Template types:
- `plan` — Wraps implementation plans
- `verification` — Wraps verification prompts
- `review` — Wraps code review prompts
- `generic` — Reusable for any context
