import io
import json
import textwrap

import pytest

from interface_test_kit.cli import main
from interface_test_kit.context import Context
from interface_test_kit.session import run_session
from interface_test_kit.station import Station
from interface_test_kit.ui import ScriptedUI

HINT = "Same failure on several units? Run the equipment self-test."


def setup_station(tmp_path, profiles: dict[str, str], **kw) -> Station:
    pdir = tmp_path / "profiles"
    pdir.mkdir()
    for name, text in profiles.items():
        (pdir / name).write_text(textwrap.dedent(text).lstrip("\n"))
    return Station(report_dir=tmp_path / "share", profile_dir=pdir, spool_dir=tmp_path / "spool",
                   name="EOL-1", **kw)


def share(tmp_path):
    d = tmp_path / "share"
    d.mkdir(exist_ok=True)
    return d


UNIT = """
name: EPC-24 B
version: 3
serial_number: {pattern: "^EPC-24-\\\\d{5}$"}
setup: Plug in the loopback plugs.
steps:
  - {type: fake, name: Serial 1, outcomes: [PASS]}
  - {type: confirm, name: Power LED, prompt: "Is the power LED green?"}
"""


def results(tmp_path):
    return [json.loads(p.read_text()) for p in (tmp_path / "share").rglob("result.json")]


def test_full_pass_writes_report(tmp_path):
    share(tmp_path)
    st = setup_station(tmp_path, {"b.yaml": UNIT})
    ui = ScriptedUI(["EPC-24-00001", True, True])
    run = run_session(st, Context(root=tmp_path), ui)
    assert run.status == "PASS" and run.serial_number == "EPC-24-00001"
    assert [s.status for s in run.steps] == ["PASS", "PASS"]
    assert "wait_key: Plug in the loopback plugs.\nPress Enter when ready." in ui.log
    assert "banner: PASS" in ui.log
    assert any(line.startswith("info: Report saved: ") for line in ui.log)
    assert results(tmp_path)[0]["profile"] == {"name": "EPC-24 B", "version": 3}


def test_serial_reasked_and_stripped(tmp_path):
    share(tmp_path)
    st = setup_station(tmp_path, {"b.yaml": UNIT})
    ui = ScriptedUI(["", "BAD", "EPC-24-00001\r ", True, True])
    run = run_session(st, Context(root=tmp_path), ui)
    assert run.serial_number == "EPC-24-00001"
    assert ui.log.count("info: The serial number does not match the expected format. Try again.") == 2


def detect_profile(name, product):
    return f"""
name: {name}
version: 1
detect: {{dmi_product_name: {product}}}
steps: [{{type: fake, name: A, outcomes: [PASS]}}]
"""


def test_detect_picks_profile(tmp_path):
    share(tmp_path)
    st = setup_station(tmp_path, {"a.yaml": detect_profile("EPC-24 A", "EPC-24A"),
                                  "b.yaml": detect_profile("EPC-24 B", "EPC-24B")})
    dmi = tmp_path / "sys/class/dmi/id"
    dmi.mkdir(parents=True)
    (dmi / "product_name").write_text("EPC-24B\n")
    ui = ScriptedUI(["SN1", True])
    run = run_session(st, Context(root=tmp_path), ui)
    assert run.profile_name == "EPC-24 B"
    assert not any("Choose the profile number" in line for line in ui.log)


def test_profile_list_when_not_detected(tmp_path):
    share(tmp_path)
    st = setup_station(tmp_path, {"a.yaml": detect_profile("EPC-24 A", "EPC-24A"),
                                  "b.yaml": detect_profile("EPC-24 B", "EPC-24B")})
    ui = ScriptedUI(["SN1", "9", "x", "2", True])
    run = run_session(st, Context(root=tmp_path), ui)
    assert run.profile_name == "EPC-24 B"
    assert sum("Choose the profile number" in line for line in ui.log) == 3
    assert "info:   1  EPC-24 A (v1)" in ui.log


