from datetime import datetime, timezone

from itk.model import Attempt, Measurement, RunResult, StepResult


def test_measurement_limits():
    assert Measurement("speed", 30.0, "MB/s", low=10).passed
    assert not Measurement("speed", 5.0, "MB/s", low=10).passed
    assert not Measurement("loss", 20.0, "%", high=0).passed
    assert Measurement("x", 1.0).passed
    assert Measurement("speed", 5.0, low=10).to_dict()["passed"] is False


def test_step_passed_after_retry():
    s = StepResult("usb", "USB", "usb", "PASS",
                   [Attempt.fail("no stick"), Attempt.ok(), Attempt.ok()])
    assert s.passed_after_retry and s.message == ""
    assert s.to_dict()["passed_after_retry"] is True
    assert len(s.to_dict()["attempts"]) == 3


def test_single_pass_is_not_after_retry():
    s = StepResult("usb", "USB", "usb", "PASS", [Attempt.ok("fine")])
    assert not s.passed_after_retry and s.message == "fine"


def test_attempt_defaults_are_independent():
    a, b = Attempt.ok(), Attempt.ok()
    a.details.append("x")
    assert b.details == []


def test_run_to_dict_iso_times():
    t = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
    r = RunResult("unit", "EPC-24-00001", None, "EPC-24 B", 3, "st1", None,
                  t, t, "0.1.0", [], "PASS")
    d = r.to_dict()
    assert d["started"] == "2026-10-28T09:00:00+00:00"
    assert d["finished"] == "2026-10-28T09:00:00+00:00"
    assert d["status"] == "PASS" and d["steps"] == []
