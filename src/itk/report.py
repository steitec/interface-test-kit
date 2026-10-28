"""Write run reports to the network drive, or spool them locally until it is back."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from .model import RunResult
from .station import Station


def folder_name(run: RunResult) -> str:
    stamp = run.started.strftime("%Y%m%d-%H%M%S")
    if run.mode == "selftest":
        name = f"selftest_{run.station}_{stamp}"
    else:
        parts = [run.serial_number] + ([run.rma] if run.rma else []) + [stamp]
        name = "_".join(parts)
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return "_" + name if name.startswith(".") else name


def _relative(run: RunResult) -> Path:
    folder = folder_name(run)
    return Path("selftest", folder) if run.mode == "selftest" else Path(folder)


def report_reachable(station: Station) -> bool:
    target = Path(station.report_dir)
    if not target.is_dir() or not os.access(target, os.W_OK | os.X_OK):
        return False
    if station.require_mount:
        p = target.resolve()
        while not os.path.ismount(p):
            p = p.parent
        if p == Path("/"):
            return False
    return True


def _fmt(value: float) -> str:
    return f"{value:g}"


def render_text(run: RunResult) -> str:
    lines = [f"Interface test report ({'equipment self-test' if run.mode == 'selftest' else 'unit test'})",
             "", f"Serial number: {run.serial_number}"]
    if run.rma:
        lines.append(f"RMA: {run.rma}")
    lines.append(f"Profile: {run.profile_name} v{run.profile_version}")
    lines.append(f"Station: {run.station}")
    if run.operator:
        lines.append(f"Operator: {run.operator}")
    lines.append(f"Started: {run.started.isoformat(timespec='seconds')}")
    if run.finished:
        lines.append(f"Finished: {run.finished.isoformat(timespec='seconds')}")
    lines.append(f"Tool version: {run.tool_version}")
    if run.only:
        lines.append(f"Only steps: {', '.join(run.only)}")
    lines += [f"Result: {run.status}", ""]
    for step in run.steps:
        note = " (passed after retry)" if step.passed_after_retry else ""
        msg = f" — {step.message}" if step.message else ""
        lines.append(f"[{step.status}] {step.name}{msg}{note}")
        if step.equipment_id:
            lines.append(f"    Equipment: {step.equipment_id}")
        for m in step.attempts[-1].measurements if step.attempts else []:
            limits = []
            if m.low is not None:
                limits.append(f">= {_fmt(m.low)}")
            if m.high is not None:
                limits.append(f"<= {_fmt(m.high)}")
            limit = f" (limit {' and '.join(limits)})" if limits else ""
            unit = f" {m.unit}" if m.unit else ""
            lines.append(f"    {m.name}: {_fmt(m.value)}{unit}{limit} "
                         f"{'ok' if m.passed else 'out of limits'}")
        if len(step.attempts) > 1:
            for i, a in enumerate(step.attempts, 1):
                lines.append(f"    attempt {i}: {a.status}{' — ' + a.message if a.message else ''}")
        for a in step.attempts:
            for d in a.details:
                lines.append(f"        {d}")
    return "\n".join(lines) + "\n"


def _write_into(base: Path, run: RunResult) -> Path:
    path = base / _relative(run)
    path.mkdir(parents=True, exist_ok=True)
    (path / "result.json").write_text(json.dumps(run.to_dict(), indent=2) + "\n")
    (path / "report.txt").write_text(render_text(run))
    return path


def write_run(run: RunResult, station: Station) -> tuple[Path, bool]:
    """Returns the folder written and whether it went to the local spool."""
    if report_reachable(station):
        try:
            return _write_into(Path(station.report_dir), run), False
        except OSError:
            pass
    return _write_into(Path(station.spool_dir), run), True


def _spooled_runs(spool: Path) -> list[Path]:
    if not spool.is_dir():
        return []
    return sorted(p.parent for p in spool.rglob("result.json"))


def sync_spool(station: Station) -> list[Path]:
    spool = Path(station.spool_dir)
    runs = _spooled_runs(spool)
    if not runs or not report_reachable(station):
        return []
    moved = []
    for src in runs:
        dest = Path(station.report_dir) / src.relative_to(spool)
        try:
            shutil.copytree(src, dest, dirs_exist_ok=True)
        except OSError:
            continue
        shutil.rmtree(src, ignore_errors=True)
        moved.append(dest)
    return moved
