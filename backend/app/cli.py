"""Operator command line.  Run:  python -m app.cli --help

Modules add their own sub-apps here (identity: breakglass, projects/reporting: seed).
"""

from __future__ import annotations

import typer

from app.core.config import get_settings
from app.identity.breakglass import cli as breakglass_cli
from app.identity.cli import cli as identity_cli
from app.notifications.cli import cli as notifications_cli
from app.seed import cli as seed_cli

cli = typer.Typer(no_args_is_help=True, help="Research Management System operator commands")
cli.add_typer(identity_cli, name="identity")
cli.add_typer(breakglass_cli, name="breakglass")
cli.add_typer(seed_cli, name="seed")
cli.add_typer(notifications_cli, name="notifications")


@cli.command()
def info() -> None:
    """Print the effective configuration with secrets masked."""
    settings = get_settings()
    for key, value in settings.masked().items():
        typer.echo(f"{key}={value}")


if __name__ == "__main__":
    cli()
