"""Shared test helpers: a scriptable ``fake`` step type."""

from __future__ import annotations

from dataclasses import dataclass, field

from interface_test_kit.checks import CheckType, fields, register
from interface_test_kit.model import Attempt
from interface_test_kit.profile import Profile, Step


@dataclass(frozen=True)
class FakeConfig:
    outcomes: list = field(default_factory=list)
    problems: tuple = ()


def _parse(raw: dict) -> FakeConfig:
    f = fields(raw, set(), {"outcomes": ["PASS"], "problems": []})
    return FakeConfig(list(f["outcomes"]), tuple(f["problems"]))


def _run(config: FakeConfig, ctx, ui) -> Attempt:
    outcome = config.outcomes.pop(0)
    if outcome == "raise":
        raise OSError("[Errno 2] No such file: '/dev/ttyS1'")
    if outcome == "interrupt":
        raise KeyboardInterrupt
    if outcome == "PASS":
        return Attempt.ok("fine")
    return Attempt.fail(ctx.say("device broken", "equipment broken"))


register("fake", CheckType(parse=_parse, run=_run,
                           preflight=lambda config, ctx: list(config.problems)))


def fake_step(name: str, *outcomes: str, equipment: str | None = None) -> Step:
    from interface_test_kit.profile import slug
    return Step(slug(name), name, "fake", FakeConfig(list(outcomes)), equipment, 1)


def make_profile(*steps: Step, **kwargs) -> Profile:
    return Profile(name=kwargs.pop("name", "Test"), version=kwargs.pop("version", 1),
                   steps=list(steps), **kwargs)
