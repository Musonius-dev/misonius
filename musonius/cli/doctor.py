"""musonius doctor — system health check and environment diagnostics."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from rich.panel import Panel
from rich.table import Table

from musonius.cli.utils import console, handle_errors

logger = logging.getLogger(__name__)


@handle_errors
def doctor_command() -> None:
    """Run system health checks and environment diagnostics.

    Validates Python version, dependencies, API keys, git setup,
    project initialization state, and model availability.
    """
    console.print(Panel("Musonius Doctor", subtitle="System Health Check", border_style="blue"))

    checks: list[tuple[str, str, str]] = []

    # 1. Python version
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 10):
        checks.append(("Python", f"[green]{py_version}[/green]", ""))
    else:
        checks.append(("Python", f"[red]{py_version}[/red]", "Requires 3.10+"))

    # 2. Virtual environment
    in_venv = sys.prefix != sys.base_prefix
    if in_venv:
        checks.append(("Virtual env", "[green]Active[/green]", sys.prefix))
    else:
        checks.append(("Virtual env", "[yellow]Not active[/yellow]", "Recommended: source .venv/bin/activate"))

    # 3. Core dependencies
    _check_dependencies(checks)

    # 4. Git
    git_path = shutil.which("git")
    if git_path:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                capture_output=True,
                text=True,
                cwd=Path.cwd(),
            )
            if result.returncode == 0:
                checks.append(("Git", "[green]Repository found[/green]", ""))
            else:
                checks.append(("Git", "[yellow]Installed but not a repo[/yellow]", "Run git init"))
        except Exception:
            checks.append(("Git", "[yellow]Installed[/yellow]", "Not in a git directory"))
    else:
        checks.append(("Git", "[red]Not found[/red]", "Install git"))

    # 5. API keys
    _check_api_keys(checks)

    # 6. Project initialization
    _check_project_state(checks)

    # 7. Optional tools
    _check_optional_tools(checks)

    # Display results
    table = Table(show_header=True, title="Health Checks")
    table.add_column("Check", style="cyan", min_width=20)
    table.add_column("Status", min_width=25)
    table.add_column("Notes", style="dim")

    passed = 0
    warnings = 0
    failed = 0

    for name, status, notes in checks:
        table.add_row(name, status, notes)
        if "[green]" in status:
            passed += 1
        elif "[yellow]" in status:
            warnings += 1
        else:
            failed += 1

    console.print(table)

    # Summary
    console.print()
    if failed == 0 and warnings == 0:
        console.print("[bold green]All checks passed![/bold green]")
    elif failed == 0:
        console.print(
            f"[bold green]{passed} passed[/bold green], "
            f"[bold yellow]{warnings} warnings[/bold yellow]"
        )
    else:
        console.print(
            f"[bold green]{passed} passed[/bold green], "
            f"[bold yellow]{warnings} warnings[/bold yellow], "
            f"[bold red]{failed} failed[/bold red]"
        )

    # Recommendations
    _print_recommendations(checks)


def _check_dependencies(checks: list[tuple[str, str, str]]) -> None:
    """Check core Python dependencies."""
    deps = {
        "typer": "CLI framework",
        "rich": "Terminal UI",
        "tree_sitter": "AST parsing",
        "litellm": "LLM routing",
        "pydantic": "Data models",
        "yaml": "Config files (pyyaml)",
        "git": "Git operations (gitpython)",
    }

    missing: list[str] = []
    for module, description in deps.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(f"{module} ({description})")

    if not missing:
        checks.append(("Dependencies", "[green]All installed[/green]", f"{len(deps)} packages"))
    else:
        checks.append((
            "Dependencies",
            f"[red]Missing {len(missing)}[/red]",
            ", ".join(missing),
        ))


def _check_api_keys(checks: list[tuple[str, str, str]]) -> None:
    """Check for configured API keys."""
    keys = {
        "GEMINI_API_KEY": "Gemini (free scout/verifier)",
        "GOOGLE_API_KEY": "Google AI (alternative)",
        "ANTHROPIC_API_KEY": "Anthropic (planner)",
        "OPENAI_API_KEY": "OpenAI (alternative)",
    }

    found: list[str] = []
    for env_var, description in keys.items():
        value = os.environ.get(env_var, "")
        if value:
            # Mask the key for display
            masked = value[:4] + "..." + value[-4:] if len(value) > 8 else "***"
            found.append(f"{description} ({masked})")

    if found:
        checks.append(("API keys", f"[green]{len(found)} configured[/green]", "; ".join(found)))
    else:
        checks.append((
            "API keys",
            "[yellow]None found[/yellow]",
            "init/prep/memory work without keys; plan/verify need at least one",
        ))


def _check_project_state(checks: list[tuple[str, str, str]]) -> None:
    """Check Musonius project initialization state."""
    project_root = Path.cwd()
    musonius_dir = project_root / ".musonius"

    if not musonius_dir.exists():
        checks.append(("Project", "[yellow]Not initialized[/yellow]", "Run: musonius init"))
        return

    # Check individual components
    components = []

    # Index
    index_dir = musonius_dir / "index"
    if index_dir.exists() and any(index_dir.iterdir()):
        components.append("index")

    # Memory
    db_path = musonius_dir / "memory" / "decisions.db"
    if db_path.exists():
        components.append("memory")

    # Config
    config_path = musonius_dir / "config.yaml"
    if config_path.exists():
        components.append("config")

    # Epics
    epics_dir = musonius_dir / "epics"
    if epics_dir.exists():
        epic_count = len([d for d in epics_dir.iterdir() if d.is_dir()])
        if epic_count > 0:
            components.append(f"{epic_count} epics")

    # SOT
    sot_dir = musonius_dir / "sot"
    if sot_dir.exists():
        sot_count = len(list(sot_dir.glob("*.md")))
        if sot_count > 0:
            components.append(f"{sot_count} SOT docs")

    if components:
        checks.append((
            "Project",
            "[green]Initialized[/green]",
            ", ".join(components),
        ))
    else:
        checks.append(("Project", "[yellow]Partially initialized[/yellow]", "Re-run: musonius init"))


def _check_optional_tools(checks: list[tuple[str, str, str]]) -> None:
    """Check optional but recommended tools."""
    # ruff
    if shutil.which("ruff"):
        checks.append(("Linter (ruff)", "[green]Available[/green]", ""))
    else:
        checks.append(("Linter (ruff)", "[yellow]Not found[/yellow]", "pip install ruff"))

    # gh CLI
    if shutil.which("gh"):
        checks.append(("GitHub CLI (gh)", "[green]Available[/green]", ""))
    else:
        checks.append(("GitHub CLI (gh)", "[dim]Not found[/dim]", "Optional: --from-issue support"))

    # Ollama (local models)
    if shutil.which("ollama"):
        checks.append(("Ollama", "[green]Available[/green]", "Local model support"))
    else:
        checks.append(("Ollama", "[dim]Not found[/dim]", "Optional: offline model support"))


def _print_recommendations(checks: list[tuple[str, str, str]]) -> None:
    """Print actionable recommendations based on check results."""
    recs: list[str] = []

    for name, status, notes in checks:
        if "[red]" in status:
            if "Python" in name:
                recs.append("Install Python 3.10+: brew install python@3.12")
            elif "Dependencies" in name:
                recs.append("Install dependencies: pip install -e .")
            elif "Git" in name:
                recs.append("Install git: brew install git")
        elif "[yellow]" in status:
            if "API keys" in name:
                recs.append(
                    "Get a free Gemini key: https://aistudio.google.com\n"
                    "     Then: export GEMINI_API_KEY=your-key"
                )
            elif "Not initialized" in status:
                recs.append("Initialize project: musonius init")
            elif "Virtual env" in name:
                recs.append("Activate venv: source .venv/bin/activate")

    if recs:
        console.print("\n[bold]Recommendations:[/bold]")
        for i, rec in enumerate(recs, 1):
            console.print(f"  {i}. {rec}")
