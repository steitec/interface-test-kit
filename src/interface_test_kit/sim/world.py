"""A whole simulated unit for ``itk demo``: serial ports, USB sticks, Ethernet, CAN and faults."""

from __future__ import annotations

import itertools
from pathlib import Path

from ..checks.serial import LOOPBACK_TYPES
from ..context import CommandResult, Context
from ..ui import ConsoleUI
from .can import SimCanNetwork
from .fakes import FakeRunner, add_netdev, add_usb_stick, lsblk_result
from .serial import SimLoopback

FAULTS: dict[str, str] = {
    "serial_cts": "Serial 1: RTS->CTS line broken",
    "serial_data": "Serial 1: no data comes back",
    "usb_missing": "only one test stick plugged in",
    "usb_slow": "test sticks far too slow",
    "usb_wrong_speed": "USB 3 port 2-1 only runs at 480 Mbit/s",
    "usb_no_label": "second stick has no ITKTEST label",
    "eth_no_link": "no Ethernet link on LAN1",
    "eth_speed": "LAN1 links at 100 instead of 1000 Mbit/s",
    "can_no_ack": "frames sent from can0 never arrive",
    "led_off": "the operator sees the power LED off",
}

SERIAL_NUMBER = "EPC-24-00137"


def _ping(args: list[str]) -> CommandResult:
    target = args[-1]
    return CommandResult(0, f"--- {target} ping statistics ---\n"
                            "5 packets transmitted, 5 received, 0% packet loss, time 4005ms\n", "")


def build_world(fault: str | None, root: Path) -> Context:
    """Create the fake system under ``root`` and return a context wired to it."""
    for port in ("ttyS0", "ttyS1"):
        (root / "dev").mkdir(parents=True, exist_ok=True)
        (root / "dev" / port).write_text("")
    dmi = root / "sys/class/dmi/id"
    dmi.mkdir(parents=True, exist_ok=True)
    (dmi / "product_name").write_text("EPC-24B\n")

    sticks = [add_usb_stick(root, "sdb1", "ITKTEST1", "1-1", 5000, "/media/itk1")]
    if fault != "usb_missing":
        label = None if fault == "usb_no_label" else "ITKTEST2"
        speed = 480 if fault == "usb_wrong_speed" else 5000
        sticks.append(add_usb_stick(root, "sdc1", label, "2-1", speed, "/media/itk2"))

    add_netdev(root, "eth0", carrier=0 if fault == "eth_no_link" else 1,
               speed=100 if fault == "eth_speed" else 1000)
    for iface in ("can0", "can1"):
        add_netdev(root, iface, hardware=False)

    def open_serial(port: str, baud: int) -> SimLoopback:
        if port.endswith("ttyS0"):
            return SimLoopback(LOOPBACK_TYPES["9pin-full"],
                               broken_lines={"RTS->CTS"} if fault == "serial_cts" else None,
                               data_fault="no_echo" if fault == "serial_data" else None)
        return SimLoopback(LOOPBACK_TYPES["9pin"])

    network = SimCanNetwork(drop={"can0"} if fault == "can_no_ack" else None)
    # The USB check times a write and a read-back per stick. In the demo the "sticks" are
    # folders on the local disk, so a real clock would report the disk (thousands of MB/s).
    # Instead the clock steps through the times a real stick would need, in check order.
    rates = [STICK_MBS["slow" if fault == "usb_slow" else 5000]]
    if len(sticks) > 1:
        rates.append(STICK_MBS["slow" if fault == "usb_slow" else speed])
    clock = _stick_clock(rates)
    runner = FakeRunner({"lsblk -J": lsblk_result(sticks), "ping -c": _ping})
    return Context(root=root, run=runner, open_serial=open_serial, open_can=network.open, clock=clock)


# Typical (write, read) MB/s of a test stick on a USB 3 port, on a USB 2 port, and a worn one.
STICK_MBS: dict[int | str, tuple[float, float]] = {5000: (42.0, 138.0), 480: (17.5, 34.0), "slow": (4.2, 9.5)}
DEMO_SIZE_MB = 8  # size_mb of the USB step in profiles/demo.yaml


def _stick_clock(rates: list[tuple[float, float]]):
    """A clock for the demo: per stick write-start, write-end, read-start, read-end."""
    steps = []
    for write, read in rates:
        steps += [0.05, DEMO_SIZE_MB / write, 0.05, DEMO_SIZE_MB / read]
    increments = itertools.chain(steps, itertools.repeat(0.05))
    now = 0.0

    def clock() -> float:
        nonlocal now
        now += next(increments)
        return now
    return clock


class AutoUI(ConsoleUI):
    """Console output like a real session, with the operator's answers typed in automatically."""

    def __init__(self, serial: str, no_to: tuple[str, ...] = (), stdout=None):
        super().__init__(stdout=stdout)
        self.serial = serial
        self.no_to = no_to

    def ask_text(self, prompt: str) -> str:
        self._break()
        self._write(f"{prompt}{self.serial}\n")
        return self.serial

    def ask_yes_no(self, prompt: str) -> bool:
        self._break()
        answer = not any(text in prompt for text in self.no_to)
        self._write(f"{prompt} [Y/N] {'Y' if answer else 'N'}\n")
        return answer

    def wait_key(self, prompt: str) -> None:
        self._break()
        self._write(f"{prompt}\n")
