"""Whether a response model is one the provider's strict mode will actually accept.

The rules are the provider's, reimplemented here rather than borrowed, for two reasons.

The first is the import contract: `openai` belongs to `app.ai.gateway` and nowhere else
(`pyproject.toml`, contract 3 of 5), and this has to be callable from the fake gateway and from a
unit test that never opens a socket.

The second is that borrowing would not work. The SDK's `to_strict_json_schema` fills in
`additionalProperties: false` only where the key is *absent*; a `dict[str, X]` emits the key
already holding a `$ref`, so the converter walks past it, declares the schema strict, and sends a
request the server answers with 400. `to_strict_json_schema(RubricOutput)` succeeds today against
a schema that has never once been accepted in production. A check that delegates to the SDK is a
check that agrees with the bug.

So this normalises the schema exactly as the SDK does — that part is legitimate and is what
actually goes on the wire — and then judges what is left.

What it is for: `rate_rubric` failed on every call for as long as a real key has been configured,
because `RubricOutput.dimensions` was an open-ended map. Nothing caught it: the fake gateway never
builds a JSON schema, so the whole suite passed through the defect.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

# Keywords strict mode does not accept.
#
# `default` is deliberately NOT here. The SDK does not strip it, and `ClaimList`, `ClaimVerdicts`,
# `RoutePlan` and `AnswerDraft` all carry defaults and all succeed against the real provider — so
# the production record settles it, and flagging it would fail four schemas that demonstrably work.
#
# Numeric bounds ARE here, and that one is a judgement call rather than a reading of the record:
# the only schema carrying them is the only schema that has never succeeded, so production tells us
# nothing either way. Sources disagree, and the disagreement has shifted by model generation. A
# constraint that may or may not be honoured is worth nothing on the wire regardless, so enforce it
# in Python — a validator does not appear in the schema — and keep the contract unambiguous.
UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
        "pattern",
        "format",
        "uniqueItems",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "patternProperties",
    }
)

MAX_NESTING_DEPTH = 5
MAX_PROPERTIES = 100


def violations(model: type[BaseModel]) -> list[str]:
    """Every reason the provider would refuse this model, each naming where it is.

    An empty list is the only acceptable result for anything handed to `complete_structured`.
    """
    schema = _as_sent(model.model_json_schema())
    found: list[str] = []
    counted = _Counter()

    for name, definition in (schema.get("$defs") or {}).items():
        _walk(definition, f"$defs/{name}", found, counted, depth=0)
    _walk(schema, model.__name__, found, counted, depth=0, skip_defs=True)

    if counted.properties > MAX_PROPERTIES:
        found.append(f"{model.__name__}: {counted.properties} properties, at most {MAX_PROPERTIES}")
    if counted.depth > MAX_NESTING_DEPTH:
        found.append(f"{model.__name__}: nested {counted.depth} deep, at most {MAX_NESTING_DEPTH}")
    return found


def _as_sent(node: Any) -> Any:
    """The schema as the SDK will actually transmit it.

    Two normalisations, mirroring `openai.lib._pydantic._ensure_strict_json_schema`: an object
    with no `additionalProperties` key gets `false`, and an object's `required` is rewritten to
    every property. Judging the schema pydantic emits instead of this one would fail every model
    in the package for faults the SDK repairs on the way out.
    """
    if isinstance(node, dict):
        out = {key: _as_sent(value) for key, value in node.items()}
        if out.get("type") == "object" and "additionalProperties" not in out:
            out["additionalProperties"] = False
        properties = out.get("properties")
        if isinstance(properties, dict):
            out["required"] = list(properties)
        return out
    if isinstance(node, list):
        return [_as_sent(item) for item in node]
    return node


class _Counter:
    def __init__(self) -> None:
        self.properties = 0
        self.depth = 0


def _walk(
    node: Any,
    path: str,
    found: list[str],
    counted: _Counter,
    *,
    depth: int,
    skip_defs: bool = False,
) -> None:
    if not isinstance(node, dict):
        return
    counted.depth = max(counted.depth, depth)

    for keyword in sorted(UNSUPPORTED_KEYWORDS & node.keys()):
        found.append(f"{path}: `{keyword}` is not supported in strict mode")

    if node.get("type") == "object":
        if node.get("properties") is None:
            found.append(
                f"{path}: an object with no `properties` — an open-ended map (`dict[str, X]`) "
                "cannot be expressed in strict mode. Use a list of objects carrying the key as "
                "a field."
            )
        else:
            counted.properties += len(node["properties"])
        if node.get("additionalProperties") is not False:
            found.append(
                f"{path}: `additionalProperties` must be false, and the SDK will not correct this "
                "one because the key is already present"
            )

    for key, child in node.items():
        if key == "$defs" and skip_defs:
            continue
        if key == "properties" and isinstance(child, dict):
            for name, sub in child.items():
                _walk(sub, f"{path}.{name}", found, counted, depth=depth + 1)
        elif isinstance(child, dict):
            _walk(child, f"{path}/{key}", found, counted, depth=depth + 1)
        elif isinstance(child, list):
            for index, sub in enumerate(child):
                _walk(sub, f"{path}/{key}[{index}]", found, counted, depth=depth + 1)


__all__ = ["MAX_NESTING_DEPTH", "MAX_PROPERTIES", "UNSUPPORTED_KEYWORDS", "violations"]
