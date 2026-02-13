"""CLI Backend — routes LLM calls through locally installed CLI tools (claude, gemini).

Instead of requiring API keys, this backend detects installed CLI tools
and shells out to them. This lets users leverage their existing
Claude Code subscription or Gemini CLI (free tier) with zero config.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Timeout for CLI calls (seconds)
CLI_TIMEOUT = 300


@dataclass
class CLITool:
    """A detected CLI tool.

    Attributes:
        name: Tool name (claude, gemini).
        command: Full path to the executable.
        provider: Provider identifier for routing.
    """

    name: str
    command: str
    provider: str


def detect_cli_tools() -> dict[str, CLITool]:
    """Detect available CLI tools on the system.

    Checks for claude and gemini CLI tools in PATH.

    Returns:
        Dict mapping tool name to CLITool info.
    """
    tools: dict[str, CLITool] = {}

    claude_path = shutil.which("claude")
    if claude_path:
        tools["claude"] = CLITool(
            name="claude",
            command=claude_path,
            provider="anthropic",
        )
        logger.debug("Found Claude CLI at %s", claude_path)

    gemini_path = shutil.which("gemini")
    if gemini_path:
        tools["gemini"] = CLITool(
            name="gemini",
            command=gemini_path,
            provider="google",
        )
        logger.debug("Found Gemini CLI at %s", gemini_path)

    return tools


def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
    """Convert OpenAI-style messages to a single prompt string for CLI tools.

    Args:
        messages: Chat messages in [{"role": "...", "content": "..."}] format.

    Returns:
        Combined prompt string.
    """
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "system":
            parts.append(f"<system>\n{content}\n</system>\n")
        elif role == "assistant":
            parts.append(f"<assistant>\n{content}\n</assistant>\n")
        else:
            parts.append(content)
    return "\n".join(parts)


def call_claude_cli(
    messages: list[dict[str, str]],
    max_tokens: int | None = None,
    timeout: int = CLI_TIMEOUT,
) -> dict[str, Any]:
    """Call Claude via the Claude Code CLI.

    Uses `claude -p "prompt"` for non-interactive single-shot mode.

    Args:
        messages: Chat messages.
        max_tokens: Maximum output tokens (passed via --max-turns 1).
        timeout: Command timeout in seconds.

    Returns:
        Dict with 'content', 'model', and timing info.

    Raises:
        RuntimeError: If the CLI call fails.
    """
    prompt = _messages_to_prompt(messages)

    cmd = ["claude", "-p", prompt]

    if max_tokens:
        cmd.extend(["--max-tokens", str(max_tokens)])

    logger.debug("Calling Claude CLI: %s chars prompt", len(prompt))
    start = time.monotonic()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Claude CLI timed out after {timeout}s") from e
    except FileNotFoundError as e:
        raise RuntimeError("Claude CLI not found. Install with: npm install -g @anthropic-ai/claude-code") from e

    elapsed_ms = (time.monotonic() - start) * 1000

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Claude CLI failed (exit {result.returncode}): {stderr}")

    content = result.stdout.strip()
    if not content:
        raise RuntimeError("Claude CLI returned empty output")

    return {
        "content": content,
        "model": "claude-cli",
        "latency_ms": elapsed_ms,
    }


def call_gemini_cli(
    messages: list[dict[str, str]],
    max_tokens: int | None = None,
    timeout: int = CLI_TIMEOUT,
) -> dict[str, Any]:
    """Call Gemini via the Gemini CLI.

    Uses `gemini -p "prompt"` for non-interactive mode.

    Args:
        messages: Chat messages.
        max_tokens: Maximum output tokens.
        timeout: Command timeout in seconds.

    Returns:
        Dict with 'content', 'model', and timing info.

    Raises:
        RuntimeError: If the CLI call fails.
    """
    prompt = _messages_to_prompt(messages)

    cmd = ["gemini", "-p", prompt]

    logger.debug("Calling Gemini CLI: %s chars prompt", len(prompt))
    start = time.monotonic()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Gemini CLI timed out after {timeout}s") from e
    except FileNotFoundError as e:
        raise RuntimeError("Gemini CLI not found. Install with: npm install -g @anthropic-ai/gemini-cli") from e

    elapsed_ms = (time.monotonic() - start) * 1000

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise RuntimeError(f"Gemini CLI failed (exit {result.returncode}): {stderr}")

    content = result.stdout.strip()
    if not content:
        raise RuntimeError("Gemini CLI returned empty output")

    return {
        "content": content,
        "model": "gemini-cli",
        "latency_ms": elapsed_ms,
    }


def call_cli(
    tool_name: str,
    messages: list[dict[str, str]],
    max_tokens: int | None = None,
    timeout: int = CLI_TIMEOUT,
) -> dict[str, Any]:
    """Route a call to the appropriate CLI tool.

    Args:
        tool_name: Tool name ("claude" or "gemini").
        messages: Chat messages.
        max_tokens: Maximum output tokens.
        timeout: Command timeout in seconds.

    Returns:
        Dict with 'content', 'model', and timing info.

    Raises:
        ValueError: If tool_name is unknown.
        RuntimeError: If the CLI call fails.
    """
    if tool_name == "claude":
        return call_claude_cli(messages, max_tokens=max_tokens, timeout=timeout)
    elif tool_name == "gemini":
        return call_gemini_cli(messages, max_tokens=max_tokens, timeout=timeout)
    else:
        raise ValueError(f"Unknown CLI tool: {tool_name}")
