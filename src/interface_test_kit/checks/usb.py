"""USB check with labelled test sticks: count, port, negotiated speed, write/read and throughput."""

from __future__ import annotations

import json
import os
import random
import stat
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ..model import Attempt, Measurement
from . import CheckType, fields, register

BLOCK = 1 << 20
TEST_FILE = "itk-test.bin"


@dataclass(frozen=True)
class UsbConfig:
    name: str
    count: int
    label: str = "ITKTEST"
    size_mb: int = 64
    min_write_mbs: float | None = None
    min_read_mbs: float | None = None
    min_speed_mbps: int | None = None
    ports: tuple[str, ...] = ()


@dataclass
class Stick:
    device: str
    label: str
    mountpoint: str | None
    usb_port: str | None
    speed_mbps: int | None


def _positive(value, name: str, whole: bool = False):
    ok_type = int if whole else (int, float)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, ok_type) or value <= 0:
        raise ValueError(f"{name}: must be a positive {'whole ' if whole else ''}number")
    return value


def parse(raw: dict) -> UsbConfig:
    f = fields(raw, {"count"}, {"label": "ITKTEST", "size_mb": 64, "min_write_mbs": None,
                                "min_read_mbs": None, "min_speed_mbps": None, "ports": []})
    _positive(f["count"], "count", whole=True)
    _positive(f["size_mb"], "size_mb", whole=True)
    for key in ("min_write_mbs", "min_read_mbs"):
        _positive(f[key], key)
    _positive(f["min_speed_mbps"], "min_speed_mbps", whole=True)
    if not isinstance(f["label"], str) or not f["label"]:
        raise ValueError("label: must be a non-empty text")
    if not isinstance(f["ports"], list):
        raise ValueError("ports: must be a list of USB port names like 1-2")
    return UsbConfig(str(f["name"]), f["count"], f["label"], f["size_mb"], f["min_write_mbs"],
                     f["min_read_mbs"], f["min_speed_mbps"], tuple(str(p) for p in f["ports"]))


def _usb_device(ctx, kname: str) -> tuple[str | None, int | None]:
    """Walk up from the block device in sysfs to the USB device (the dir with speed and devnum)."""
    sysfs = ctx.path("/sys").resolve()
    try:
        p = ctx.path(f"/sys/class/block/{kname}").resolve(strict=True)
    except OSError:
        return None, None
    while p != sysfs and p != p.parent:
        if (p / "speed").is_file() and (p / "devnum").is_file():
            try:
                return p.name, int(float((p / "speed").read_text().strip()))
            except (OSError, ValueError):
                return p.name, None
        p = p.parent
    return None, None


def _walk(nodes: list[dict], tran: str | None = None):
    for node in nodes:
        t = node.get("tran") or tran
        yield node, t
        yield from _walk(node.get("children") or [], t)


def find_sticks(cfg: UsbConfig, ctx, ignored: list[str] | None = None) -> list[Stick]:
    result = ctx.run(["lsblk", "-J", "-o", "NAME,KNAME,PATH,LABEL,MOUNTPOINT,TRAN"])
    if result.returncode != 0:
        raise RuntimeError(f"lsblk failed: {result.stderr.strip()}")
    sticks = []
    for node, tran in _walk(json.loads(result.stdout).get("blockdevices", [])):
        label = node.get("label")
        if tran != "usb" or not label:
            continue
        if not label.startswith(cfg.label):
            if ignored is not None:
                ignored.append(f"ignored: {node.get('path')} label {label}")
            continue
        port, speed = _usb_device(ctx, node["kname"])
        sticks.append(Stick(node["path"], label, node.get("mountpoint"), port, speed))
    return sorted(sticks, key=lambda s: s.device)


@lru_cache(maxsize=1)
def _payload() -> bytes:
    return random.Random(0).randbytes(BLOCK - 8)


def _block(i: int) -> bytes:
    return i.to_bytes(8, "big") + _payload()


def _same_device(ctx, stick: Stick) -> bool:
    """True if the mountpoint really is the stick's filesystem right now."""
    mountpoint = ctx.path(stick.mountpoint)
    device = ctx.path(stick.device)
    if not device.exists():
        # Only the simulated worlds under a fake root have no device nodes.
        return Path(ctx.root) != Path("/")
    try:
        return (stat.S_ISBLK(os.stat(device).st_mode) and os.path.ismount(mountpoint)
                and os.stat(mountpoint).st_dev == os.stat(device).st_rdev)
    except OSError:
        return False


def _still_mounted(ctx, cfg: UsbConfig, stick: Stick) -> bool:
    """Ask lsblk again right before writing: the stick may have been pulled meanwhile."""
    try:
        now = {s.device: s.mountpoint for s in find_sticks(cfg, ctx)}
    except (RuntimeError, ValueError):
        return False
    return now.get(stick.device) == stick.mountpoint and _same_device(ctx, stick)


