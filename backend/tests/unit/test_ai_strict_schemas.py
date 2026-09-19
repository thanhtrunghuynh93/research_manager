"""Every response schema must be one the provider's strict mode accepts.

This is the test that was missing. `rate_rubric` failed on every single call for as long as a real
key had been configured — 13 of 13 runs, no assessment ever produced from real model output — and
the whole suite passed, because the fake gateway never builds a JSON schema and the SDK's own
strict converter walks straight past an open-ended map.

The models are discovered by reflection rather than listed. A schema added next year is covered on
the day it lands, which is the only version of this test worth having.
"""

from __future__ import annotations

import inspect

import pytest
from pydantic import BaseModel

from app.ai import schemas
from app.ai.schemas.strict import violations

pytestmark = pytest.mark.unit


def _response_models() -> list[type[BaseModel]]:
    found = [
        obj
        for obj in vars(schemas).values()
        if inspect.isclass(obj) and issubclass(obj, BaseModel) and obj is not BaseModel
    ]
    assert found, "no response models discovered — has app.ai.schemas moved?"
    return sorted(found, key=lambda model: model.__name__)


@pytest.mark.parametrize("model", _response_models(), ids=lambda model: model.__name__)
def test_every_response_schema_is_one_the_provider_accepts(model: type[BaseModel]) -> None:
    assert violations(model) == []


def test_an_open_ended_map_is_refused() -> None:
    """The specific defect, pinned: `dict[str, X]` is what broke `rate_rubric`.

    It is worth its own test because it is the one fault the SDK's converter does not repair —
    `additionalProperties` is already present, holding a `$ref`, so the key-absent check skips it
    and a request the server refuses goes out looking strict.
    """

    class OpenEnded(BaseModel):
        ratings: dict[str, int] = {}

    found = violations(OpenEnded)

    assert any("open-ended map" in line for line in found)


def test_a_schema_of_lists_and_scalars_passes() -> None:
    # The counterpart, so the validator is not merely rejecting everything.
    class Closed(BaseModel):
        name: str
        scores: list[int] = []

    assert violations(Closed) == []
