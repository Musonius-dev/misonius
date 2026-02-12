"""musonius agents — list, inspect, and manage agent plugins."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import typer
from rich.table import Table

from musonius.cli.utils import console, find_project_root, handle_errors

if TYPE_CHECKING:
    from musonius.context.agents.registry import AgentRegistry

logger = logging.getLogger(__name__)

agents_app = typer.Typer(help="List and manage agent plugins.")


def _get_registry() -> AgentRegistry:
    """Create a full registry including custom YAML agents."""
    from musonius.context.agents.registry import create_full_registry

    try:
        project_root = find_project_root()
    except typer.Exit:
        project_root = Path.cwd()

    return create_full_registry(project_root)


@agents_app.command(name="list")
@handle_errors
def agents_list() -> None:
    """List all available agent plugins and their capabilities."""
    registry = _get_registry()
    slugs = registry.list_agents()

    table = Table(title="Available Agent Plugins", show_header=True)
    table.add_column("Slug", style="cyan")
    table.add_column("Name")
    table.add_column("Description", style="dim")
    table.add_column("Output File")
    table.add_column("Tokens", justify="right")
    table.add_column("XML", justify="center")
    table.add_column("YOLO", justify="center")
    table.add_column("Handoff")
    table.add_column("CLI", style="dim")

    yes = "[green]Yes[/green]"
    no = "[dim]No[/dim]"

    for slug in slugs:
        plugin = registry.get(slug)
        caps = plugin.capabilities()
        table.add_row(
            caps.slug,
            caps.name,
            caps.description,
            caps.file_name,
            f"{caps.max_context_tokens:,}",
            yes if caps.supports_xml else no,
            yes if caps.supports_yolo else no,
            caps.handoff_method,
            caps.cli_command or "-",
        )

    console.print(table)


@agents_app.command(name="info")
@handle_errors
def agents_info(
    agent: str = typer.Argument(..., help="Agent slug to show details for."),
) -> None:
    """Show detailed information about a specific agent plugin."""
    registry = _get_registry()

    try:
        plugin = registry.get(agent)
    except KeyError:
        console.print(f"[red]Unknown agent:[/red] {agent}")
        console.print(f"[dim]Available: {', '.join(registry.list_agents())}[/dim]")
        raise typer.Exit(1) from None

    caps = plugin.capabilities()

    console.print(f"\n[bold]{caps.name}[/bold] ({caps.slug})")
    console.print(f"  Description: {caps.description}")
    console.print(f"  Output file: {caps.file_name}")
    console.print(f"  File extension: {caps.file_extension}")
    console.print(f"  Max context tokens: {caps.max_context_tokens:,}")
    console.print(f"  Supports XML: {'Yes' if caps.supports_xml else 'No'}")
    console.print(f"  Supports Mermaid: {'Yes' if caps.supports_mermaid else 'No'}")
    console.print(f"  Supports file refs: {'Yes' if caps.supports_file_refs else 'No'}")
    console.print(f"  Autonomous mode: {'Yes' if caps.supports_yolo else 'No'}")
    console.print(f"  Handoff method: {caps.handoff_method}")
    console.print(f"  CLI command: {caps.cli_command or 'N/A'}")

    # Show a sample output
    console.print("\n[bold]Sample output format:[/bold]")
    sample = plugin.format_context(
        task="Example task",
        plan={"phases": [{"title": "Phase 1", "description": "Do the thing", "files": []}]},
        repo_map="(repo map would appear here)",
        memory=[{"summary": "Example decision", "rationale": "Because reasons"}],
        token_budget=1000,
    )
    console.print(f"\n[dim]{sample[:500]}{'...' if len(sample) > 500 else ''}[/dim]")


@agents_app.command(name="add")
@handle_errors
def agents_add(
    name: str = typer.Option(..., "--name", "-n", prompt="Agent name", help="Agent display name."),
    slug: str = typer.Option(
        ..., "--slug", "-s", prompt="Agent slug (short identifier)", help="Agent slug."
    ),
    description: str = typer.Option(
        "", "--description", "-d", prompt="Description (optional)", help="Agent description."
    ),
    base_format: str = typer.Option(
        "generic",
        "--format",
        "-f",
        prompt="Base format (claude/gemini/generic)",
        help="Base format plugin to inherit from.",
    ),
    max_tokens: int = typer.Option(
        128_000, "--max-tokens", prompt="Max context tokens", help="Context window size."
    ),
    project: bool = typer.Option(
        True,
        "--project/--user",
        help="Save to project (.musonius/agents/) or user (~/.musonius/agents/).",
    ),
) -> None:
    """Add a new custom agent via YAML definition.

    Creates a YAML agent file in .musonius/agents/ (project) or
    ~/.musonius/agents/ (user). The agent inherits formatting from
    the specified base format and can be customized with templates.
    """
    import yaml

    if project:
        agents_dir = find_project_root() / ".musonius" / "agents"
    else:
        agents_dir = Path.home() / ".musonius" / "agents"

    agents_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = agents_dir / f"{slug}.yaml"

    if yaml_path.exists():
        console.print(f"[yellow]Warning:[/yellow] {yaml_path} already exists.")
        overwrite = typer.confirm("Overwrite?", default=False)
        if not overwrite:
            raise typer.Exit(0)

    config = {
        "name": name,
        "slug": slug,
        "description": description or f"Custom agent: {name}",
        "file_name": "AGENTS.md",
        "format": base_format,
        "preferences": {
            "use_xml": base_format == "claude",
            "use_mermaid": base_format in ("claude", "gemini"),
            "max_tokens": max_tokens,
        },
        "handoff": {
            "method": "file",
            "command": None,
        },
        "templates": {
            "prepend": "",
            "append": "",
        },
    }

    yaml_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    console.print(f"[green]Created agent definition:[/green] {yaml_path}")
    console.print("  Edit the file to customize templates and preferences.")
    console.print(f"  Use [bold]musonius agents info {slug}[/bold] to verify.")
