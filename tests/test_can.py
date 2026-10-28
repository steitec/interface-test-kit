import json
import socket

import pytest

from interface_test_kit.checks import STEP_TYPES
from interface_test_kit.checks.can import TEST_FRAMES, CanConfig, open_socketcan
from interface_test_kit.context import CommandResult, Context
from interface_test_kit.sim.can import SimCanNetwork
from interface_test_kit.sim.fakes import FakeRunner, add_netdev
from interface_test_kit.ui import ScriptedUI

CAN = STEP_TYPES["can"]


def cfg(**kw):
    kw.setdefault("name", "CAN")
    kw.setdefault("pair", ("can0", "can1"))
    return CanConfig(**kw)


def sim_ctx(tmp_path, net=None, runner=None, hardware=False, mode="unit"):
    for iface in ("can0", "can1"):
        add_netdev(tmp_path, iface, hardware=hardware)
    net = net or SimCanNetwork()
    return Context(root=tmp_path, open_can=net.open, run=runner or FakeRunner({}), mode=mode)


def run(config, ctx):
    return CAN.run(config, ctx, ScriptedUI([]))


def test_parse():
    assert CAN.parse({"name": "CAN", "pair": ["can0", "can1"]}) == CanConfig("CAN", ("can0", "can1"))
    with pytest.raises(ValueError, match="pair"):
        CAN.parse({"name": "CAN", "pair": ["can0"]})
    with pytest.raises(ValueError, match="bitrate"):
        CAN.parse({"name": "CAN", "pair": ["can0", "can1"], "bitrate": -1})


def test_sim_pass(tmp_path):
    attempt = run(cfg(), sim_ctx(tmp_path))
    assert attempt.status == "PASS", attempt
    assert any(f"{len(TEST_FRAMES)} frames" in d for d in attempt.details)


def test_virtual_interfaces_get_no_ip_commands(tmp_path):
    runner = FakeRunner({})
    attempt = run(cfg(bitrate=500000), sim_ctx(tmp_path, runner=runner))
    assert attempt.status == "PASS" and runner.calls == []


def test_dropped_frames_name_direction(tmp_path):
    attempt = run(cfg(), sim_ctx(tmp_path, SimCanNetwork(drop={"can0"})))
    assert attempt.message == "CAN: no frames from can0 to can1. Check the CAN cable and termination."


def test_reverse_direction(tmp_path):
    attempt = run(cfg(), sim_ctx(tmp_path, SimCanNetwork(drop={"can1"})))
    assert attempt.message == "CAN: no frames from can1 to can0. Check the CAN cable and termination."


def test_corrupted_frames(tmp_path):
    class Corrupting(SimCanNetwork):
        def deliver(self, sender, frame):
            arb_id, data, ext = frame
            super().deliver(sender, (arb_id, bytes(b ^ 0xFF for b in data), ext))
    attempt = run(cfg(), sim_ctx(tmp_path, Corrupting()))
    assert attempt.message == "CAN: frames from can0 to can1 corrupted"


def test_selftest_wording(tmp_path):
    attempt = run(cfg(), sim_ctx(tmp_path, SimCanNetwork(drop={"can0"}), mode="selftest"))
    assert attempt.message == "CAN cable between can0 and can1 faulty"


def ip_state(state):
    def respond(args):
        return CommandResult(0, json.dumps([{"ifname": args[-1], "linkinfo": {
            "info_kind": "can", "info_data": {"state": state}}}]), "")
    return respond


def test_hardware_sets_bitrate_and_checks_state(tmp_path):
    runner = FakeRunner({"ip link": CommandResult(0, "", ""), "ip -d": ip_state("ERROR-ACTIVE")})
    attempt = run(cfg(bitrate=500000), sim_ctx(tmp_path, runner=runner, hardware=True))
    assert attempt.status == "PASS", attempt
    assert runner.calls[:3] == [["ip", "link", "set", "can0", "down"],
                                ["ip", "link", "set", "can0", "type", "can", "bitrate", "500000"],
                                ["ip", "link", "set", "can0", "up"]]
    assert ["ip", "-d", "-j", "link", "show", "can1"] in runner.calls


def test_bus_off_fails(tmp_path):
    runner = FakeRunner({"ip link": CommandResult(0, "", ""), "ip -d": ip_state("BUS-OFF")})
    attempt = run(cfg(), sim_ctx(tmp_path, runner=runner, hardware=True))
    assert attempt.message.startswith("CAN: can0 in error state BUS-OFF. Check the CAN cable")


def test_bitrate_command_failure(tmp_path):
    runner = FakeRunner({"ip link": CommandResult(2, "", "RTNETLINK answers: Operation not permitted")})
    attempt = run(cfg(bitrate=500000), sim_ctx(tmp_path, runner=runner, hardware=True))
    assert attempt.status == "FAIL"
    assert any("Operation not permitted" in d for d in attempt.details)


def test_preflight(tmp_path, monkeypatch):
    ctx = Context(root=tmp_path)
    assert CAN.preflight(cfg(), ctx) == ["CAN: network interface can0 not found",
                                         "CAN: network interface can1 not found"]
    add_netdev(tmp_path, "can0")
    add_netdev(tmp_path, "can1")
    monkeypatch.setattr("os.geteuid", lambda: 1000)
    assert CAN.preflight(cfg(), ctx) == []
    assert CAN.preflight(cfg(bitrate=500000), ctx) == ["CAN: setting the bitrate needs root"]


@pytest.mark.vcan
def test_vcan_roundtrip():
    try:
        socket.if_nametoindex("vcan0")
    except OSError:
        pytest.skip("no vcan0 interface")
    attempt = run(cfg(pair=("vcan0", "vcan0")), Context(open_can=open_socketcan))
    assert attempt.status == "PASS", attempt


def test_error_warning_after_cable_fix_passes(tmp_path):
    # frames got through both ways; a TX error counter still counting down is fine
    runner = FakeRunner({"ip link": CommandResult(0, "", ""), "ip -d": ip_state("ERROR-WARNING")})
    attempt = run(cfg(), sim_ctx(tmp_path, runner=runner, hardware=True))
    assert attempt.status == "PASS", attempt


def test_error_passive_fails_with_operator_advice(tmp_path):
    runner = FakeRunner({"ip link": CommandResult(0, "", ""), "ip -d": ip_state("ERROR-PASSIVE")})
    attempt = run(cfg(), sim_ctx(tmp_path, runner=runner, hardware=True))
    assert attempt.message == ("CAN: can0 in error state ERROR-PASSIVE. "
                               "Check the CAN cable and termination, then retry.")


def test_stale_frames_from_earlier_attempt_are_ignored(tmp_path):
    net = SimCanNetwork()
    ctx = sim_ctx(tmp_path, net)
    original = net.open

    def open_with_stale(iface):
        bus = original(iface)
        bus.queue.append((0x7FF, b"old", False))  # left over from the attempt without cable
        return bus
    ctx.open_can = open_with_stale
    assert run(cfg(), ctx).status == "PASS"


def test_same_interface_twice_is_rejected():
    with pytest.raises(ValueError, match="two different"):
        CAN.parse({"name": "CAN", "pair": ["can0", "can0"]})
