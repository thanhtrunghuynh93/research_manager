"""What an export bundle looks like (UI-06)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

# Bumped when the shape of a record changes, so a bundle read years later can be interpreted.
SCHEMA_VERSION = "1.0"


@dataclass(slots=True)
class Bundle:
    """Metadata plus records, keyed by kind. Serialisable as it stands."""

    metadata: dict[str, Any] = field(default_factory=dict)
    records: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"metadata": self.metadata, "records": self.records}


class BundleOut(BaseModel):
    metadata: dict[str, Any] = Field(default_factory=dict)
    records: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
