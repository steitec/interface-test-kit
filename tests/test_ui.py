import io
from pathlib import Path

import pytest

from interface_test_kit.context import Context, run_command
from interface_test_kit.model import Attempt, StepResult
from interface_test_kit.ui import ConsoleUI


def console(text: str) -> tuple[ConsoleUI, io.StringIO]:
    out = io.StringIO()
    return ConsoleUI(stdin=io.StringIO(text), stdout=out), out


def test_console_yes_no_repeats_on_garbage():
    ui, out = console("maybe\n\ny\n")
    assert ui.ask_yes_no("Is the LED green?") is True
    assert out.getvalue().count("Is the LED green? [Y/N] ") == 3


@pytest.mark.parametrize("answer,expected", [("Y", True), ("yes", True), ("N", False), (" no \n", False)])
def test_console_yes_no_answers(answer, expected):
    ui, _ = console(answer + "\n")
    assert ui.ask_yes_no("Q") is expected


def test_console_eof_is_abort():
    ui, _ = console("")
    with pytest.raises(KeyboardInterrupt):
        ui.ask_yes_no("Q")
    with pytest.raises(KeyboardInterrupt):
        ui.ask_text("Serial: ")


def test_console_ask_text_strips():
    ui, _ = console("EPC-24-00001\r \n")
    assert ui.ask_text("Serial: ") == "EPC-24-00001"


def test_console_step_line_no_color_when_not_tty():
    ui, out = console("")
    ui.step_finished(StepResult("usb", "USB", "usb", "FAIL", [Attempt.fail("no stick")]))
    assert "[FAIL] USB" in out.getvalue() and "no stick" in out.getvalue()
    assert "\033[" not in out.getvalue()


@pytest.mark.parametrize("status", ["PASS", "FAIL", "ABORTED"])
def test_console_banner_contains_result(status):
    ui, out = console("")
    ui.banner(status)
    text = out.getvalue()
    assert f"RESULT: {status}" in text
    assert len([line for line in text.splitlines() if line.strip()]) >= 3


def test_say_picks_mode():
    assert Context().say("unit", "eq") == "unit"
    assert Context(mode="selftest").say("unit", "eq") == "eq"


def test_context_path(tmp_path):
    assert Context(root=tmp_path).path("/sys/class/net") == tmp_path / "sys/class/net"
    assert Context().path("/sys") == Path("/sys")


def test_run_command_missing_and_ok():
    assert run_command(["itk-does-not-exist-xyz"]).returncode == 127
    r = run_command(["echo", "hi"])
    assert r.returncode == 0 and r.stdout.strip() == "hi"


def test_run_command_timeout():
    assert run_command(["sleep", "5"], timeout=0.2).returncode == 124


def test_console_no_started_line_when_not_tty():
    from interface_test_kit.profile import Step
    ui, out = console("")
    ui.step_started(Step("usb", "USB", "usb", None, None, 1))
    assert out.getvalue() == ""


class TTY(io.StringIO):
    def isatty(self):
        return True


def test_console_tty_overwrites_started_line_and_breaks_for_prompts():
    from interface_test_kit.profile import Step
    out = TTY()
    ui = ConsoleUI(stdin=io.StringIO("y\n"), stdout=out)
    ui.step_started(Step("led", "Power LED", "confirm", None, None, 1))
    ui.ask_yes_no("Is the power LED green?")
    ui.step_finished(StepResult("led", "Power LED", "confirm", "PASS", [Attempt.ok()]))
    text = out.getvalue()
    assert "Power LED\nIs the power LED green? [Y/N] " in text
    assert text.endswith("\r  \033[32m[PASS]\033[0m Power LED        \n")
