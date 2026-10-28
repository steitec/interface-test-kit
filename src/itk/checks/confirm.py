"""Manual check: the operator looks at something and answers Y/N."""

from __future__ import annotations

from dataclasses import dataclass

from ..model import Attempt
from . import CheckType, fields, register


@dataclass(frozen=True)
class ConfirmConfig:
    prompt: str


def parse(raw: dict) -> ConfirmConfig:
    f = fields(raw, {"prompt"}, {})
    if not isinstance(f["prompt"], str) or not f["prompt"].strip():
        raise ValueError("prompt: must be a non-empty text")
    return ConfirmConfig(f["prompt"])


def run(config: ConfirmConfig, ctx, ui) -> Attempt:
    if ui.ask_yes_no(config.prompt):
        return Attempt.ok()
    text = f"Operator answered No: {config.prompt}"
    return Attempt.fail(ctx.say(text, text))


register("confirm", CheckType(parse=parse, run=run))
