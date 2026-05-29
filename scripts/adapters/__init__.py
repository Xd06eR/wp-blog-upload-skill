"""Editor adapters: turn the parsed body AST into editor-specific markup.

Each adapter exposes one function:

    render(doc, placements, media_map) -> str

Built-in adapters live as named modules (gutenberg, classic, elementor).
Extra adapters can be registered at runtime via `register(editor, render_fn)`.
"""

from __future__ import annotations

from typing import Callable

from . import classic, elementor, gutenberg


_BUILTIN: dict[str, Callable] = {
    "gutenberg": gutenberg.render,
    "classic":   classic.render,
    "elementor": elementor.render,
}

_RUNTIME: dict[str, Callable] = {}


def get(editor: str) -> Callable:
    """Return the render function for `editor`. Looks up runtime-registered
    adapters first, then built-ins."""
    name = editor.strip().lower()
    if name in _RUNTIME:
        return _RUNTIME[name]
    if name in _BUILTIN:
        return _BUILTIN[name]
    supported = sorted(set(_BUILTIN) | set(_RUNTIME))
    raise ValueError(
        f"No adapter for editor '{editor}'. Currently loaded: {supported}. "
        f"Register one at runtime via adapters.register()."
    )


def register(editor: str, render_fn: Callable) -> None:
    """Register a runtime adapter."""
    _RUNTIME[editor.strip().lower()] = render_fn


def supported() -> list[str]:
    return sorted(set(_BUILTIN) | set(_RUNTIME))
