"""musonius verify — cross-model adversarial review of changes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import typer
from rich.table import Table
from rich.tree import Tree

from musonius.cli.utils import console, handle_errors, require_initialized
from musonius.verification.linter import LintFinding
from musonius.verification.severity import Severity

logger = logging.getLogger(__name__)


@handle_errors
def verify_command(
    reviewer: str = typer.Option("gemini", "--reviewer", "-r", help="Reviewer model."),
    staged: bool = typer.Option(False, "--staged", help="Only verify staged changes."),
    epic: str | None = typer.Option(None, "--epic", "-e", help="Epic ID to verify against."),
    phase: str | None = typer.Option(None, "--phase", "-p", help="Phase to verify (e.g. '2')."),
    no_llm: bool = typer.Option(False, "--no-llm", help="Skip LLM-based analysis."),
    fix: bool = typer.Option(False, "--fix", help="Generate fix suggestions for findings."),
    against: str | None = typer.Option(None, "--against", help="Verify against specific commit."),
    severity_filter: str | None = typer.Option(
        None,
        "--severity",
        "-s",
        help="Show only findings of given severity (comma-separated, e.g. 'critical,major').",
    ),
) -> None:
    """Verify current changes against the active plan.

    Captures git diff, runs linters, performs cross-model adversarial review,
    and reports severity-categorized findings.
    """
    project_root = require_initialized()

    console.print(f"Verifying with [bold]{reviewer}[/bold]...")

    # Load plan for comparison
    plan = _load_plan_for_verify(project_root, epic, phase)

    # Build severity filter set
    allowed_severities: set[str] | None = None
    if severity_filter:
        allowed_severities = {s.strip().lower() for s in severity_filter.split(",")}

    # Set up router for LLM-based verification
    router = None
    if not no_llm:
        try:
            from musonius.config.loader import load_config
            from musonius.orchestration.router import ModelRouter

            config = load_config(project_root)
            router = ModelRouter(config)
        except Exception as e:
            logger.debug("Router setup failed, skipping LLM verify: %s", e)

    # Set up memory store
    memory = None
    try:
        from musonius.memory.store import MemoryStore

        db_path = project_root / ".musonius" / "memory" / "decisions.db"
        memory = MemoryStore(db_path)
        memory.initialize()
    except Exception as e:
        logger.debug("Memory setup failed: %s", e)

    from musonius.verification.engine import VerificationEngine

    engine = VerificationEngine(
        router=router,
        memory=memory,
        repo_path=project_root,
    )

    base = against or "HEAD"
    verification = engine.verify(
        epic_id=epic or "",
        phase_id=phase or "",
        base=base,
        staged=staged,
        auto_fix=fix,
        use_llm=not no_llm,
        plan=plan,
    )

    _display_findings(verification, allowed_severities)

    if memory:
        memory.close()


def _load_plan_for_verify(
    project_root: Path, epic_id: str | None, phase_id: str | None
) -> dict[str, Any]:
    """Load the plan to verify against."""
    epics_dir = project_root / ".musonius" / "epics"
    if not epics_dir.exists():
        return {}

    epic_dir: Path | None = None
    if epic_id:
        candidate = epics_dir / epic_id
        if candidate.is_dir():
            epic_dir = candidate
        else:
            matches = [d for d in epics_dir.iterdir() if d.is_dir() and epic_id in d.name]
            epic_dir = matches[0] if matches else None
    else:
        epic_dirs = sorted(
            [d for d in epics_dir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        epic_dir = epic_dirs[0] if epic_dirs else None

    if not epic_dir:
        return {}

    phases_dir = epic_dir / "phases"
    phases: list[dict[str, Any]] = []
    if phases_dir.exists():
        pattern = f"phase-{phase_id.zfill(2)}*.md" if phase_id else "phase-*.md"
        for phase_file in sorted(phases_dir.glob(pattern)):
            content = phase_file.read_text()
            lines = content.split("\n")
            title = lines[0].lstrip("# ").strip() if lines else "Untitled"
            phases.append({"title": title, "description": "\n".join(lines[1:]).strip()})

    return {"phases": phases}


def _display_findings(
    result: Any, allowed_severities: set[str] | None = None
) -> None:
    """Display verification findings in tree format matching the spec output."""
    from musonius.verification.engine import VerificationResult

    if not isinstance(result, VerificationResult):
        return

    # Title
    title_parts = ["Verification Results"]
    if result.epic_id:
        title_parts.append(result.epic_id)
    if result.phase_id:
        title_parts.append(f"phase-{result.phase_id}")
    title = " / ".join(title_parts)

    if result.diff_summary:
        console.print(f"\n[dim]{result.diff_summary}[/dim]\n")

    if not result.findings and not result.lint_results:
        console.print("[green]No findings — all changes look good.[/green]")
        return

    # Group findings by severity
    severity_order = [Severity.CRITICAL, Severity.MAJOR, Severity.MINOR, Severity.OUTDATED, Severity.INFO]
    severity_styles = {
        Severity.CRITICAL: ("red", "CRITICAL"),
        Severity.MAJOR: ("yellow", "MAJOR"),
        Severity.MINOR: ("cyan", "MINOR"),
        Severity.OUTDATED: ("dim", "OUTDATED"),
        Severity.INFO: ("dim", "INFO"),
    }

    # Filter findings
    filtered = result.findings
    if allowed_severities:
        filtered = [f for f in filtered if f.severity.value in allowed_severities]

    if not filtered and not result.lint_results:
        console.print("[dim]No findings match the severity filter.[/dim]")
        return

    # Build tree output
    root_tree = Tree(f"[bold]{title}[/bold]")

    for sev in severity_order:
        sev_findings = [f for f in filtered if f.severity == sev]
        if not sev_findings:
            continue

        style, label = severity_styles[sev]
        sev_branch = root_tree.add(
            f"[{style} bold]{label}[/{style} bold] ({len(sev_findings)})"
        )

        for finding in sev_findings:
            location = finding.file_path or ""
            if finding.line_number:
                location += f":{finding.line_number}"

            if location:
                finding_branch = sev_branch.add(f"[{style}]{location}[/{style}]")
            else:
                finding_branch = sev_branch

            finding_branch.add(f"[dim]{finding.message}[/dim]")

            if finding.plan_reference:
                finding_branch.add(f"[dim italic]Plan: {finding.plan_reference}[/dim italic]")

    console.print(root_tree)

    # Display lint results summary
    if result.lint_results:
        _display_lint_summary(result.lint_results)

    # Display fix suggestions
    if result.fix_suggestions:
        _display_fix_suggestions(result)

    # Summary line
    status = "[green]PASSED[/green]" if result.passed else "[red]FAILED[/red]"
    counts = []
    if result.critical_count:
        counts.append(f"{result.critical_count} critical")
    if result.major_count:
        counts.append(f"{result.major_count} major")
    if result.minor_count:
        counts.append(f"{result.minor_count} minor")
    if result.outdated_count:
        counts.append(f"{result.outdated_count} outdated")

    summary_text = ", ".join(counts) if counts else "0"
    console.print(f"\nSummary: {summary_text} findings")
    console.print(f"Status: {status}")


def _display_lint_summary(lint_results: list[LintFinding]) -> None:
    """Display a summary of lint results."""
    errors = sum(1 for lr in lint_results if lr.severity == "error")
    warnings = sum(1 for lr in lint_results if lr.severity == "warning")
    info = len(lint_results) - errors - warnings

    parts: list[str] = []
    if errors:
        parts.append(f"{errors} errors")
    if warnings:
        parts.append(f"{warnings} warnings")
    if info:
        parts.append(f"{info} info")

    linters_used = sorted({lr.linter for lr in lint_results})
    console.print(
        f"\n[dim]Lint Results ({', '.join(parts)}) from {', '.join(linters_used)}[/dim]"
    )


def _display_fix_suggestions(result: Any) -> None:
    """Display fix suggestions in a table."""
    from musonius.verification.engine import VerificationResult

    if not isinstance(result, VerificationResult) or not result.fix_suggestions:
        return

    table = Table(title="Fix Suggestions", show_header=True)
    table.add_column("#", style="bold", width=4)
    table.add_column("Description")
    table.add_column("Confidence", width=12)

    for i, suggestion in enumerate(result.fix_suggestions, 1):
        conf_pct = f"{suggestion.confidence * 100:.0f}%"
        table.add_row(str(i), suggestion.description, conf_pct)

    console.print()
    console.print(table)
