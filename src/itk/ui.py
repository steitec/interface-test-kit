"""Operator screen: prompts, step lines and the final result banner."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .model import StepResult
    from .profile import Step

_COLORS = {"PASS": "\033[32m", "FAIL": "\033[31m", "ABORTED": "\033[33m"}
_RESET = "\033[0m"


class UI(Protocol):
    def info(self, text: str) -> None: ...
    def ask_text(self, prompt: str) -> str: ...
    def ask_yes_no(self, prompt: str) -> bool: ...
    def wait_key(self, prompt: str) -> None: ...
    def step_started(self, step: Step) -> None: ...
    def step_finished(self, result: StepResult) -> None: ...
    def banner(self, status: str) -> None: ...


class ConsoleUI:
    def __init__(self, stdin=None, stdout=None):
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        isatty = getattr(self.stdout, "isatty", None)
        self.color = bool(isatty and isatty())

    def _write(self, text: str) -> None:
        self.stdout.write(text)
        self.stdout.flush()

    def _readline(self) -> str:
        line = self.stdin.readline()
        if not line:
            raise KeyboardInterrupt
        return line

    def _paint(self, status: str, text: str) -> str:
        return f"{_COLORS.get(status, '')}{text}{_RESET}" if self.color else text

    def info(self, text: str) -> None:
        self._write(f"{text}\n")

    def ask_text(self, prompt: str) -> str:
        self._write(prompt)
        return self._readline().strip()

    def ask_yes_no(self, prompt: str) -> bool:
        while True:
            self._write(f"{prompt} [Y/N] ")
            answer = self._readline().strip().lower()
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False

    def wait_key(self, prompt: str) -> None:
        self._write(f"{prompt} ")
        self._readline()

    def step_started(self, step: Step) -> None:
        self._write(f"  ...    {step.name}\n")

    def step_finished(self, result: StepResult) -> None:
        tag = self._paint(result.status, f"[{result.status}]")
        note = " (passed after retry)" if result.passed_after_retry else ""
        self._write(f"  {tag} {result.name:<16} {result.message}{note}\n")

    def banner(self, status: str) -> None:
        line = "=" * 40
        self._write("\n" + self._paint(status, f"{line}\n   RESULT: {status}\n{line}") + "\n")


class ScriptedUI:
    """Test double: answers come from a list, every call is logged."""

    def __init__(self, answers: list):
        self.answers = list(answers)
        self.log: list[str] = []

    def _next(self, prompt: str):
        if not self.answers:
            raise AssertionError(f"no scripted answer left for: {prompt}")
        return self.answers.pop(0)

    def info(self, text: str) -> None:
        self.log.append(f"info: {text}")

    def ask_text(self, prompt: str) -> str:
        self.log.append(f"ask_text: {prompt}")
        return str(self._next(prompt)).strip()

    def ask_yes_no(self, prompt: str) -> bool:
        self.log.append(f"ask_yes_no: {prompt}")
        return bool(self._next(prompt))

    def wait_key(self, prompt: str) -> None:
        self.log.append(f"wait_key: {prompt}")

    def step_started(self, step: Step) -> None:
        self.log.append(f"step_started: {step.name}")

    def step_finished(self, result: StepResult) -> None:
        self.log.append(f"step_finished: {result.name} {result.status}")

    def banner(self, status: str) -> None:
        self.log.append(f"banner: {status}")
