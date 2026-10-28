import shutil

import pytest

from itk.checks import STEP_TYPES
from itk.checks.ethernet import EthernetConfig
from itk.context import CommandResult, Context, run_command
from itk.sim.fakes import FakeRunner, add_netdev
from itk.ui import ScriptedUI

ETH = STEP_TYPES["ethernet"]


def ping_output(loss: float) -> CommandResult:
    out = (f"--- 192.168.100.1 ping statistics ---\n"
           f"5 packets transmitted, {5 - int(loss / 20)} received, {loss:g}% packet loss, time 4005ms\n")
    return CommandResult(0 if loss < 100 else 1, out, "")


def cfg(**kw):
    kw.setdefault("name", "LAN1")
    kw.setdefault("iface", "eth0")
    return EthernetConfig(**kw)


def run(config, tmp_path, ping=None, mode="unit", **netdev):
    add_netdev(tmp_path, config.iface, **netdev)
    runner = FakeRunner({"ping -c": ping} if ping else {})
    attempt = ETH.run(config, Context(root=tmp_path, run=runner, mode=mode), ScriptedUI([]))
    return attempt, runner


def test_parse():
    assert ETH.parse({"name": "LAN1", "iface": "eth0"}) == EthernetConfig("LAN1", "eth0")
    with pytest.raises(ValueError, match="duplex"):
        ETH.parse({"name": "LAN1", "iface": "eth0", "duplex": "double"})
    with pytest.raises(ValueError, match="max_loss_pct"):
        ETH.parse({"name": "LAN1", "iface": "eth0", "max_loss_pct": 120})


def test_link_and_ping_ok(tmp_path):
    attempt, runner = run(cfg(speed=1000, duplex="full", ping="192.168.100.1"), tmp_path, ping_output(0))
    assert attempt.status == "PASS", attempt
    assert runner.calls == [["ping", "-c", "5", "-W", "1", "-I", "eth0", "192.168.100.1"]]
    assert {m.name: m.value for m in attempt.measurements} == {"link speed": 1000, "packet loss": 0}


def test_no_link_skips_ping(tmp_path):
    attempt, runner = run(cfg(speed=1000, ping="192.168.100.1"), tmp_path, ping_output(0),
                          carrier=0, speed=None, duplex=None)
    assert attempt.message == "LAN1: no network link. Check the cable."
    assert runner.calls == []


def test_missing_carrier_file_is_no_link(tmp_path):
    attempt, _ = run(cfg(), tmp_path, carrier=None)
    assert attempt.message == "LAN1: no network link. Check the cable."


def test_wrong_speed(tmp_path):
    attempt, _ = run(cfg(speed=1000), tmp_path, speed=100)
    assert attempt.message == "LAN1: link at 100 Mbit/s, expected 1000"


def test_half_duplex(tmp_path):
    attempt, _ = run(cfg(duplex="full"), tmp_path, duplex="half")
    assert attempt.message == "LAN1: half duplex, expected full"


def test_no_answer(tmp_path):
    attempt, _ = run(cfg(ping="192.168.100.1"), tmp_path, ping_output(100))
    assert attempt.message == "LAN1: no answer from 192.168.100.1"


def test_some_loss(tmp_path):
    attempt, _ = run(cfg(ping="192.168.100.1"), tmp_path, ping_output(20))
    assert attempt.message == "LAN1: 20% packet loss to 192.168.100.1"


def test_loss_within_limit(tmp_path):
    attempt, _ = run(cfg(ping="192.168.100.1", max_loss_pct=20), tmp_path, ping_output(20))
    assert attempt.status == "PASS"


def test_garbage_ping_output(tmp_path):
    attempt, _ = run(cfg(ping="192.168.100.1"), tmp_path,
                     CommandResult(2, "", "ping: unknown iface eth0"))
    assert attempt.status == "FAIL" and any("unknown iface" in d for d in attempt.details)


def test_selftest_wording(tmp_path):
    attempt, _ = run(cfg(), tmp_path, mode="selftest", carrier=0)
    assert attempt.message == "LAN1: network cable or test network faulty"


def test_preflight(tmp_path):
    ctx = Context(root=tmp_path)
    assert ETH.preflight(cfg(), ctx) == ["LAN1: network interface eth0 not found"]
    add_netdev(tmp_path, "eth0")
    assert ETH.preflight(cfg(), ctx) == []


def test_real_ping_localhost():
    if not shutil.which("ping"):
        pytest.skip("ping not installed")
    probe = run_command(["ping", "-c", "1", "-W", "1", "-I", "lo", "127.0.0.1"])
    if probe.returncode != 0:
        pytest.skip(f"ping not permitted here: {probe.stderr.strip()}")
    attempt = ETH.run(cfg(iface="lo", ping="127.0.0.1", ping_count=2), Context(), ScriptedUI([]))
    assert attempt.status == "PASS", attempt
