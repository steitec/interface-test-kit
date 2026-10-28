"""A simulated CAN network: frames sent on one interface arrive at all other open ones."""

from __future__ import annotations

from collections import deque


class SimCanBus:
    def __init__(self, network: "SimCanNetwork", iface: str):
        self.network = network
        self.iface = iface
        self.queue: deque = deque()

    def send(self, arb_id: int, data: bytes, extended: bool) -> None:
        self.network.deliver(self, (arb_id, bytes(data), extended))

    def recv(self, timeout: float):
        return self.queue.popleft() if self.queue else None

    def close(self) -> None:
        if self in self.network.buses:
            self.network.buses.remove(self)


class SimCanNetwork:
    def __init__(self, drop: set[str] | None = None):
        self.drop = set(drop or ())
        self.buses: list[SimCanBus] = []

    def open(self, iface: str) -> SimCanBus:
        bus = SimCanBus(self, iface)
        self.buses.append(bus)
        return bus

    def deliver(self, sender: SimCanBus, frame) -> None:
        if sender.iface in self.drop:
            return
        for bus in self.buses:
            if bus is not sender:
                bus.queue.append(frame)
