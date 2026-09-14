"""Professor account recovery from the host shell (AUTH-01, docs/runbooks/break-glass.md).

Registered in app.cli as `breakglass`, so both spellings in the documentation work:

    python -m app.cli breakglass recover-professor --email <address>
    python -m app.identity.breakglass recover-professor --email <address>

There is no API route to any of this by design: it requires shell access to the host and the
`infra/.env` file, and every use writes an `audit_events` row with `actor_kind = system`.

Professors are co-equal over students but cannot demote, deactivate, or remove each other through
the API (ADR 0011), so ejecting a colleague lives here too. Every command that could reduce the
professor count refuses to leave the workspace without one.
"""

from __future__ import annotations

import typer

from app.core.config import get_settings
from app.core.db import run_in_session
from app.identity import service

cli = typer.Typer(no_args_is_help=True, help="Professor account recovery (break-glass)")


def _print_link(path: str, token: str, expires_at: object) -> None:
    settings = get_settings()
    typer.echo(f"recovery link (valid until {expires_at}, single use):")
    typer.echo(f"  {settings.public_url}{path}?token={token}")
    typer.echo("Hand it over through a different channel from the one used to request it.")


@cli.command("recover-professor")
def recover_professor(
    email: str = typer.Option(..., "--email", help="The professor account to restore"),
) -> None:
    """Restore professor access and print a single-use recovery link."""
    link = run_in_session(lambda session: service.recover_professor(session, email=email))
    _print_link("/reset-password", link.token, link.expires_at)


@cli.command("transfer-professor")
def transfer_professor(
    from_email: str = typer.Option(..., "--from", help="The outgoing professor"),
    to_email: str = typer.Option(..., "--to", help="The incoming professor"),
    display_name: str | None = typer.Option(None, "--name", help="Name for a new account"),
) -> None:
    """Hand the workspace to another person; the outgoing account is deactivated."""
    link = run_in_session(
        lambda session: service.transfer_professor(
            session, from_email=from_email, to_email=to_email, display_name=display_name
        )
    )
    typer.echo(f"{from_email} deactivated; {to_email} is now the professor.")
    _print_link("/reset-password", link.token, link.expires_at)


@cli.command("demote-professor")
def demote_professor(
    email: str = typer.Option(..., "--email", help="The professor to return to the student role"),
) -> None:
    """Return a professor to the student role. Refused if they are the only one left."""
    user = run_in_session(lambda session: service.demote_professor(session, email=email))
    typer.echo(f"{user.email} is now a student.")


@cli.command("deactivate-professor")
def deactivate_professor(
    email: str = typer.Option(..., "--email", help="The professor account to close"),
) -> None:
    """Close a professor account. Refused if they are the only one left."""
    user = run_in_session(lambda session: service.deactivate_professor(session, email=email))
    typer.echo(f"{user.email} is deactivated; every session is revoked.")


if __name__ == "__main__":
    cli()
