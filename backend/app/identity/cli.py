"""Operator commands for the identity module, registered in app.cli as `identity`."""

from __future__ import annotations

import typer

from app.core.config import get_settings
from app.core.db import run_in_session
from app.identity import service

cli = typer.Typer(no_args_is_help=True, help="Workspace and account commands")


@cli.command("bootstrap")
def bootstrap(
    name: str = typer.Option(..., "--name", help="Workspace name, for example 'Vision Lab'"),
    email: str = typer.Option(..., "--email", help="The professor's email address"),
    display_name: str = typer.Option(..., "--display-name", help="The professor's name"),
    timezone: str = typer.Option("Asia/Ho_Chi_Minh", "--timezone", help="Workspace timezone"),
) -> None:
    """Create the workspace and its professor. Run once, on the first deploy."""
    result = run_in_session(
        lambda session: service.bootstrap_workspace(
            session,
            name=name,
            prof_email=email,
            prof_display_name=display_name,
            timezone=timezone,
        )
    )
    typer.echo(f"workspace {result.workspace.name} created ({result.workspace.id})")
    typer.echo(f"invitation for {result.user.email}, valid for 7 days, single use:")
    typer.echo(f"  {get_settings().public_url}/accept-invitation?token={result.token}")
