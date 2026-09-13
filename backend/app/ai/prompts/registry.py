"""Versioned prompts (ASSESS-09, architecture §10).

A prompt is part of how a result was produced, so it is named and versioned like code and recorded
on every assessment. Loading one by id and version is what lets an old assessment be explained.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

PROMPT_ROOT = Path(__file__).parent


@dataclass(frozen=True, slots=True)
class Prompt:
    prompt_id: str
    version: str
    model: str
    temperature: float
    max_tokens: int
    text: str

    @property
    def label(self) -> str:
        return f"{self.prompt_id}@{self.version}"


def load(prompt_id: str, version: str = "v1") -> Prompt:
    folder = PROMPT_ROOT / prompt_id
    manifest_path = folder / "manifest.toml"
    body_path = folder / f"{version}.md"
    if not body_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"no prompt {prompt_id}@{version}")

    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    return Prompt(
        prompt_id=prompt_id,
        version=version,
        model=str(manifest.get("model", "")),
        # Zero by default: an assessment that changes between identical runs is not reproducible.
        temperature=float(manifest.get("temperature", 0.0)),
        max_tokens=int(manifest.get("max_tokens", 2048)),
        text=body_path.read_text(encoding="utf-8"),
    )


def available() -> list[str]:
    return sorted(
        folder.name for folder in PROMPT_ROOT.iterdir() if (folder / "manifest.toml").is_file()
    )
