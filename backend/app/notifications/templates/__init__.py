"""Jinja2 templates, one plain-text and one HTML body per message, per language.

A template receives identifiers, dates, and the recipient's own missing-entry list — never an
assessment narrative and never another student's work (REP-08, UI-07).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

TEMPLATE_ROOT = Path(__file__).parent
DEFAULT_LOCALE = "en"

_environment = Environment(
    loader=FileSystemLoader(TEMPLATE_ROOT),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template: str, locale: str, params: dict[str, Any]) -> tuple[str, str, str]:
    """Return (subject, text body, html body) for one message."""
    folder = locale if (TEMPLATE_ROOT / locale).is_dir() else DEFAULT_LOCALE
    subject = _environment.get_template(f"{folder}/{template}.subject.txt").render(**params)
    text = _environment.get_template(f"{folder}/{template}.txt").render(**params)
    html = _environment.get_template(f"{folder}/{template}.html").render(**params)
    return subject.strip(), text, html
