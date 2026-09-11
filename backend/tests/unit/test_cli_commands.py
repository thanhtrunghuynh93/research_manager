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
