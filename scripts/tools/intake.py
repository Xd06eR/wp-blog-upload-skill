"""Brief-intake dispatch: pick the parser from the file extension.

The skill accepts two brief formats and auto-detects by suffix:

  - ``.docx``  -> ``parse_docx`` (native Word reader). The safer default:
    when a brief wraps the article body in a table cell, markdown export can
    flatten that cell to one line, but the .docx keeps every heading +
    paragraph, so the structure survives.
  - ``.md`` / anything else -> ``parse_md`` (the markdown parser). Fine for
    clean, non-table-wrapped briefs and the multi-brief ``### **Brand**``
    format.

Both parsers expose the same ``parse(path, brand=None)`` / ``list_briefs(path)``
surface and return the same ``ParsedDoc`` / ``BriefSummary`` shapes, so every
caller downstream (render + upload) is format-agnostic.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType


def parser_for(path: str | Path) -> ModuleType:
    """Return the parser module (``parse_docx`` or ``parse_md``) for ``path``."""
    if Path(path).suffix.lower() == ".docx":
        from . import parse_docx
        return parse_docx
    from . import parse_md
    return parse_md
