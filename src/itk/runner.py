"""Run the steps of a profile, applying the retry rule."""

from __future__ import annotations

from .checks import STEP_TYPES
from .context import Context
from .model import Attempt, StepResult
from .profile import Profile, Step
from .ui import UI

RETRY_PROMPT = "Retry this step?"
CONFIRM_INFO = "Passed. Running once more to confirm."
INTERNAL_ERROR = "Internal error in this test step. Tell the test engineer."


def _attempt(step: Step, ctx: Context, ui: UI) -> Attempt:
    try:
        return STEP_TYPES[step.type].run(step.config, ctx, ui)
    except KeyboardInterrupt:
        raise
    except Exception as e:  # a broken check must not stop the run
        return Attempt.fail(INTERNAL_ERROR, details=[f"{type(e).__name__}: {e}"])


def _passed(attempts: list[Attempt]) -> bool:
    if len(attempts) == 1:
        return attempts[0].status == "PASS"
    return attempts[-1].status == "PASS" and attempts[-2].status == "PASS"


def run_step(step: Step, ctx: Context, ui: UI, max_attempts: int) -> StepResult:
    """A step passes on its first attempt, or when its last two attempts passed."""
    attempts = [_attempt(step, ctx, ui)]
    while not _passed(attempts) and len(attempts) < max_attempts:
        if attempts[-1].status == "FAIL":
            if not ui.ask_yes_no(RETRY_PROMPT):
                break
        else:
            ui.info(CONFIRM_INFO)
        attempts.append(_attempt(step, ctx, ui))
    status = "PASS" if _passed(attempts) else "FAIL"
    return StepResult(step.id, step.name, step.type, status, attempts)


def run_steps(profile: Profile, ctx: Context, ui: UI,
              only: list[str] | None = None) -> list[StepResult]:
    steps = profile.steps
    if only:
        wanted = [o.lower() for o in only]
        known = {s.id.lower() for s in steps}
        for o in wanted:
            if o not in known:
                raise ValueError(f"unknown step id: {o}")
        steps = [s for s in steps if s.id.lower() in wanted]
    results = []
    for step in steps:
        equipment_id = None
        if ctx.mode == "selftest" and step.equipment:
            equipment_id = ui.ask_text(f"{step.equipment}: ")
        ui.step_started(step)
        result = run_step(step, ctx, ui, profile.max_attempts)
        result.equipment_id = equipment_id
        ui.step_finished(result)
        results.append(result)
    return results
