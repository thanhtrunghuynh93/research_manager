"""The operator commands the runbooks tell people to type must exist under those exact names.

docs/runbooks/break-glass.md is followed by a person under pressure; a renamed command or option is
an outage in that moment. These checks parse the command line only and touch no database.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from app.cli import cli

runner = CliRunner()


@pytest.mark.unit
def test_the_root_command_lists_the_module_groups() -> None:
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "identity" in result.output
    assert "breakglass" in result.output


@pytest.mark.unit
@pytest.mark.parametrize(
    ("command", "expected_option"),
    [
        (["breakglass", "recover-professor", "--help"], "--email"),
        (["breakglass", "transfer-professor", "--help"], "--from"),
        (["identity", "bootstrap", "--help"], "--display-name"),
        # docs/runbooks/rotate-secrets.md row 1, the only way to end every session at once.
        (["identity", "revoke-all-sessions", "--help"], "--yes"),
    ],
)
def test_the_documented_commands_take_the_documented_options(
    command: list[str], expected_option: str
) -> None:
    result = runner.invoke(cli, command)

    assert result.exit_code == 0
    assert expected_option in result.output


@pytest.mark.unit
def test_a_missing_required_option_fails_before_any_database_work() -> None:
    result = runner.invoke(cli, ["breakglass", "recover-professor"])

    assert result.exit_code != 0


@pytest.mark.unit
def test_reseeding_an_already_seeded_database_says_so_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`scripts/run_mock.sh --seed` is the documented way to start, and people run it daily.

    The second run is the normal case, not an error: the dataset is already there. Letting the
    refusal escape as a traceback also aborted run.sh under `set -e`, so the stack never reached
    the frontend and the developer was left with a stack trace and no app.
    """
    from app import seed

    def already_there(_operation: object) -> None:
        raise seed.AlreadySeededError("the demo dataset is already loaded")

    monkeypatch.setattr(seed, "run_in_session", already_there)

    result = runner.invoke(cli, ["seed", "demo"])

    assert result.exit_code == 0, result.output
    assert "already" in result.output.lower()
    assert seed.PROF_EMAIL in result.output, "still tell them how to sign in"
    assert "Traceback" not in result.output


@pytest.mark.unit
def test_a_seed_failure_that_is_not_the_second_run_still_fails_loudly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the known refusal is benign. Everything else must keep stopping the startup script."""
    from app import seed
    from app.core.errors import ConflictError

    def broken(_operation: object) -> None:
        raise ConflictError("something else entirely")

    monkeypatch.setattr(seed, "run_in_session", broken)

    result = runner.invoke(cli, ["seed", "demo"])

    assert result.exit_code != 0
