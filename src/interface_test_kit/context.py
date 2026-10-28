"""Everything a check needs from the outside world, so tests can swap it out."""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def run_command(args: list[str], timeout: float = 30) -> CommandResult:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        return CommandResult(127, "", f"command not found: {args[0]}")
    except subprocess.TimeoutExpired:
        return CommandResult(124, "", f"timed out after {timeout} s: {' '.join(args)}")
    return CommandResult(p.returncode, p.stdout, p.stderr)


@dataclass
class Context:
    root: Path = Path("/")
    run: Callable[[list[str]], CommandResult] = run_command
    open_serial: Callable[[str, int], Any] | None = None
    open_can: Callable[[str], Any] | None = None
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    mode: str = "unit"

    def path(self, p: str) -> Path:
        return Path(self.root) / p.lstrip("/")

    def say(self, unit: str, equipment: str) -> str:
        return equipment if self.mode == "selftest" else unit
