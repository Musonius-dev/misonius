# Project Musonius — Master Knowledge File

> "Philosophy must be practical, not theoretical. Specs must be actionable, not ephemeral."
> — Musonius Rufus (paraphrased), the teacher of Epictetus

## Identity

- **Name:** Musonius (named after the Stoic philosopher Gaius Musonius Rufus)
- **Domain:** musonius.dev
- **Repo:** github.com/ArcaneSME/musonius.dev (MIT License, Copyright 2026 ArcaneSME)
- **Tagline:** Spec-driven development orchestrator. Local-first. Model-agnostic. Memory that compounds.
- **Previously codenamed:** FORGE (in early architecture docs)

## What Musonius Is

Musonius is an open-source, CLI-first AI coding orchestrator that turns high-level intent into structured, phased implementation plans — then hands off to any AI coding agent (Claude Code, Cursor, Grok, Aider, Copilot, etc.) with optimized context files.

It solves the problem that AI coding agents are powerful but drift: they hallucinate APIs, misread intent, and lose context in large codebases. Musonius provides the planning, memory, and verification layer that keeps agents on track.

## Core Principles

1. **Specs must be actionable, not ephemeral** — Every plan is a git-versioned file, not ephemeral UI state
2. **Never send a token you don't need to** — AST-based local indexing, progressive context loading, scout/thinker model separation
3. **Memory compounds forever** — SQLite-backed persistent knowledge that makes session #50 smarter than session #1
4. **Model-agnostic, agent-agnostic** — Works with any LLM provider and hands off to any coding tool
5. **CLI-first, local-first** — Works on an airplane, in any terminal, with any editor

## Competitive Positioning

### vs. Traycer AI
Traycer proved the market for spec-driven development. Musonius delivers it as open-source infrastructure:

| Dimension | Traycer | Musonius |
|-----------|---------|----------|
| Pricing | Artifact slots with cooldowns + $0.50 refills | BYOK — pay API costs only |
| Token efficiency | No optimization layer | 7-strategy optimization, ~70% reduction |
| Cross-session memory | None (dies per session) | Persistent SQLite knowledge graph |
| IDE support | VS Code extension only | CLI + MCP + any IDE |
| Automation control | Binary manual/YOLO | 0-5 autonomy scale with retry policies |
| Agent support | 16 agents, closed config | Plugin system, YAML config, pip-installable |
| Self-hostable | No (cloud-required) | Yes — fully local option |
| Codebase indexing | Runtime LLM exploration (burns tokens) | Pre-computed tree-sitter AST graph ($0) |
| Architecture | Closed source, cloud platform | MIT licensed, inspectable, forkable |

### Key Differentiators
1. **Local tree-sitter indexing** — Pre-computes dependency graph and repo map locally. Zero tokens for codebase exploration.
2. **Persistent memory** — Architectural decisions, conventions, past failures survive across all sessions.
3. **Scout/Thinker separation** — Free-tier models (Gemini Flash) handle 60-70% of operations.
4. **Universal agent handoff** — Plugin system supports any downstream coding tool via format adapters.
5. **Git-versioned specs** — Plans, epics, and verification results live in `.musonius/` as trackable files.
