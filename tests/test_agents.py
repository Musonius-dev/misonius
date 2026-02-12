"""Tests for agent plugins."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from musonius.context.agents.base import AgentCapabilities, AgentPlugin
from musonius.context.agents.claude import ClaudePlugin
from musonius.context.agents.cursor import CursorPlugin
from musonius.context.agents.gemini import GeminiPlugin
from musonius.context.agents.generic import GenericPlugin
from musonius.context.agents.grok import GrokPlugin
from musonius.context.agents.registry import (
    AgentRegistry,
    create_default_registry,
    create_full_registry,
)

# -- Shared fixtures --------------------------------------------------------

SAMPLE_PLAN = {
    "phases": [
        {
            "title": "Phase 1",
            "description": "Build auth",
            "files": [{"path": "src/auth.py", "description": "Auth module"}],
            "acceptance_criteria": ["Tests pass", "No regressions"],
        }
    ]
}

SAMPLE_MEMORY = [
    {"summary": "Use JWT", "rationale": "Industry standard"},
    {"summary": "Use bcrypt", "rationale": "Secure hashing"},
]


# -- Plugin capability tests ------------------------------------------------


class TestAgentCapabilities:
    """Tests for AgentCapabilities fields on all built-in plugins."""

    @pytest.mark.parametrize(
        ("plugin_cls", "slug", "file_name"),
        [
            (ClaudePlugin, "claude", "CLAUDE.md"),
            (GeminiPlugin, "gemini", "GEMINI.md"),
            (GrokPlugin, "grok", "GROK.md"),
            (CursorPlugin, "cursor", ".cursorrules"),
            (GenericPlugin, "generic", "AGENTS.md"),
        ],
    )
    def test_slug_and_file_name(
        self,
        plugin_cls: type[AgentPlugin],
        slug: str,
        file_name: str,
    ) -> None:
        """Each plugin declares the expected slug and file_name."""
        caps = plugin_cls().capabilities()
        assert caps.slug == slug
        assert caps.file_name == file_name

    def test_claude_capabilities(self) -> None:
        """Claude plugin should report correct capabilities."""
        caps = ClaudePlugin().capabilities()
        assert caps.supports_xml is True
        assert caps.supports_mermaid is True
        assert caps.supports_file_refs is True
        assert caps.supports_yolo is True
        assert caps.max_context_tokens == 200_000
        assert caps.handoff_method == "file"
        assert caps.description != ""

    def test_gemini_capabilities(self) -> None:
        """Gemini plugin should report correct capabilities."""
        caps = GeminiPlugin().capabilities()
        assert caps.supports_xml is False
        assert caps.supports_mermaid is True
        assert caps.max_context_tokens == 1_000_000

    def test_grok_capabilities(self) -> None:
        """Grok plugin should report correct capabilities."""
        caps = GrokPlugin().capabilities()
        assert caps.supports_xml is False
        assert caps.supports_yolo is False
        assert caps.description != ""

    def test_cursor_capabilities(self) -> None:
        """Cursor plugin should report correct capabilities."""
        caps = CursorPlugin().capabilities()
        assert caps.file_extension == ".cursorrules"
        assert caps.supports_yolo is True
        assert caps.cli_command is None

    def test_generic_capabilities(self) -> None:
        """Generic plugin should report correct capabilities."""
        caps = GenericPlugin().capabilities()
        assert caps.supports_xml is False
        assert caps.supports_mermaid is False
        assert caps.supports_yolo is False

    @pytest.mark.parametrize(
        "plugin_cls",
        [ClaudePlugin, GeminiPlugin, GrokPlugin, CursorPlugin, GenericPlugin],
    )
    def test_all_capability_fields_present(self, plugin_cls: type[AgentPlugin]) -> None:
        """Every plugin must populate all AgentCapabilities fields."""
        caps = plugin_cls().capabilities()
        assert isinstance(caps, AgentCapabilities)
        assert caps.name
        assert caps.slug
        assert caps.file_extension
        assert caps.file_name
        assert isinstance(caps.supports_xml, bool)
        assert isinstance(caps.supports_mermaid, bool)
        assert isinstance(caps.supports_file_refs, bool)
        assert isinstance(caps.supports_yolo, bool)
        assert caps.max_context_tokens > 0
        assert caps.handoff_method in ("file", "stdin", "clipboard", "cli_arg")


# -- Context formatting tests -----------------------------------------------


class TestContextFormatting:
    """Tests for context formatting across all plugins."""

    @pytest.mark.parametrize(
        "plugin_cls",
        [ClaudePlugin, GeminiPlugin, GrokPlugin, CursorPlugin, GenericPlugin],
    )
    def test_format_context_includes_task(self, plugin_cls: type[AgentPlugin]) -> None:
        """All plugins must include the task in their output."""
        result = plugin_cls().format_context(
            task="Add rate limiting",
            plan=SAMPLE_PLAN,
            repo_map="src/api.py",
            memory=SAMPLE_MEMORY,
            token_budget=5000,
        )
        assert "Add rate limiting" in result

    @pytest.mark.parametrize(
        "plugin_cls",
        [ClaudePlugin, GeminiPlugin, GrokPlugin, CursorPlugin, GenericPlugin],
    )
    def test_format_context_returns_string(self, plugin_cls: type[AgentPlugin]) -> None:
        """All plugins must return a non-empty string."""
        result = plugin_cls().format_context(
            task="Test task",
            plan={},
            repo_map="",
            memory=[],
            token_budget=5000,
        )
        assert isinstance(result, str)
        assert len(result) > 0

    def test_claude_xml_structure(self) -> None:
        """Claude plugin should produce XML-tagged output."""
        result = ClaudePlugin().format_context(
            task="Add auth",
            plan=SAMPLE_PLAN,
            repo_map="src/auth.py",
            memory=SAMPLE_MEMORY,
            token_budget=5000,
        )
        assert "<plan>" in result
        assert "</plan>" in result
        assert "<repo_map>" in result
        assert "<memory>" in result

    def test_gemini_natural_language(self) -> None:
        """Gemini plugin should use numbered phases."""
        result = GeminiPlugin().format_context(
            task="Add auth",
            plan=SAMPLE_PLAN,
            repo_map="src/auth.py",
            memory=[],
            token_budget=5000,
        )
        assert "# Task" in result
        assert "Phase 1" in result

    def test_grok_includes_plan_steps(self) -> None:
        """Grok plugin should include step-numbered plan entries."""
        result = GrokPlugin().format_context(
            task="Add auth",
            plan=SAMPLE_PLAN,
            repo_map="",
            memory=[],
            token_budget=5000,
        )
        assert "Step 1" in result

    def test_cursor_directive_style(self) -> None:
        """Cursor plugin should produce directive-style output."""
        result = CursorPlugin().format_context(
            task="Add auth",
            plan=SAMPLE_PLAN,
            repo_map="",
            memory=[],
            token_budget=5000,
        )
        assert "Current Task" in result
        assert "Implementation Steps" in result

    def test_generic_plain_markdown(self) -> None:
        """Generic plugin should produce plain markdown."""
        result = GenericPlugin().format_context(
            task="Add auth",
            plan=SAMPLE_PLAN,
            repo_map="src/",
            memory=[],
            token_budget=5000,
        )
        assert "# Task" in result
        assert "# Plan" in result

    @pytest.mark.parametrize(
        "plugin_cls",
        [ClaudePlugin, GeminiPlugin, GrokPlugin, CursorPlugin, GenericPlugin],
    )
    def test_format_context_handles_empty_plan(self, plugin_cls: type[AgentPlugin]) -> None:
        """Plugins should handle empty plans gracefully."""
        result = plugin_cls().format_context(
            task="Task",
            plan={},
            repo_map="",
            memory=[],
            token_budget=5000,
        )
        assert "Task" in result


# -- Verification prompt tests ----------------------------------------------


class TestVerificationPrompt:
    """Tests for format_verification_prompt method."""

    def test_default_verification_prompt(self) -> None:
        """Default verification prompt includes plan and diff."""
        plugin = GenericPlugin()
        result = plugin.format_verification_prompt(
            diff="--- a/auth.py\n+++ b/auth.py\n+import jwt",
            plan=SAMPLE_PLAN,
        )
        assert "Verification Review" in result
        assert "Phase 1" in result
        assert "import jwt" in result
        assert "PASS" in result or "FAIL" in result

    def test_claude_verification_uses_xml(self) -> None:
        """Claude plugin overrides verification prompt with XML tags."""
        plugin = ClaudePlugin()
        result = plugin.format_verification_prompt(
            diff="some diff",
            plan=SAMPLE_PLAN,
        )
        assert "<verification>" in result or "<plan>" in result

    def test_verification_prompt_with_empty_plan(self) -> None:
        """Verification works with empty plan."""
        result = GenericPlugin().format_verification_prompt(
            diff="diff content",
            plan={},
        )
        assert "diff content" in result


# -- Handoff command tests --------------------------------------------------


class TestHandoffCommand:
    """Tests for handoff_command method."""

    def test_claude_handoff_command(self, tmp_path: Path) -> None:
        """Claude plugin should produce a CLI command."""
        plugin = ClaudePlugin()
        context_file = tmp_path / "CLAUDE.md"
        cmd = plugin.handoff_command(context_file)
        assert cmd is not None
        assert str(context_file) in cmd

    def test_gemini_handoff_command(self, tmp_path: Path) -> None:
        """Gemini plugin should produce a CLI command."""
        plugin = GeminiPlugin()
        context_file = tmp_path / "GEMINI.md"
        cmd = plugin.handoff_command(context_file)
        assert cmd is not None
        assert str(context_file) in cmd

    def test_generic_handoff_returns_none(self, tmp_path: Path) -> None:
        """Generic plugin with no CLI command returns None."""
        plugin = GenericPlugin()
        context_file = tmp_path / "AGENTS.md"
        cmd = plugin.handoff_command(context_file)
        assert cmd is None

    def test_cursor_handoff_returns_none(self, tmp_path: Path) -> None:
        """Cursor plugin has no CLI command."""
        plugin = CursorPlugin()
        cmd = plugin.handoff_command(tmp_path / ".cursorrules")
        assert cmd is None

    def test_grok_handoff_returns_none(self, tmp_path: Path) -> None:
        """Grok plugin has no CLI command."""
        plugin = GrokPlugin()
        cmd = plugin.handoff_command(tmp_path / "GROK.md")
        assert cmd is None


# -- Registry tests ---------------------------------------------------------


class TestAgentRegistry:
    """Tests for the agent registry."""

    def test_register_and_get(self) -> None:
        """Should register and retrieve plugins."""
        registry = AgentRegistry()
        registry.register(ClaudePlugin())
        plugin = registry.get("claude")
        assert plugin.capabilities().slug == "claude"

    def test_unknown_agent(self) -> None:
        """Should raise KeyError for unknown agents."""
        registry = AgentRegistry()
        with pytest.raises(KeyError, match="Unknown agent"):
            registry.get("nonexistent")

    def test_contains(self) -> None:
        """__contains__ should work."""
        registry = AgentRegistry()
        registry.register(ClaudePlugin())
        assert "claude" in registry
        assert "nonexistent" not in registry

    def test_default_registry_has_all_builtins(self) -> None:
        """Default registry should include all 5 built-in plugins."""
        registry = create_default_registry()
        assert "claude" in registry
        assert "gemini" in registry
        assert "grok" in registry
        assert "cursor" in registry
        assert "generic" in registry

    def test_list_agents_sorted(self) -> None:
        """list_agents returns sorted slugs."""
        registry = create_default_registry()
        agents = registry.list_agents()
        assert len(agents) >= 5
        assert agents == sorted(agents)

    def test_list_capabilities(self) -> None:
        """list_capabilities returns AgentCapabilities objects."""
        registry = create_default_registry()
        caps_list = registry.list_capabilities()
        assert len(caps_list) >= 5
        assert all(isinstance(c, AgentCapabilities) for c in caps_list)
        slugs = {c.slug for c in caps_list}
        assert "claude" in slugs
        assert "generic" in slugs

    def test_register_overwrites_existing(self) -> None:
        """Registering a plugin with the same slug replaces the old one."""
        registry = AgentRegistry()
        registry.register(GenericPlugin())
        registry.register(ClaudePlugin())
        # Now register another generic — should replace the original
        registry.register(GenericPlugin())
        assert "generic" in registry
        assert "claude" in registry


# -- Custom YAML agent tests ------------------------------------------------


class TestCustomAgentPlugin:
    """Tests for loading custom agents from YAML."""

    def test_load_custom_agent(self, tmp_path: Path) -> None:
        """Custom agent should load from a valid YAML file."""
        yaml_content = dedent("""\
            name: "Roo Code"
            slug: "roo-code"
            description: "Roo Code extension"
            file_name: "ROO.md"
            format: "generic"
            preferences:
              use_xml: false
              use_mermaid: true
              max_tokens: 64000
            handoff:
              method: "file"
              command: null
            templates:
              prepend: "You are Roo Code."
              append: "Done."
        """)
        yaml_path = tmp_path / "roo-code.yaml"
        yaml_path.write_text(yaml_content)

        from musonius.context.agents.custom import CustomAgentPlugin

        plugin = CustomAgentPlugin(yaml_path)
        caps = plugin.capabilities()

        assert caps.name == "Roo Code"
        assert caps.slug == "roo-code"
        assert caps.file_name == "ROO.md"
        assert caps.supports_xml is False
        assert caps.supports_mermaid is True
        assert caps.max_context_tokens == 64_000
        assert caps.description == "Roo Code extension"

    def test_custom_agent_format_with_templates(self, tmp_path: Path) -> None:
        """Custom agent applies prepend and append templates."""
        yaml_content = dedent("""\
            name: "Test Agent"
            slug: "test-agent"
            format: "generic"
            templates:
              prepend: "CUSTOM HEADER"
              append: "CUSTOM FOOTER"
        """)
        yaml_path = tmp_path / "test-agent.yaml"
        yaml_path.write_text(yaml_content)

        from musonius.context.agents.custom import CustomAgentPlugin

        plugin = CustomAgentPlugin(yaml_path)
        result = plugin.format_context(
            task="Test",
            plan={},
            repo_map="",
            memory=[],
            token_budget=5000,
        )
        assert result.startswith("CUSTOM HEADER")
        assert result.endswith("CUSTOM FOOTER")
        assert "Test" in result

    def test_custom_agent_missing_required_field(self, tmp_path: Path) -> None:
        """Should raise ValueError when required fields are missing."""
        yaml_content = "description: 'no name or slug'\n"
        yaml_path = tmp_path / "bad.yaml"
        yaml_path.write_text(yaml_content)

        from musonius.context.agents.custom import CustomAgentPlugin

        with pytest.raises(ValueError, match="Missing required field"):
            CustomAgentPlugin(yaml_path)

    def test_custom_agent_invalid_yaml(self, tmp_path: Path) -> None:
        """Should raise error for non-dict YAML content."""
        yaml_content = "- just\n- a\n- list\n"
        yaml_path = tmp_path / "list.yaml"
        yaml_path.write_text(yaml_content)

        from musonius.context.agents.custom import CustomAgentPlugin

        with pytest.raises(ValueError, match="Expected YAML dict"):
            CustomAgentPlugin(yaml_path)

    def test_custom_agent_defaults(self, tmp_path: Path) -> None:
        """Minimal YAML should produce sensible defaults."""
        yaml_content = 'name: "Minimal"\nslug: "minimal"\n'
        yaml_path = tmp_path / "minimal.yaml"
        yaml_path.write_text(yaml_content)

        from musonius.context.agents.custom import CustomAgentPlugin

        plugin = CustomAgentPlugin(yaml_path)
        caps = plugin.capabilities()
        assert caps.file_name == "AGENTS.md"
        assert caps.max_context_tokens == 128_000
        assert caps.handoff_method == "file"


# -- Full registry with YAML discovery tests --------------------------------


class TestFullRegistry:
    """Tests for create_full_registry with YAML agent discovery."""

    def test_full_registry_includes_builtins(self, tmp_path: Path) -> None:
        """Full registry should still include built-in plugins."""
        registry = create_full_registry(tmp_path)
        assert "claude" in registry
        assert "gemini" in registry
        assert "generic" in registry

    def test_full_registry_discovers_project_yaml(self, tmp_path: Path) -> None:
        """Full registry should discover YAML agents in project .musonius/agents/."""
        agents_dir = tmp_path / ".musonius" / "agents"
        agents_dir.mkdir(parents=True)
        yaml_content = dedent("""\
            name: "My Agent"
            slug: "my-agent"
            format: "generic"
        """)
        (agents_dir / "my-agent.yaml").write_text(yaml_content)

        registry = create_full_registry(tmp_path)
        assert "my-agent" in registry
        caps = registry.get("my-agent").capabilities()
        assert caps.name == "My Agent"

    def test_project_yaml_overrides_builtin(self, tmp_path: Path) -> None:
        """Project YAML agent with same slug should override built-in."""
        agents_dir = tmp_path / ".musonius" / "agents"
        agents_dir.mkdir(parents=True)
        yaml_content = dedent("""\
            name: "Custom Claude Override"
            slug: "claude"
            format: "generic"
        """)
        (agents_dir / "claude.yaml").write_text(yaml_content)

        registry = create_full_registry(tmp_path)
        assert "claude" in registry
        caps = registry.get("claude").capabilities()
        assert caps.name == "Custom Claude Override"

    def test_full_registry_handles_no_yaml_dir(self, tmp_path: Path) -> None:
        """Full registry should work when no .musonius/agents/ directory exists."""
        registry = create_full_registry(tmp_path)
        # Should still have builtins
        assert len(registry.list_agents()) >= 5

    def test_full_registry_skips_bad_yaml(self, tmp_path: Path) -> None:
        """Full registry should skip malformed YAML files without crashing."""
        agents_dir = tmp_path / ".musonius" / "agents"
        agents_dir.mkdir(parents=True)

        # Bad YAML (missing required fields)
        (agents_dir / "bad.yaml").write_text("not_a_name: true\n")

        # Good YAML
        good_yaml = dedent("""\
            name: "Good Agent"
            slug: "good-agent"
            format: "generic"
        """)
        (agents_dir / "good-agent.yaml").write_text(good_yaml)

        registry = create_full_registry(tmp_path)
        assert "good-agent" in registry
        # Bad one should be skipped
        assert "not_a_name" not in registry.list_agents()