def test_profile_no_goes_back_to_list(tmp_path):
    share(tmp_path)
    st = setup_station(tmp_path, {"a.yaml": detect_profile("EPC-24 A", "X"),
                                  "b.yaml": detect_profile("EPC-24 B", "Y")})
    ui = ScriptedUI(["SN1", "1", False, "2", True])
    assert run_session(st, Context(root=tmp_path), ui).profile_name == "EPC-24 B"


def test_single_profile_rejected_aborts(tmp_path):
    st = setup_station(tmp_path, {"b.yaml": UNIT})
    with pytest.raises(ValueError, match="Profile not confirmed"):
        run_session(st, Context(root=tmp_path), ScriptedUI(["EPC-24-00001", False]))


REF = """
name: Reference EPC-24
version: 1
reference: true
steps: [{type: fake, name: Serial 1, equipment: Loopback plug number, outcomes: [PASS]}]
"""


def test_selftest_uses_reference_profiles_only(tmp_path):
    share(tmp_path)
    st = setup_station(tmp_path, {"b.yaml": UNIT, "ref.yaml": REF})
    ui = ScriptedUI([True, "LB-07"])
    run = run_session(st, Context(root=tmp_path, mode="selftest"), ui)
    assert run.mode == "selftest" and run.serial_number == "selftest"
    assert run.profile_name == "Reference EPC-24"
    assert run.steps[0].equipment_id == "LB-07"
    assert not any("serial number" in line for line in ui.log)
    assert list((tmp_path / "share/selftest").iterdir())


def test_no_profiles(tmp_path):
    st = setup_station(tmp_path, {"ref.yaml": REF})
    with pytest.raises(ValueError, match="No profiles found"):
        run_session(st, Context(root=tmp_path), ScriptedUI([]))


FAILING = """
name: F
version: 1
steps: [{type: fake, name: USB, outcomes: [FAIL]}, {type: fake, name: LAN1, outcomes: [PASS]}]
"""


def test_fail_shows_selftest_hint(tmp_path):
    share(tmp_path)
    st = setup_station(tmp_path, {"f.yaml": FAILING})
    ui = ScriptedUI(["SN1", True, False])
    run = run_session(st, Context(root=tmp_path), ui)
    assert run.status == "FAIL" and f"info: {HINT}" in ui.log
    assert ui.log.index("banner: FAIL") < ui.log.index(f"info: {HINT}")


def test_operator_asked_when_configured(tmp_path):
    share(tmp_path)
    st = setup_station(tmp_path, {"f.yaml": FAILING.replace("FAIL]", "PASS]")}, ask_operator=True)
    run = run_session(st, Context(root=tmp_path), ScriptedUI(["SN1", "Anna", True]))
    assert run.operator == "Anna"


INTERRUPTED = """
name: I
version: 1
steps: [{type: fake, name: A, outcomes: [PASS]}, {type: fake, name: B, outcomes: [interrupt]},
        {type: fake, name: C, outcomes: [PASS]}]
"""


def test_ctrl_c_mid_run_writes_aborted(tmp_path):
    share(tmp_path)
    st = setup_station(tmp_path, {"i.yaml": INTERRUPTED})
    ui = ScriptedUI(["SN1", True])
    run = run_session(st, Context(root=tmp_path), ui)
    assert run.status == "ABORTED" and [s.id for s in run.steps] == ["a"]
    assert results(tmp_path)[0]["status"] == "ABORTED"
    assert "banner: ABORTED" in ui.log


PROBLEM = """
name: P
version: 1
steps: [{type: fake, name: A, problems: ["Serial 2: port /dev/ttyS1 not found"]}]
"""


