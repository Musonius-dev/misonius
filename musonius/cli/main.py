"""Musonius CLI — main entry point."""

from __future__ import annotations

import typer
from rich.console import Console

from musonius import __version__

app = typer.Typer(
    name="musonius",
    help="Spec-driven development orchestrator — the AI coding multiplier.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()


def version_callback(value: bool) -> None:
    """Print version and exit."""
    if value:
        console.print(f"musonius {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
    debug: bool = typer.Option(False, "--debug", help="Enable debug output."),
) -> None:
    """Musonius — stop burning tokens on exploration."""
    if debug:
        import logging

        logging.basicConfig(level=logging.DEBUG)


# Import and register subcommands
from musonius.cli.agents import agents_app  # noqa: E402
from musonius.cli.doctor import doctor_command  # noqa: E402
from musonius.cli.go import go_command  # noqa: E402
from musonius.cli.history import history_app  # noqa: E402
from musonius.cli.init import init_command  # noqa: E402
from musonius.cli.memory import memory_app  # noqa: E402
from musonius.cli.plan import plan_command  # noqa: E402
from musonius.cli.prep import prep_command  # noqa: E402
from musonius.cli.review import review_command  # noqa: E402
from musonius.cli.rollback import rollback_command  # noqa: E402
from musonius.cli.run import run_command  # noqa: E402
from musonius.cli.serve import serve_command  # noqa: E402
from musonius.cli.status import status_command  # noqa: E402
from musonius.cli.verify import verify_command  # noqa: E402

app.command(name="init")(init_command)
app.command(name="doctor")(doctor_command)
app.command(name="go")(go_command)
app.command(name="plan")(plan_command)
app.command(name="prep")(prep_command)
app.command(name="run")(run_command)
app.command(name="verify")(verify_command)
app.command(name="review")(review_command)
app.command(name="rollback")(rollback_command)
app.command(name="serve")(serve_command)
app.command(name="status")(status_command)
app.add_typer(memory_app, name="memory")
app.add_typer(history_app, name="history")
app.add_typer(agents_app, name="agents")
