"""One operator session: serial number, profile, preflight, steps, result and report."""

from __future__ import annotations

import re
from datetime import datetime

from . import __version__
from .context import Context
from .detect import detect_profiles
from .model import RunResult, StepResult
from .profile import Profile, load_profiles
from .report import sync_spool, write_run
from .runner import run_steps, select_steps
from .station import Station
from .ui import UI

SERIAL_PROMPT = "Scan or enter the serial number: "
SERIAL_RETRY = "The serial number does not match the expected format. Try again."
SELFTEST_HINT = "Same failure on several units? Run the equipment self-test."


def real_context(mode: str) -> Context:
    from .checks.can import open_socketcan
    from .checks.serial import open_pyserial
    return Context(open_serial=open_pyserial, open_can=open_socketcan, mode=mode)


def _ask_serial(ui: UI, pattern: str | None) -> str:
    while True:
        serial = ui.ask_text(SERIAL_PROMPT)
        if serial and (pattern is None or re.fullmatch(pattern, serial)):
            return serial
        ui.info(SERIAL_RETRY)


def _choose(ui: UI, candidates: list[Profile]) -> Profile:
    for i, p in enumerate(candidates, 1):
        ui.info(f"  {i}  {p.name} (v{p.version})")
    while True:
        answer = ui.ask_text("Choose the profile number: ")
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1]


def _select_profile(ui: UI, ctx: Context, candidates: list[Profile]) -> Profile:
    detected = detect_profiles(candidates, ctx) if len(candidates) > 1 else candidates
    profile = detected[0] if len(detected) == 1 else _choose(ui, candidates)
    while not ui.ask_yes_no(f"Profile: {profile.name} (v{profile.version}). Correct?"):
        if len(candidates) == 1:
            raise ValueError("Profile not confirmed. Check the profiles with the test engineer.")
        profile = _choose(ui, candidates)
    return profile


def run_session(station: Station, ctx: Context, ui: UI, *, rma: str | None = None,
                only: list[str] | None = None, profiles: list[Profile] | None = None) -> RunResult:
    moved = sync_spool(station)
    if moved:
        ui.info(f"Uploaded {len(moved)} saved report(s) to the network drive.")

    selftest = ctx.mode == "selftest"
    if profiles is None:
        profiles = load_profiles(station.profile_dir)
    candidates = [p for p in profiles if p.reference == selftest]
    if not candidates:
        kind = "reference profiles" if selftest else "profiles"
        raise ValueError(f"No {kind} found in {station.profile_dir}")

    # The serial pattern is per profile; with several candidates we only know it
    # after the profile is chosen, so ask first and check against all patterns.
    patterns = {p.serial_pattern for p in candidates}
    pattern = patterns.pop() if len(patterns) == 1 else None
    serial = "selftest" if selftest else _ask_serial(ui, pattern)
    operator = ui.ask_text("Operator: ") if station.ask_operator else None
    profile = _select_profile(ui, ctx, candidates)
    if not selftest and profile.serial_pattern and not re.fullmatch(profile.serial_pattern, serial):
        ui.info(SERIAL_RETRY)
        serial = _ask_serial(ui, profile.serial_pattern)

    steps = select_steps(profile, only)
    run = RunResult(ctx.mode, serial, rma, profile.name, profile.version, station.name, operator,
                    datetime.now().astimezone(), None, __version__, [], "ABORTED", only)

    from .checks import STEP_TYPES
    problems = [p for s in steps for p in STEP_TYPES[s.type].preflight(s.config, ctx)]
    if problems:
        for p in problems:
            ui.info(p)
    else:
        results: list[StepResult] = run.steps
        try:
            if profile.setup:
                ui.wait_key(profile.setup + "\nPress Enter when ready.")
            run_steps(profile, ctx, ui, only, results=results)
            run.status = "PASS" if all(s.status == "PASS" for s in results) else "FAIL"
        except KeyboardInterrupt:
            run.status = "ABORTED"

    run.finished = datetime.now().astimezone()
    ui.banner(run.status)
    if run.status == "FAIL" and not selftest:
        ui.info(SELFTEST_HINT)
    path, spooled = write_run(run, station)
    if spooled:
        ui.info(f"Network drive not reachable. Report saved locally: {path}")
    else:
        ui.info(f"Report saved: {path}")
    return run
