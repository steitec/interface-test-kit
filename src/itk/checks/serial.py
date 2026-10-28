"""Serial port check through a loopback plug: data at each baud rate, then handshake lines."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from typing import Protocol

from ..model import Attempt
from . import CheckType, fields, register

# Which output line drives which input lines on each kind of loopback plug.
LOOPBACK_TYPES: dict[str, dict[str, tuple[str, ...]]] = {
    "9pin-full": {"RTS": ("CTS",), "DTR": ("DSR", "CD", "RI")},
    "9pin": {"RTS": ("CTS",), "DTR": ("DSR", "CD")},
    "data-only": {},
}

# USB-serial adapters report modem line changes over USB, several ms late.
LINE_SETTLE_S = 0.05

_REPAIR = ". Check the loopback plug; if it is fine, send the unit to repair."


class SerialLink(Protocol):
    def set_baud(self, baud: int) -> None: ...
    def write(self, data: bytes) -> None: ...
    def read(self, n: int, timeout: float) -> bytes: ...
    def reset_input(self) -> None: ...
    def set_line(self, name: str, state: bool) -> None: ...
    def get_line(self, name: str) -> bool: ...
    def close(self) -> None: ...


class PySerialLink:
    def __init__(self, port: str, baud: int):
        import serial
        self._ser = serial.Serial(port, baud, timeout=1.0)

    def set_baud(self, baud: int) -> None:
        self._ser.baudrate = baud

    def write(self, data: bytes) -> None:
        self._ser.write(data)
        self._ser.flush()

    def read(self, n: int, timeout: float) -> bytes:
        self._ser.timeout = timeout
        return self._ser.read(n)

    def reset_input(self) -> None:
        self._ser.reset_input_buffer()

    def set_line(self, name: str, state: bool) -> None:
        setattr(self._ser, name.lower(), state)

    def get_line(self, name: str) -> bool:
        return bool(getattr(self._ser, name.lower()))

    def close(self) -> None:
        self._ser.close()


def open_pyserial(port: str, baud: int) -> SerialLink:
    return PySerialLink(port, baud)


@dataclass(frozen=True)
class SerialConfig:
    name: str
    port: str
    loopback: str = "9pin"
    bauds: tuple[int, ...] = (9600, 115200)
    pattern_bytes: int = 512


def parse(raw: dict) -> SerialConfig:
    f = fields(raw, {"port"}, {"loopback": "9pin", "bauds": [9600, 115200], "pattern_bytes": 512})
    if f["loopback"] not in LOOPBACK_TYPES:
        raise ValueError(f"loopback: unknown type '{f['loopback']}' "
                         f"(known: {', '.join(LOOPBACK_TYPES)})")
    bauds = f["bauds"]
    if not isinstance(bauds, list) or not bauds or \
            not all(isinstance(b, int) and not isinstance(b, bool) and b > 0 for b in bauds):
        raise ValueError("bauds: must be a list of positive whole numbers")
    pb = f["pattern_bytes"]
    if not isinstance(pb, int) or pb < 256:
        raise ValueError("pattern_bytes: must be a whole number of at least 256")
    return SerialConfig(str(f["name"]), str(f["port"]), f["loopback"], tuple(bauds), pb)


def preflight(config: SerialConfig, ctx) -> list[str]:
    path = ctx.path(config.port)
    if not path.exists():
        return [f"{config.name}: port {config.port} not found"]
    if not os.access(path, os.R_OK | os.W_OK):
        return [f"{config.name}: no access to port {config.port} (add the user to group dialout)"]
    return []


def _pattern(baud: int, size: int) -> bytes:
    return bytes(range(256)) + random.Random(baud).randbytes(size - 256)


def _check_data(link: SerialLink, config: SerialConfig, details: list[str]) -> tuple[str, int] | None:
    """Returns (problem, baud) for the first failing baud rate, or None."""
    for baud in config.bauds:
        link.set_baud(baud)
        link.reset_input()
        sent = _pattern(baud, config.pattern_bytes)
        link.write(sent)
        got = link.read(len(sent), max(1.0, 20 * len(sent) * 10 / baud))
        if not got:
            details.append(f"{baud} baud: nothing received")
            return "no_data", baud
        if got != sent:
            offset = next((i for i, (a, b) in enumerate(zip(sent, got)) if a != b), len(got))
            details.append(f"{baud} baud: received {len(got)} of {len(sent)} bytes, "
                           f"first difference at offset {offset}")
            return "corrupt", baud
        details.append(f"{baud} baud: {len(sent)} bytes ok")
    return None


def _check_lines(link: SerialLink, wiring: dict[str, tuple[str, ...]], details: list[str],
                 sleep) -> list[str]:
    broken: list[str] = []
    for out, inputs in wiring.items():
        for state in (True, False):
            link.set_line(out, state)
            for other in wiring:
                if other != out:
                    link.set_line(other, not state)
            sleep(LINE_SETTLE_S)
            for inp in inputs:
                if link.get_line(inp) != state:
                    pair = f"{out}->{inp}"
                    details.append(f"{pair}: input did not follow output set {'high' if state else 'low'}")
                    if pair not in broken:
                        broken.append(pair)
    if wiring and not broken:
        details.append("handshake lines ok: " + ", ".join(
            f"{o}->{i}" for o, ins in wiring.items() for i in ins))
    return broken


def run(config: SerialConfig, ctx, ui) -> Attempt:
    details: list[str] = []
    link = ctx.open_serial(config.port, config.bauds[0])
    try:
        problem = _check_data(link, config, details)
        if problem:
            kind, baud = problem
            if kind == "no_data":
                unit = f"{config.name}: no data received back{_REPAIR}"
            else:
                unit = f"{config.name}: data corrupted at {baud} baud{_REPAIR}"
            return Attempt.fail(ctx.say(unit, f"Loopback plug on {config.name} faulty or not plugged in"),
                                details=details)
        broken = _check_lines(link, LOOPBACK_TYPES[config.loopback], details, ctx.sleep)
    finally:
        link.close()
    if broken:
        pairs = ", ".join(broken)
        return Attempt.fail(ctx.say(f"{config.name}: handshake line faulty ({pairs}){_REPAIR}",
                                    f"Loopback plug on {config.name} faulty ({pairs} not connected)"),
                            details=details)
    return Attempt.ok(details=details)


register("serial", CheckType(parse=parse, run=run, preflight=preflight))
