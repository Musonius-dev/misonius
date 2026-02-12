"""CLI command: musonius serve — start the MCP server."""

from __future__ import annotations

import typer
from rich.console import Console

console = Console()


def serve_command(
    transport: str = typer.Option(
        "stdio",
        "--transport",
        "-t",
        help="Transport protocol: stdio (default) or sse.",
    ),
    port: int = typer.Option(
        8000,
        "--port",
        "-p",
        help="Port for SSE transport (ignored for stdio).",
    ),
) -> None:
    """Start the Musonius MCP server.

    Exposes 6 tools via MCP: get_plan, get_context, verify,
    memory_query, record_decision, and status. Any MCP-compatible
    client (Claude Code, Cursor, VS Code) can connect.

    \b
    Usage in Claude Code's config:
      {
        "mcpServers": {
          "musonius": {
            "command": "musonius",
            "args": ["serve"]
          }
        }
      }
    """
    from musonius.mcp.server import mcp

    if transport == "stdio":
        console.print("[bold green]Starting Musonius MCP server (stdio)...[/]")
        console.print("Tools: get_plan, get_context, verify, memory_query, record_decision, status")
        mcp.run(transport="stdio")
    elif transport == "sse":
        console.print(f"[bold green]Starting Musonius MCP server (SSE on port {port})...[/]")
        mcp.run(transport="sse", sse_params={"port": port})
    else:
        console.print(f"[bold red]Unknown transport: {transport}[/]")
        raise typer.Exit(code=1)
