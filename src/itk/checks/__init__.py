"""Registry of step types. Each check module registers itself on import."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..context import Context
    from ..model import Attempt
    from ..ui import UI


def _no_preflight(config: Any, ctx: "Context") -> list[str]:
    return []


@dataclass(frozen=True)
class CheckType:
    parse: Callable[[dict], Any]
    run: Callable[[Any, "Context", "UI"], "Attempt"]
    preflight: Callable[[Any, "Context"], list[str]] = _no_preflight


STEP_TYPES: dict[str, CheckType] = {}


def register(name: str, check: CheckType) -> None:
    STEP_TYPES[name] = check


def fields(raw: dict, required: set[str], optional: dict[str, Any]) -> dict:
    """Check the keys of a step's type-specific fields and fill in defaults.

    The step's ``name`` is always passed along, so checks can use it in messages.
    """
    optional = {"name": "", **optional}
    for key in raw:
        if key not in required and key not in optional:
            raise ValueError(f"unknown field '{key}'")
    for key in sorted(required):
        if key not in raw:
            raise ValueError(f"{key}: missing")
    return {**optional, **raw}


from . import confirm, serial, usb  # noqa: E402,F401  (register themselves)
