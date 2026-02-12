"""musonius review — code review mode for PRs and diffs."""

from __future__ import annotations

import logging
import subprocess

import typer
from rich.panel import Panel
from rich.table import Table

from musonius.cli.utils import console, handle_errors, require_initialized

logger = logging.getLogger(__name__)


@handle_errors
def review_command(
    target: str = typer.Argument(
        None, help="Branch, commit, or PR to review (default: current changes)."
    ),
    reviewer: str = typer.Option("gemini", "--reviewer", "-r", help="Reviewer model."),
    focus: str | None = typer.Option(
        None, "--focus", "-f", help="Focus area: security, performance, style, tests."
    ),
) -> None:
    """Review code changes with cross-model analysis.

    Reviews the diff between the current branch and target, or reviews
    staged/unstaged changes if no target is specified.
    """
    project_root = require_initialized()

    # Build the diff command
    if target:
        diff_cmd = ["git", "diff", f"{target}...HEAD"]
        console.print(Panel(f"Reviewing changes vs [bold]{target}[/bold]", border_style="blue"))
    else:
        diff_cmd = ["git", "diff", "HEAD"]
        console.print(Panel("Reviewing current changes", border_style="blue"))

    try:
        result = subprocess.run(
            diff_cmd,
            capture_output=True,
            text=True,
            cwd=project_root,
            check=True,
        )
        diff = result.stdout
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Failed to get diff:[/red] {e.stderr or e}")
        raise typer.Exit(1) from e

    if not diff.strip():
        console.print("[yellow]No changes to review.[/yellow]")
        return

    # Parse diff for summary
    from musonius.verification.diff_analyzer import DiffAnalyzer

    analyzer = DiffAnalyzer(project_root)
    diff_files = analyzer.extract_changes(diff)
    console.print(f"\n[bold]Files changed:[/bold] {len(diff_files)}")
    for df in diff_files:
        console.print(f"  {df.file_path}: [green]+{df.added_count}[/green] [red]-{df.removed_count}[/red]")

    # Try LLM-powered review
    try:
        from musonius.config.loader import load_config
        from musonius.orchestration.router import ModelRouter

        config = load_config(project_root)
        router = ModelRouter(config)

        review_prompt = _build_review_prompt(diff, focus)
        response = router.call_verifier(
            [
                {"role": "system", "content": _review_system_prompt(focus)},
                {"role": "user", "content": review_prompt},
            ]
        )

        console.print(Panel(response.content, title="Review", border_style="green"))
        console.print(
            f"[dim]Model: {response.model} | "
            f"Tokens: {response.prompt_tokens + response.completion_tokens:,}[/dim]"
        )

    except Exception as e:
        logger.debug("LLM review failed: %s", e)
        console.print(f"[yellow]LLM review unavailable:[/yellow] {e}")
        console.print("[dim]Tip: Configure your API keys to enable AI-powered reviews.[/dim]")

        # Fall back to heuristic review
        from musonius.verification.engine import VerificationEngine

        engine = VerificationEngine()
        verification = engine.verify_diff(diff=diff, plan={}, use_llm=False)

        if verification.findings:
            table = Table(title="Heuristic Findings", show_header=True)
            table.add_column("Severity")
            table.add_column("Category")
            table.add_column("Message")
            table.add_column("File")

            for finding in verification.findings:
                table.add_row(
                    finding.severity.value,
                    finding.category,
                    finding.message,
                    finding.file_path or "-",
                )
            console.print(table)


def _review_system_prompt(focus: str | None) -> str:
    """Build the system prompt for code review."""
    base = (
        "You are an expert code reviewer. Analyze the diff and provide a thorough review. "
        "Be constructive, specific, and actionable. Highlight both issues and good practices."
    )
    if focus:
        return f"{base}\n\nFocus especially on: {focus}"
    return base


def _build_review_prompt(diff: str, focus: str | None) -> str:
    """Build the user prompt for code review."""
    truncated = diff[:15_000] if len(diff) > 15_000 else diff
    prompt = f"```diff\n{truncated}\n```\n\n"
    prompt += "Please review this code change. For each issue found, specify:\n"
    prompt += "1. The file and approximate location\n"
    prompt += "2. The severity (critical/major/minor/info)\n"
    prompt += "3. A clear description of the issue\n"
    prompt += "4. A suggested fix\n"
    if focus:
        prompt += f"\nPay special attention to: {focus}"
    return prompt
