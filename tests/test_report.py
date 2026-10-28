import json
import os
from datetime import datetime, timezone

import pytest

from itk.cli import main
from itk.model import Attempt, Measurement, RunResult, StepResult
from itk.report import folder_name, render_text, report_reachable, sync_spool, write_run
from itk.station import Station

T0 = datetime(2026, 10, 28, 9, 0, 0, tzinfo=timezone.utc)


def make_run(serial="EPC-24-00001", rma=None, mode="unit", status="FAIL", steps=None):
    if steps is None:
        steps = [
            StepResult("usb", "USB", "usb", "FAIL",
                       [Attempt.fail("USB: port 1-2 too slow", details=["write 3.1 MB/s"],
                                     measurements=[Measurement("1-2 write", 3.1, "MB/s", low=10)])]),
            StepResult("lan1", "LAN1", "ethernet", "PASS",
                       [Attempt.fail("LAN1: no network link. Check the cable."), Attempt.ok(), Attempt.ok()]),
        ]
    return RunResult(mode, serial, rma, "EPC-24 B", 3, "EOL-1", "Anna", T0, T0, "0.1.0", steps, status)


def station(tmp_path, **kw):
    kw.setdefault("report_dir", tmp_path / "share")
    kw.setdefault("spool_dir", tmp_path / "spool")
    return Station(name="EOL-1", **kw)


def test_folder_name_sanitized():
    run = make_run(serial="EPC/24 00001\r", rma="RMA-2026/0042")
    assert folder_name(run) == "EPC_24_00001__RMA-2026_0042_20261028-090000"


def test_folder_name_no_hidden_or_parent():
    assert folder_name(make_run(serial="..")).startswith("_")
    assert "/" not in folder_name(make_run(serial="../../etc"))


def test_folder_name_selftest():
    assert folder_name(make_run(mode="selftest", serial="selftest")) == "selftest_EOL-1_20261028-090000"


def test_write_run_to_share(tmp_path):
    st = station(tmp_path)
    st.report_dir.mkdir()
    path, spooled = write_run(make_run(), st)
    assert not spooled and path.parent == st.report_dir
    data = json.loads((path / "result.json").read_text())
    assert data["serial_number"] == "EPC-24-00001" and data["status"] == "FAIL"
    assert "Result: FAIL" in (path / "report.txt").read_text()


def test_selftest_goes_to_subfolder(tmp_path):
    st = station(tmp_path)
    st.report_dir.mkdir()
    path, _ = write_run(make_run(mode="selftest", serial="selftest"), st)
    assert path.parent == st.report_dir / "selftest"


def test_unreachable_share_spools(tmp_path):
    st = station(tmp_path)  # report_dir does not exist
    path, spooled = write_run(make_run(), st)
    assert spooled and path.parent == st.spool_dir
    assert (path / "result.json").exists()


def test_write_error_spools(tmp_path, monkeypatch):
    st = station(tmp_path)
    st.report_dir.mkdir()
    real_mkdir = type(st.report_dir).mkdir

    def mkdir(self, *a, **kw):
        if self.parent == st.report_dir:
            raise OSError("Input/output error")
        return real_mkdir(self, *a, **kw)
    monkeypatch.setattr(type(st.report_dir), "mkdir", mkdir)
    path, spooled = write_run(make_run(), st)
    assert spooled and (path / "report.txt").exists()


def test_mount_point_must_be_mounted(tmp_path, monkeypatch):
    mount = tmp_path / "share"
    st = station(tmp_path, report_dir=mount / "itk", mount_point=mount)
    st.report_dir.mkdir(parents=True)
    # share not mounted: the folder sits on a local filesystem (even one mounted at /data)
    monkeypatch.setattr(os.path, "ismount", lambda p: str(p) in ("/", str(tmp_path.resolve())))
    assert not report_reachable(st)
    monkeypatch.setattr(os.path, "ismount", lambda p: str(p) in ("/", str(mount.resolve())))
    assert report_reachable(st)


def test_report_dir_outside_mount_point_is_rejected(tmp_path, monkeypatch):
    st = station(tmp_path, mount_point=tmp_path / "share")
    (tmp_path / "share").mkdir()
    st2 = station(tmp_path, report_dir=tmp_path / "elsewhere", mount_point=tmp_path / "share")
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.setattr(os.path, "ismount", lambda p: True)
    assert report_reachable(st) and not report_reachable(st2)


def test_sync_moves_and_keeps_on_failure(tmp_path):
    st = station(tmp_path)
    write_run(make_run(), st)                                   # spooled
    write_run(make_run(mode="selftest", serial="selftest"), st)  # spooled
    assert sync_spool(st) == []                                 # share still missing
    assert len(list(st.spool_dir.rglob("result.json"))) == 2
    st.report_dir.mkdir()
    moved = sync_spool(st)
    assert len(moved) == 2
    assert (st.report_dir / "selftest").is_dir()
    assert list(st.spool_dir.rglob("result.json")) == []
    assert len(list(st.report_dir.rglob("result.json"))) == 2


def test_render_text_shows_retries_and_limits():
    text = render_text(make_run(rma="RMA-1"))
    for needle in ["Serial number: EPC-24-00001", "RMA: RMA-1", "Profile: EPC-24 B v3",
                   "Station: EOL-1", "Operator: Anna", "Tool version: 0.1.0", "Result: FAIL",
                   "[FAIL] USB", "1-2 write", "3.1 MB/s", "out of limits", "write 3.1 MB/s",
                   "[PASS] LAN1", "(passed after retry)", "attempt 1: FAIL"]:
        assert needle in text, needle


def test_render_text_without_rma_has_no_rma_line():
    assert "RMA:" not in render_text(make_run())


def test_sync_cli(tmp_path, capsys):
    st = station(tmp_path)
    (tmp_path / "station.yaml").write_text(
        f"report_dir: {st.report_dir}\nspool_dir: {st.spool_dir}\n")
    write_run(make_run(), st)
    assert main(["sync", "--station", str(tmp_path / "station.yaml")]) == 2
    st.report_dir.mkdir()
    assert main(["sync", "--station", str(tmp_path / "station.yaml")]) == 0
    assert str(st.report_dir) in capsys.readouterr().out


def test_same_second_runs_do_not_overwrite(tmp_path):
    st = station(tmp_path)
    st.report_dir.mkdir()
    first, _ = write_run(make_run(status="FAIL"), st)
    second, _ = write_run(make_run(status="PASS"), st)
    assert first != second and second.name == first.name + "-2"
    assert json.loads((first / "result.json").read_text())["status"] == "FAIL"


def test_very_long_serial_is_shortened(tmp_path):
    st = station(tmp_path)
    st.report_dir.mkdir()
    path, spooled = write_run(make_run(serial="X" * 400), st)
    assert not spooled and len(path.name) <= 120
