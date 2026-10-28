import os
import threading

import pytest

from itk.checks import STEP_TYPES
from itk.checks.serial import LOOPBACK_TYPES, SerialConfig, open_pyserial
from itk.context import Context
from itk.sim.serial import SimLoopback
from itk.ui import ScriptedUI

SERIAL = STEP_TYPES["serial"]


def cfg(**kw):
    kw.setdefault("name", "Serial 1")
    kw.setdefault("port", "/dev/ttyS0")
    kw.setdefault("loopback", "9pin-full")
    kw.setdefault("bauds", (9600, 115200))
    return SerialConfig(**kw)


def run_with(sim, config=None, mode="unit"):
    opened = []

    def open_serial(port, baud):
        opened.append((port, baud))
        return sim
    ctx = Context(open_serial=open_serial, mode=mode)
    return SERIAL.run(config or cfg(), ctx, ScriptedUI([])), opened


def test_parse_defaults_and_errors():
    c = SERIAL.parse({"name": "S1", "port": "/dev/ttyS0"})
    assert c == SerialConfig("S1", "/dev/ttyS0", "9pin", (9600, 115200), 512)
    with pytest.raises(ValueError, match="loopback"):
        SERIAL.parse({"name": "S1", "port": "/dev/ttyS0", "loopback": "25pin"})
    with pytest.raises(ValueError, match="bauds"):
        SERIAL.parse({"name": "S1", "port": "/dev/ttyS0", "bauds": [0]})
    with pytest.raises(ValueError, match="port"):
        SERIAL.parse({"name": "S1"})


def test_sim_all_ok():
    attempt, opened = run_with(SimLoopback(LOOPBACK_TYPES["9pin-full"]))
    assert attempt.status == "PASS", attempt
    assert opened and opened[0][0] == "/dev/ttyS0"
    assert any("9600" in d for d in attempt.details)


def test_broken_dtr_dsr_is_named():
    attempt, _ = run_with(SimLoopback(LOOPBACK_TYPES["9pin-full"], broken_lines={"DTR->DSR"}))
    assert attempt.status == "FAIL"
    assert attempt.message == ("Serial 1: handshake line faulty (DTR->DSR). "
                               "Check the loopback plug; if it is fine, send the unit to repair.")


def test_short_between_outputs_detected():
    # CTS wired to DTR instead of RTS: a 9-pin plug test must notice
    sim = SimLoopback({"DTR": ("CTS", "DSR", "CD", "RI")})
    attempt, _ = run_with(sim)
    assert attempt.status == "FAIL" and "RTS->CTS" in attempt.message


def test_unwired_lines_are_ignored_for_9pin():
    # "9pin" does not test RI, so a plug without RI passes
    sim = SimLoopback(LOOPBACK_TYPES["9pin"])
    attempt, _ = run_with(sim, cfg(loopback="9pin"))
    assert attempt.status == "PASS"


def test_no_echo():
    attempt, _ = run_with(SimLoopback(LOOPBACK_TYPES["9pin-full"], data_fault="no_echo"))
    assert attempt.message.startswith("Serial 1: no data received back. Check the loopback plug")


def test_corrupt():
    attempt, _ = run_with(SimLoopback(LOOPBACK_TYPES["9pin-full"], data_fault="corrupt"))
    assert attempt.message.startswith("Serial 1: data corrupted at 9600 baud.")
    assert any("offset 100" in d for d in attempt.details)


def test_selftest_wording():
    attempt, _ = run_with(SimLoopback(LOOPBACK_TYPES["9pin-full"], data_fault="no_echo"), mode="selftest")
    assert attempt.message == "Loopback plug on Serial 1 faulty or not plugged in"
    attempt, _ = run_with(SimLoopback(LOOPBACK_TYPES["9pin-full"], broken_lines={"RTS->CTS"}),
                          mode="selftest")
    assert attempt.message == "Loopback plug on Serial 1 faulty (RTS->CTS not connected)"


def test_preflight_missing_port(tmp_path):
    ctx = Context(root=tmp_path)
    assert SERIAL.preflight(cfg(), ctx) == ["Serial 1: port /dev/ttyS0 not found"]
    (tmp_path / "dev").mkdir()
    (tmp_path / "dev/ttyS0").write_text("")
    assert SERIAL.preflight(cfg(), ctx) == []


def test_preflight_no_access(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root can access everything")
    (tmp_path / "dev").mkdir()
    port = tmp_path / "dev/ttyS0"
    port.write_text("")
    port.chmod(0o000)
    problems = SERIAL.preflight(cfg(), Context(root=tmp_path))
    assert problems == ["Serial 1: no access to port /dev/ttyS0 (add the user to group dialout)"]


@pytest.fixture
def pty_echo():
    master, slave = os.openpty()
    name = os.ttyname(slave)
    stop = threading.Event()

    def echo():
        while not stop.is_set():
            try:
                data = os.read(master, 4096)
            except OSError:
                return
            os.write(master, data)
    t = threading.Thread(target=echo, daemon=True)
    t.start()
    yield name
    stop.set()
    os.close(slave)
    os.close(master)


def test_real_pyserial_on_pty(pty_echo):
    config = cfg(port=pty_echo, loopback="data-only", bauds=(115200,))
    attempt = SERIAL.run(config, Context(open_serial=open_pyserial), ScriptedUI([]))
    assert attempt.status == "PASS", attempt
