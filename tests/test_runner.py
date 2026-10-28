import pytest
from conftest import fake_step, make_profile

from itk.context import Context
from itk.runner import CONFIRM_INFO, INTERNAL_ERROR, RETRY_PROMPT, run_step, run_steps
from itk.ui import ScriptedUI


@pytest.mark.parametrize("outcomes,answers,status,n", [
    (["PASS"], [], "PASS", 1),
    (["FAIL"], [False], "FAIL", 1),
    (["FAIL", "PASS", "PASS"], [True], "PASS", 3),
    (["FAIL", "PASS", "FAIL", "PASS"], [True, True], "FAIL", 4),   # max 4 reached
    (["FAIL", "FAIL", "PASS", "PASS"], [True, True], "PASS", 4),
    (["FAIL", "PASS", "FAIL"], [True, False], "FAIL", 3),
])
def test_retry_rule(outcomes, answers, status, n):
    ui = ScriptedUI(answers)
    result = run_step(fake_step("Serial 1", *outcomes), Context(), ui, max_attempts=4)
    assert result.status == status
    assert len(result.attempts) == n
    assert ui.answers == []
    retries = sum(1 for line in ui.log if RETRY_PROMPT in line)
    assert retries == len(answers)
    # the confirm message appears only when another attempt follows the FAIL→PASS
    fail_then_pass = sum(1 for a, b in zip(outcomes[:n - 2], outcomes[1:n - 1]) if (a, b) == ("FAIL", "PASS"))
    assert sum(1 for line in ui.log if CONFIRM_INFO in line) == fail_then_pass


def test_max_attempts_one_never_asks():
    ui = ScriptedUI([])
    result = run_step(fake_step("A", "FAIL"), Context(), ui, max_attempts=1)
    assert result.status == "FAIL" and len(result.attempts) == 1


def test_exception_becomes_fail_and_run_continues():
    ui = ScriptedUI([False])
    profile = make_profile(fake_step("Serial 2", "raise"), fake_step("USB", "PASS"))
    results = run_steps(profile, Context(), ui)
    assert results[0].status == "FAIL" and results[0].message == INTERNAL_ERROR
    assert "No such file" in results[0].attempts[0].details[0]
    assert results[1].status == "PASS"


def test_keyboard_interrupt_propagates():
    with pytest.raises(KeyboardInterrupt):
        run_step(fake_step("A", "interrupt"), Context(), ScriptedUI([]), max_attempts=4)


def test_only_filters_and_rejects_unknown():
    profile = make_profile(fake_step("Serial 1", "PASS"), fake_step("USB", "PASS"))
    results = run_steps(profile, Context(), ScriptedUI([]), only=["usb"])
    assert [r.id for r in results] == ["usb"]
    with pytest.raises(ValueError, match="unknown step id: lan"):
        run_steps(profile, Context(), ScriptedUI([]), only=["USB", "lan"])


def test_only_is_case_insensitive():
    profile = make_profile(fake_step("Serial 1", "PASS"), fake_step("USB", "PASS"))
    assert [r.id for r in run_steps(profile, Context(), ScriptedUI([]), only=["SERIAL-1"])] == ["serial-1"]


def test_selftest_asks_equipment_id():
    ui = ScriptedUI(["LB-07"])
    profile = make_profile(fake_step("Serial 1", "FAIL", equipment="Loopback plug number"),
                           max_attempts=1)
    results = run_steps(profile, Context(mode="selftest"), ui)
    assert results[0].equipment_id == "LB-07"
    assert results[0].message == "equipment broken"
    assert any("Loopback plug number" in line for line in ui.log)


def test_unit_mode_does_not_ask_equipment_id():
    profile = make_profile(fake_step("Serial 1", "PASS", equipment="Loopback plug number"))
    results = run_steps(profile, Context(), ScriptedUI([]))
    assert results[0].equipment_id is None
