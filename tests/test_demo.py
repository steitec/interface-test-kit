import json
from pathlib import Path

import pytest

from interface_test_kit.cli import main
from interface_test_kit.profile import load_profile
from interface_test_kit.sim.world import FAULTS
from interface_test_kit.station import load_station

EXPECTED_STEP = {"serial_cts": "serial-1", "serial_data": "serial-1", "usb_missing": "usb",
                 "usb_slow": "usb", "usb_wrong_speed": "usb", "usb_no_label": "usb",
                 "eth_no_link": "lan1", "eth_speed": "lan1", "can_no_ack": "can", "led_off": "power-led"}


def result(out: Path) -> dict:
    files = list(out.rglob("result.json"))
    assert len(files) == 1
    return json.loads(files[0].read_text())


def test_faults_list_is_complete():
    assert set(FAULTS) == set(EXPECTED_STEP)


def test_demo_pass(tmp_path, capsys):
    assert main(["demo", "--out", str(tmp_path)]) == 0
    data = result(tmp_path)
    assert data["status"] == "PASS" and data["serial_number"] == "EPC-24-00137"
    assert [s["id"] for s in data["steps"]] == ["serial-1", "serial-2", "usb", "lan1", "can", "power-led"]
    out = capsys.readouterr().out
    assert "RESULT: PASS" in out and "Scan or enter the serial number: EPC-24-00137" in out


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_each_fault_fails_the_right_step(tmp_path, fault):
    assert main(["demo", "--fault", fault, "--out", str(tmp_path)]) == 1
    steps = {s["id"]: s["status"] for s in result(tmp_path)["steps"]}
    failed = [k for k, v in steps.items() if v == "FAIL"]
    assert failed == [EXPECTED_STEP[fault]]


def test_list_faults(capsys):
    assert main(["demo", "--list-faults"]) == 0
    out = capsys.readouterr().out
    assert all(name in out for name in FAULTS)


def test_unknown_fault_is_rejected(capsys):
    with pytest.raises(SystemExit) as e:
        main(["demo", "--fault", "nope"])
    assert e.value.code == 2


def test_examples_are_valid():
    root = Path(__file__).parent.parent / "examples"
    profiles = sorted((root / "profiles").glob("*.yaml"))
    assert len(profiles) >= 2
    loaded = [load_profile(p) for p in profiles]
    assert any(p.reference for p in loaded) and any(not p.reference for p in loaded)
    load_station(root / "station.yaml")


def test_autoui_breaks_pending_step_line_on_tty():
    import io

    from interface_test_kit.profile import Step
    from interface_test_kit.sim.world import AutoUI

    class TTY(io.StringIO):
        def isatty(self):
            return True
    out = TTY()
    ui = AutoUI("SN1", stdout=out)
    ui.step_started(Step("led", "Power LED", "confirm", None, None, 1))
    ui.ask_yes_no("Is the power LED green?")
    assert "Power LED\nIs the power LED green? [Y/N] Y\n" in out.getvalue()
