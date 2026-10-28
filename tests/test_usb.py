import os

import pytest

from itk.checks import STEP_TYPES
from itk.checks.usb import UsbConfig, find_sticks
from itk.context import Context
from itk.sim.fakes import FakeRunner, add_usb_stick, lsblk_result
from itk.ui import ScriptedUI

USB = STEP_TYPES["usb"]


def world(tmp_path, nodes, clock=None, mode="unit"):
    runner = FakeRunner({"lsblk -J": lsblk_result(nodes)})
    kw = {"clock": clock} if clock else {}
    return Context(root=tmp_path, run=runner, mode=mode, **kw)


def cfg(**kw):
    kw.setdefault("name", "USB")
    kw.setdefault("count", 2)
    kw.setdefault("size_mb", 2)
    return UsbConfig(**kw)


def two_sticks(tmp_path, speed=5000):
    return [add_usb_stick(tmp_path, "sdb1", "ITKTEST", "1-1", speed, "/media/itk1"),
            add_usb_stick(tmp_path, "sdc1", "ITKTEST2", "2-1", speed, "/media/itk2")]


def run(config, ctx):
    return USB.run(config, ctx, ScriptedUI([]))


def test_parse_defaults():
    assert USB.parse({"name": "USB", "count": 2}) == UsbConfig("USB", 2)
    with pytest.raises(ValueError, match="count"):
        USB.parse({"name": "USB", "count": 0})
    with pytest.raises(ValueError, match="count"):
        USB.parse({"name": "USB"})


def test_find_sticks(tmp_path):
    ctx = world(tmp_path, two_sticks(tmp_path))
    sticks = find_sticks(cfg(), ctx)
    assert [(s.device, s.usb_port, s.speed_mbps, s.mountpoint) for s in sticks] == [
        ("/dev/sdb1", "1-1", 5000, "/media/itk1"), ("/dev/sdc1", "2-1", 5000, "/media/itk2")]


def test_two_sticks_pass(tmp_path):
    ctx = world(tmp_path, two_sticks(tmp_path))
    attempt = run(cfg(min_write_mbs=1, min_read_mbs=1, min_speed_mbps=5000, ports=("1-1", "2-1")), ctx)
    assert attempt.status == "PASS", attempt
    assert len(attempt.measurements) == 6
    assert {m.name for m in attempt.measurements} >= {"1-1 write", "1-1 read", "1-1 USB speed"}
    assert not list(tmp_path.rglob("itk-test.bin"))


def test_ignores_unlabelled_and_non_usb(tmp_path):
    nodes = [add_usb_stick(tmp_path, "sdb1", "DATA", "1-1", 5000, "/media/data"),
             add_usb_stick(tmp_path, "sda1", "ITKTEST", "3-1", 5000, "/media/sys", tran="sata")]
    attempt = run(cfg(), world(tmp_path, nodes))
    assert attempt.status == "FAIL"
    assert attempt.message == ("USB: found 0 test stick(s), expected 2. "
                               "Insert the test sticks labelled ITKTEST.")
    assert not list((tmp_path / "media").rglob("*.bin"))
    assert any("DATA" in d for d in attempt.details)


def test_unmounted_stick_fails(tmp_path):
    nodes = [add_usb_stick(tmp_path, "sdb1", "ITKTEST", "1-1", 5000, None)]
    attempt = run(cfg(count=1), world(tmp_path, nodes))
    assert attempt.message == "USB: test stick in port 1-1 is not mounted"


def test_wrong_speed(tmp_path):
    attempt = run(cfg(min_speed_mbps=5000), world(tmp_path, two_sticks(tmp_path, speed=480)))
    assert attempt.status == "FAIL"
    assert attempt.message == "USB: port 1-1 runs at 480 Mbit/s, expected at least 5000"


def test_slow_via_clock(tmp_path):
    ticks = iter(range(1000))
    ctx = world(tmp_path, two_sticks(tmp_path), clock=lambda: float(next(ticks)))
    attempt = run(cfg(min_write_mbs=10), ctx)
    assert attempt.message == "USB: port 1-1 too slow"
    m = next(m for m in attempt.measurements if m.name == "1-1 write")
    assert m.value == pytest.approx(2.0) and not m.passed


