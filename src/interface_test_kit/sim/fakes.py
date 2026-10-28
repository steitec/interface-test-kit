"""Fake system pieces: a command runner and sysfs trees under a fake root."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..context import CommandResult


class FakeRunner:
    """Answers commands by their first two words; records every call."""

    def __init__(self, responses: dict[str, CommandResult] | None = None):
        self.responses = dict(responses or {})
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> CommandResult:
        self.calls.append(list(args))
        key = " ".join(args[:2])
        if key in self.responses:
            response = self.responses[key]
            return response(args) if callable(response) else response
        return CommandResult(127, "", f"fake: no response for {key}")


def lsblk_result(nodes: list[dict]) -> CommandResult:
    return CommandResult(0, json.dumps({"blockdevices": nodes}), "")


def add_usb_stick(root: Path, kname: str, label: str | None, port: str, speed: int,
                  mountpoint: str | None, tran: str = "usb") -> dict:
    """Create the sysfs entries of a USB stick partition and return its lsblk disk node."""
    disk = re.sub(r"\d+$", "", kname)
    bus = port.split("-")[0]
    dev = root / f"sys/devices/pci0000:00/0000:00:14.0/usb{bus}/{port}"
    dev.mkdir(parents=True, exist_ok=True)
    (dev / "speed").write_text(f"{speed}\n")
    (dev / "devnum").write_text("2\n")
    part = dev / f"{port}:1.0/host0/target0:0:0/0:0:0:0/block/{disk}/{kname}"
    part.mkdir(parents=True, exist_ok=True)
    links = root / "sys/class/block"
    links.mkdir(parents=True, exist_ok=True)
    (links / kname).symlink_to(part)
    if mountpoint:
        (root / mountpoint.lstrip("/")).mkdir(parents=True, exist_ok=True)
    return {"name": disk, "kname": disk, "path": f"/dev/{disk}", "label": None,
            "mountpoint": None, "tran": tran,
            "children": [{"name": kname, "kname": kname, "path": f"/dev/{kname}", "label": label,
                          "mountpoint": mountpoint, "tran": None}]}


def add_netdev(root: Path, iface: str, carrier: int | None = 1, speed: int | None = 1000,
               duplex: str | None = "full", hardware: bool = True) -> Path:
    """Create /sys/class/net/<iface>; None leaves the attribute unreadable like a down link."""
    d = root / "sys/class/net" / iface
    d.mkdir(parents=True, exist_ok=True)
    for name, value in (("carrier", carrier), ("speed", speed), ("duplex", duplex)):
        if value is not None:
            (d / name).write_text(f"{value}\n")
    if hardware:
        (d / "device").mkdir(exist_ok=True)
    return d