def test_preflight_problem_aborts_before_steps(tmp_path):
    share(tmp_path)
    st = setup_station(tmp_path, {"p.yaml": PROBLEM})
    ui = ScriptedUI(["SN1", True])
    run = run_session(st, Context(root=tmp_path), ui)
    assert run.status == "ABORTED" and run.steps == []
    assert "info: Serial 2: port /dev/ttyS1 not found" in ui.log
    assert not any(line.startswith("step_started") for line in ui.log)


def test_rma_and_only_in_result(tmp_path):
    share(tmp_path)
    st = setup_station(tmp_path, {"f.yaml": FAILING})
    run = run_session(st, Context(root=tmp_path), ScriptedUI(["SN1", True]), rma="RMA-1", only=["lan1"])
    assert run.rma == "RMA-1" and run.only == ["lan1"] and [s.id for s in run.steps] == ["lan1"]
    assert run.status == "PASS"
    assert any("RMA-1" in p.name for p in (tmp_path / "share").iterdir())


def test_spooled_reports_are_uploaded_first(tmp_path):
    st = setup_station(tmp_path, {"f.yaml": FAILING.replace("FAIL]", "PASS]")})
    run_session(st, Context(root=tmp_path), ScriptedUI(["SN1", True]))  # share missing → spooled
    share(tmp_path)
    ui = ScriptedUI(["SN2", True])
    run_session(st, Context(root=tmp_path), ui)
    assert "info: Uploaded 1 saved report(s) to the network drive." in ui.log
    assert len(results(tmp_path)) == 2


def write_station(tmp_path, st: Station):
    path = tmp_path / "station.yaml"
    path.write_text(f"report_dir: {st.report_dir}\nprofile_dir: {st.profile_dir}\n"
                    f"spool_dir: {st.spool_dir}\nname: EOL-1\n")
    return str(path)


def test_cli_run_exit_codes(tmp_path, monkeypatch):
    share(tmp_path)
    st = setup_station(tmp_path, {"f.yaml": FAILING})
    station = write_station(tmp_path, st)
    monkeypatch.setattr("sys.stdin", io.StringIO("SN1\ny\nn\n"))
    assert main(["run", "--station", station]) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO("SN1\ny\n"))
    assert main(["run", "--station", station, "--only", "lan1", "--rma", "RMA-9"]) == 0


def test_cli_ctrl_c_before_result(tmp_path, monkeypatch, capsys):
    st = setup_station(tmp_path, {"f.yaml": FAILING})
    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # EOF at the serial prompt
    assert main(["run", "--station", write_station(tmp_path, st)]) == 2
    assert "Aborted." in capsys.readouterr().out


def test_cli_ctrl_c_mid_run(tmp_path, monkeypatch):
    share(tmp_path)
    st = setup_station(tmp_path, {"i.yaml": INTERRUPTED})
    monkeypatch.setattr("sys.stdin", io.StringIO("SN1\ny\n"))
    assert main(["run", "--station", write_station(tmp_path, st)]) == 2


def test_cli_profile_error_exit_2(tmp_path, monkeypatch, capsys):
    st = setup_station(tmp_path, {"bad.yaml": "name: X\nversion: 1\nsteps: [{type: laser, name: A}]\n"})
    monkeypatch.setattr("sys.stdin", io.StringIO("SN1\n"))
    assert main(["run", "--station", write_station(tmp_path, st)]) == 2
    out = capsys.readouterr().out
    assert out.startswith("Error:") and "laser" in out


def test_cli_missing_station(tmp_path, capsys):
    assert main(["run", "--station", str(tmp_path / "nope.yaml")]) == 2
    assert "Error:" in capsys.readouterr().out


def test_wrong_profile_number_gets_a_hint(tmp_path):
    share(tmp_path)
    st = setup_station(tmp_path, {"a.yaml": detect_profile("EPC-24 A", "X"),
                                  "b.yaml": detect_profile("EPC-24 B", "Y")})
    ui = ScriptedUI(["SN1", "9", "2", True])
    run_session(st, Context(root=tmp_path), ui)
    assert "info: Enter a number from 1 to 2." in ui.log
