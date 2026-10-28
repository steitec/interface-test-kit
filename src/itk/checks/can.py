"""CAN check in pair mode: two CAN ports wired together exchange test frames both ways."""

from __future__ import annotations

import json
import os
import socket
import struct
from dataclasses import dataclass
from typing import Protocol

from ..model import Attempt
from . import CheckType, fields, register

# (id, data, extended): empty, short and full standard frames, one extended frame
TEST_FRAMES = [(0x123, b"", False), (0x123, bytes([0x55]), False),
               (0x7FF, bytes(range(8)), False), (0x1ABCDE0, bytes([0xAA] * 8), True)]

# ERROR-WARNING is fine: after a failed attempt (cable missing) the TX error counter
# only counts down by one per good frame, so it stays above 96 for a while.
GOOD_STATES = ("ERROR-ACTIVE", "ERROR-WARNING")

_FRAME = struct.Struct("=IB3x8s")
_EFF_FLAG = 0x80000000
_RTR_FLAG = 0x40000000
_ERR_FLAG = 0x20000000


class CanBus(Protocol):
    def send(self, arb_id: int, data: bytes, extended: bool) -> None: ...
    def recv(self, timeout: float) -> tuple[int, bytes, bool] | None: ...
    def close(self) -> None: ...


class SocketCanBus:
    def __init__(self, iface: str):
        self._sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self._sock.bind((iface,))

    def send(self, arb_id: int, data: bytes, extended: bool) -> None:
        can_id = arb_id | _EFF_FLAG if extended else arb_id
        self._sock.send(_FRAME.pack(can_id, len(data), data.ljust(8, b"\0")))

    def recv(self, timeout: float) -> tuple[int, bytes, bool] | None:
        self._sock.settimeout(timeout)
        while True:
            try:
                raw = self._sock.recv(_FRAME.size)
            except socket.timeout:
                return None
            can_id, length, data = _FRAME.unpack(raw)
            if can_id & (_ERR_FLAG | _RTR_FLAG):
                continue
            extended = bool(can_id & _EFF_FLAG)
            return can_id & (0x1FFFFFFF if extended else 0x7FF), data[:length], extended

    def close(self) -> None:
        self._sock.close()


def open_socketcan(iface: str) -> CanBus:
    return SocketCanBus(iface)


@dataclass(frozen=True)
class CanConfig:
    name: str
    pair: tuple[str, str]
    bitrate: int | None = None
    timeout_s: float = 1.0


def parse(raw: dict) -> CanConfig:
    f = fields(raw, {"pair"}, {"bitrate": None, "timeout_s": 1.0})
    pair = f["pair"]
    if not isinstance(pair, list) or len(pair) != 2:
        raise ValueError("pair: must list exactly two CAN interfaces, e.g. [can0, can1]")
    if pair[0] == pair[1]:
        # one interface talking to itself passes through the kernel's local loopback, no cable needed
        raise ValueError("pair: must name two different CAN interfaces")
    rate = f["bitrate"]
    if rate is not None and (isinstance(rate, bool) or not isinstance(rate, int) or rate <= 0):
        raise ValueError("bitrate: must be a positive whole number, e.g. 500000")
    t = f["timeout_s"]
    if isinstance(t, bool) or not isinstance(t, (int, float)) or t <= 0:
        raise ValueError("timeout_s: must be a positive number")
    return CanConfig(str(f["name"]), (str(pair[0]), str(pair[1])), rate, float(t))


def _is_hardware(ctx, iface: str) -> bool:
    return ctx.path(f"/sys/class/net/{iface}/device").exists()


def _ifaces(config: CanConfig) -> list[str]:
    return list(dict.fromkeys(config.pair))


def preflight(config: CanConfig, ctx) -> list[str]:
    problems = [f"CAN: network interface {i} not found" for i in _ifaces(config)
                if not ctx.path(f"/sys/class/net/{i}").is_dir()]
    if not problems and config.bitrate and os.geteuid() != 0 and \
            any(_is_hardware(ctx, i) for i in _ifaces(config)):
        problems.append("CAN: setting the bitrate needs root")
    return problems


def _set_bitrate(ctx, iface: str, bitrate: int, details: list[str]) -> bool:
    for args in (["ip", "link", "set", iface, "down"],
                 ["ip", "link", "set", iface, "type", "can", "bitrate", str(bitrate)],
                 ["ip", "link", "set", iface, "up"]):
        result = ctx.run(args)
        if result.returncode != 0:
            details.append(f"{' '.join(args)}: {result.stderr.strip()}")
            return False
    details.append(f"{iface}: bitrate {bitrate}")
    return True


def _state(ctx, iface: str) -> str | None:
    result = ctx.run(["ip", "-d", "-j", "link", "show", iface])
    try:
        return json.loads(result.stdout)[0]["linkinfo"]["info_data"]["state"]
    except (ValueError, LookupError, TypeError):
        return None


def _drain(bus: CanBus) -> None:
    """Drop frames still queued from an earlier attempt."""
    for _ in range(100):
        if bus.recv(0.05) is None:
            return


def _exchange(tx: CanBus, rx: CanBus, timeout: float) -> str | None:
    """Send every test frame from tx to rx. Returns 'missing', 'corrupt' or None."""
    for frame in TEST_FRAMES:
        tx.send(*frame)
        got = rx.recv(timeout)
        if got is None:
            return "missing"
        if got != frame:
            return "corrupt"
    return None


def run(config: CanConfig, ctx, ui) -> Attempt:
    a, b = config.pair
    details: list[str] = []
    cable = f"CAN cable between {a} and {b} faulty"
    hardware = [i for i in _ifaces(config) if _is_hardware(ctx, i)]
    if config.bitrate:
        for iface in hardware:
            if not _set_bitrate(ctx, iface, config.bitrate, details):
                return Attempt.fail(f"CAN: could not set up {iface}. Tell the test engineer.",
                                    details=details)
    bus_a = ctx.open_can(a)
    try:
        bus_b = ctx.open_can(b)
        try:
            _drain(bus_a)
            _drain(bus_b)
            for tx_name, tx, rx_name, rx in ((a, bus_a, b, bus_b), (b, bus_b, a, bus_a)):
                problem = _exchange(tx, rx, config.timeout_s)
                if problem == "missing":
                    details.append(f"{tx_name} -> {rx_name}: frame not received within {config.timeout_s:g} s")
                    return Attempt.fail(ctx.say(f"CAN: no frames from {tx_name} to {rx_name}. "
                                                "Check the CAN cable and termination.", cable), details=details)
                if problem == "corrupt":
                    details.append(f"{tx_name} -> {rx_name}: frame received with wrong id or data")
                    return Attempt.fail(ctx.say(f"CAN: frames from {tx_name} to {rx_name} corrupted", cable),
                                        details=details)
                details.append(f"{tx_name} -> {rx_name}: {len(TEST_FRAMES)} frames ok")
        finally:
            bus_b.close()
    finally:
        bus_a.close()
    for iface in hardware:
        state = _state(ctx, iface)
        details.append(f"{iface}: state {state}")
        if state not in GOOD_STATES:
            return Attempt.fail(f"CAN: {iface} in error state {state}. "
                                "Check the CAN cable and termination, then retry.", details=details)
    return Attempt.ok(details=details)


register("can", CheckType(parse=parse, run=run, preflight=preflight))