def _write_file(path: Path, size_mb: int, clock) -> float:
    if os.path.lexists(path):  # never follow a link someone left on the stick
        os.unlink(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    try:
        t0 = clock()
        for i in range(size_mb):
            os.write(fd, _block(i))
        os.fsync(fd)
        return clock() - t0
    finally:
        os.close(fd)


def _read_back(path: Path, size_mb: int, clock) -> tuple[float, int | None]:
    """Returns (seconds, index of the first bad block or None)."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        bad = None
        t0 = clock()
        for i in range(size_mb):
            data = os.read(fd, BLOCK)
            if bad is None and data != _block(i):
                bad = i
        return clock() - t0, bad
    finally:
        os.close(fd)


def _test_stick(stick: Stick, cfg: UsbConfig, ctx, details: list[str]) -> tuple[str | None, list[Measurement]]:
    """Returns (unit-mode problem or None, measurements). Never writes outside the mountpoint."""
    where = stick.usb_port or stick.device
    if not _still_mounted(ctx, cfg, stick):
        details.append(f"{stick.device}: not mounted at {stick.mountpoint} any more")
        return f"USB: test stick in port {where} is not mounted", []
    path = ctx.path(stick.mountpoint) / TEST_FILE
    measurements = []
    try:
        try:
            t_write = _write_file(path, cfg.size_mb, ctx.clock)
        except OSError as e:
            details.append(f"{stick.device}: write failed: {e}")
            return f"USB: could not write to the test stick ({where}): full or write-protected", []
        t_read, bad = _read_back(path, cfg.size_mb, ctx.clock)
    finally:
        try:
            path.unlink()
        except OSError:
            pass
    write_mbs = round(cfg.size_mb / max(t_write, 1e-6), 1)
    read_mbs = round(cfg.size_mb / max(t_read, 1e-6), 1)
    measurements.append(Measurement(f"{where} write", write_mbs, "MB/s", low=cfg.min_write_mbs))
    measurements.append(Measurement(f"{where} read", read_mbs, "MB/s", low=cfg.min_read_mbs))
    if stick.speed_mbps is not None:
        measurements.append(Measurement(f"{where} USB speed", stick.speed_mbps, "Mbit/s",
                                        low=cfg.min_speed_mbps))
    details.append(f"{stick.device} ({stick.label}) on {where}: write {write_mbs} MB/s, "
                   f"read {read_mbs} MB/s, USB {stick.speed_mbps} Mbit/s")
    if bad is not None:
        details.append(f"{stick.device}: block {bad} read back wrong")
        return f"USB: stick data corrupted ({where})", measurements
    if any(not m.passed for m in measurements[:2]):
        return f"USB: port {where} too slow", measurements
    if len(measurements) > 2 and not measurements[2].passed:
        return (f"USB: port {where} runs at {stick.speed_mbps} Mbit/s, "
                f"expected at least {cfg.min_speed_mbps}"), measurements
    return None, measurements


def run(cfg: UsbConfig, ctx, ui) -> Attempt:
    details: list[str] = []
    try:
        sticks = find_sticks(cfg, ctx, details)
    except (RuntimeError, ValueError) as e:
        return Attempt.fail("USB: could not look for test sticks. Tell the test engineer.",
                            details=[str(e)])
    if len(sticks) != cfg.count:
        details.append("found: " + (", ".join(f"{s.device} on {s.usb_port}" for s in sticks) or "none"))
        return Attempt.fail(f"USB: found {len(sticks)} test stick(s), expected {cfg.count}. "
                            f"Insert the test sticks labelled {cfg.label}.", details=details)
    ports = {s.usb_port for s in sticks}
    for port in cfg.ports:
        if port not in ports:
            return Attempt.fail(f"USB: no test stick in port {port}", details=details)
    measurements: list[Measurement] = []
    problems: list[tuple[str, Stick]] = []
    for stick in sticks:
        if not stick.mountpoint:
            problems.append((f"USB: test stick in port {stick.usb_port or stick.device} is not mounted", stick))
            continue
        problem, ms = _test_stick(stick, cfg, ctx, details)
        measurements += ms
        if problem:
            problems.append((problem, stick))
    if problems:
        unit, stick = problems[0]
        stick_fault = "not mounted" not in unit
        message = ctx.say(unit, f"Test stick {stick.device} faulty or too slow") if stick_fault else unit
        return Attempt.fail(message, details=details, measurements=measurements)
    return Attempt.ok(measurements=measurements, details=details)


register("usb", CheckType(parse=parse, run=run))
