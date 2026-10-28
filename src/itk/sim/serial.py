"""A simulated serial port with a loopback plug, optionally broken."""

from __future__ import annotations


class SimLoopback:
    def __init__(self, wiring: dict[str, tuple[str, ...]], broken_lines: set[str] | None = None,
                 data_fault: str | None = None):
        self.wiring = wiring
        self.broken_lines = set(broken_lines or ())
        self.data_fault = data_fault
        self.outputs = {"RTS": False, "DTR": False}
        self.buffer = bytearray()
        self.baud = 0

    def set_baud(self, baud: int) -> None:
        self.baud = baud

    def write(self, data: bytes) -> None:
        if self.data_fault == "no_echo":
            return
        data = bytearray(data)
        if self.data_fault == "corrupt" and len(data) > 100:
            data[100] ^= 0x01
        self.buffer += data

    def read(self, n: int, timeout: float) -> bytes:
        out = bytes(self.buffer[:n])
        del self.buffer[:n]
        return out

    def reset_input(self) -> None:
        self.buffer.clear()

    def set_line(self, name: str, state: bool) -> None:
        self.outputs[name] = state

    def get_line(self, name: str) -> bool:
        return any(self.outputs.get(out, False)
                   for out, inputs in self.wiring.items()
                   if name in inputs and f"{out}->{name}" not in self.broken_lines)

    def close(self) -> None:
        pass
