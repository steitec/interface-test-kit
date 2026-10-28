"""Ethernet check: link, negotiated speed and duplex from sysfs, then ping a counterpart."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..model import Attempt, Measurement
from . import CheckType, fields, register

_LOSS = re.compile(r"(\d+(?:\.\d+)?)% packet loss")


@dataclass(frozen=True)
class EthernetConfig:
    name: str
    iface: str
    speed: int | None = None
    duplex: str | None = None
    ping: str | None = None
    ping_count: int = 5
    max_loss_pct: float = 0.0


def parse(raw: dict) -> EthernetConfig:
    f = fields(raw, {"iface"}, {"speed": None, "duplex": None, "ping": None,
                                "ping_count": 5, "max_loss_pct": 0.0})
    if f["speed"] is not None and (not isinstance(f["speed"], int) or f["speed"] <= 0):
        raise ValueError("speed: must be a positive whole number (Mbit/s)")
    if f["duplex"] is not None and f["duplex"] not in ("full", "half"):
        raise ValueError("duplex: must be full or half")
    if not isinstance(f["ping_count"], int) or not 1 <= f["ping_count"] <= 100:
        raise ValueError("ping_count: must be a whole number from 1 to 100")
    loss = f["max_loss_pct"]
    if isinstance(loss, bool) or not isinstance(loss, (int, float)) or not 0 <= loss <= 100:
        raise ValueError("max_loss_pct: must be a number from 0 to 100")
    return EthernetConfig(str(f["name"]), str(f["iface"]), f["speed"], f["duplex"],
                          str(f["ping"]) if f["ping"] is not None else None, f["ping_count"], float(loss))


def preflight(config: EthernetConfig, ctx) -> list[str]:
    if not ctx.path(f"/sys/class/net/{config.iface}").is_dir():
        return [f"{config.name}: network interface {config.iface} not found"]
    return []


def _read(ctx, iface: str, attr: str) -> str | None:
    try:
        return ctx.path(f"/sys/class/net/{iface}/{attr}").read_text().strip()
    except OSError:  # reading speed/duplex of a link that is down fails with EINVAL
        return None


def run(config: EthernetConfig, ctx, ui) -> Attempt:
    name = config.name
    faulty_equipment = f"{name}: network cable or test network faulty"
    details: list[str] = []
    measurements: list[Measurement] = []
    if _read(ctx, config.iface, "carrier") != "1":
        details.append(f"{config.iface}: no carrier")
        return Attempt.fail(ctx.say(f"{name}: no network link. Check the cable.", faulty_equipment),
                            details=details)
    speed_text = _read(ctx, config.iface, "speed")
    duplex = _read(ctx, config.iface, "duplex")
    details.append(f"{config.iface}: link up, speed {speed_text} Mbit/s, duplex {duplex}")
    if config.speed is not None:
        try:
            speed = int(speed_text or "")
        except ValueError:
            speed = -1
        measurements.append(Measurement("link speed", speed, "Mbit/s", low=config.speed))
        if speed != config.speed:
            return Attempt.fail(f"{name}: link at {speed_text} Mbit/s, expected {config.speed}",
                                details=details, measurements=measurements)
    if config.duplex is not None and duplex != config.duplex:
        return Attempt.fail(f"{name}: {duplex} duplex, expected {config.duplex}",
                            details=details, measurements=measurements)
    if config.ping:
        result = ctx.run(["ping", "-c", str(config.ping_count), "-W", "1", "-I", config.iface, config.ping])
        match = _LOSS.search(result.stdout)
        if not match:
            details += [f"ping exit {result.returncode}", result.stdout.strip(), result.stderr.strip()]
            return Attempt.fail(ctx.say(f"{name}: no answer from {config.ping}", faulty_equipment),
                                details=[d for d in details if d], measurements=measurements)
        loss = float(match.group(1))
        measurements.append(Measurement("packet loss", loss, "%", high=config.max_loss_pct))
        details.append(f"ping {config.ping}: {loss:g}% loss")
        if loss >= 100:
            return Attempt.fail(ctx.say(f"{name}: no answer from {config.ping}", faulty_equipment),
                                details=details, measurements=measurements)
        if loss > config.max_loss_pct:
            return Attempt.fail(ctx.say(f"{name}: {loss:g}% packet loss to {config.ping}", faulty_equipment),
                                details=details, measurements=measurements)
    return Attempt.ok(measurements=measurements, details=details)


register("ethernet", CheckType(parse=parse, run=run, preflight=preflight))