def test_slow_selftest_wording(tmp_path):
    ticks = iter(range(1000))
    ctx = world(tmp_path, two_sticks(tmp_path), clock=lambda: float(next(ticks)), mode="selftest")
    assert run(cfg(min_write_mbs=10), ctx).message == "Test stick /dev/sdb1 faulty or too slow"


def test_expected_port_missing(tmp_path):
    nodes = [add_usb_stick(tmp_path, "sdb1", "ITKTEST", "1-2", 5000, "/media/itk1")]
    attempt = run(cfg(count=1, ports=("1-1", "1-2")), world(tmp_path, nodes))
    assert attempt.message == "USB: no test stick in port 1-1"


def test_readonly_mount(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root ignores permissions")
    nodes = [add_usb_stick(tmp_path, "sdb1", "ITKTEST", "1-1", 5000, "/media/itk1")]
    (tmp_path / "media/itk1").chmod(0o555)
    try:
        attempt = run(cfg(count=1), world(tmp_path, nodes))
    finally:
        (tmp_path / "media/itk1").chmod(0o755)
    assert attempt.message == "USB: could not write to the test stick (1-1): full or write-protected"


def test_corrupt_readback(tmp_path, monkeypatch):
    import itk.checks.usb as usb
    nodes = [add_usb_stick(tmp_path, "sdb1", "ITKTEST", "1-1", 5000, "/media/itk1")]
    real = usb._read_back

    def flaky(path, size_mb, clock):
        path.write_bytes(b"\0" * (size_mb * usb.BLOCK))
        return real(path, size_mb, clock)
    monkeypatch.setattr(usb, "_read_back", flaky)
    attempt = run(cfg(count=1), world(tmp_path, nodes))
    assert attempt.message == "USB: stick data corrupted (1-1)"
    assert not (tmp_path / "media/itk1/itk-test.bin").exists()


def test_lsblk_failure(tmp_path):
    ctx = Context(root=tmp_path, run=FakeRunner({}))
    attempt = run(cfg(), ctx)
    assert attempt.status == "FAIL" and any("lsblk" in d for d in attempt.details)


def test_symlink_test_file_is_not_followed(tmp_path):
    nodes = [add_usb_stick(tmp_path, "sdb1", "ITKTEST", "1-1", 5000, "/media/itk1")]
    victim = tmp_path / "etc-passwd"
    victim.write_text("precious")
    (tmp_path / "media/itk1/itk-test.bin").symlink_to(victim)
    attempt = run(cfg(count=1), world(tmp_path, nodes))
    assert attempt.status == "PASS", attempt
    assert victim.read_text() == "precious"


def test_stick_unmounted_before_write_is_not_written(tmp_path):
    nodes = [add_usb_stick(tmp_path, "sdb1", "ITKTEST", "1-1", 5000, "/media/itk1")]
    gone = [add_usb_stick(tmp_path / "x", "sdb1", "ITKTEST", "1-1", 5000, None)]
    answers = iter([lsblk_result(nodes), lsblk_result(gone)])
    ctx = Context(root=tmp_path, run=FakeRunner({"lsblk -J": lambda args: next(answers)}))
    attempt = run(cfg(count=1), ctx)
    assert attempt.message == "USB: test stick in port 1-1 is not mounted"
    assert not list((tmp_path / "media").rglob("*.bin"))


def test_mountpoint_on_other_device_is_not_written(tmp_path, monkeypatch):
    import itk.checks.usb as usb
    nodes = [add_usb_stick(tmp_path, "sdb1", "ITKTEST", "1-1", 5000, "/media/itk1")]
    monkeypatch.setattr(usb, "_same_device", lambda ctx, stick: False)
    attempt = run(cfg(count=1), world(tmp_path, nodes))
    assert attempt.message == "USB: test stick in port 1-1 is not mounted"
    assert not list((tmp_path / "media").rglob("*.bin"))
