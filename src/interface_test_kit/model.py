"""Result data: measurements, attempts, step results and a whole run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Measurement:
    name: str
    value: float
    unit: str = ""
    low: float | None = None
    high: float | None = None

    @property
    def passed(self) -> bool:
        if self.low is not None and self.value < self.low:
            return False
        if self.high is not None and self.value > self.high:
            return False
        return True

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "unit": self.unit,
                "low": self.low, "high": self.high, "passed": self.passed}


@dataclass
class Attempt:
    status: str
    message: str = ""
    details: list[str] = field(default_factory=list)
    measurements: list[Measurement] = field(default_factory=list)

    @classmethod
    def ok(cls, message: str = "", measurements: list[Measurement] | None = None,
           details: list[str] | None = None) -> Attempt:
        return cls("PASS", message, list(details or []), list(measurements or []))

    @classmethod
    def fail(cls, message: str, details: list[str] | None = None,
             measurements: list[Measurement] | None = None) -> Attempt:
        return cls("FAIL", message, list(details or []), list(measurements or []))

    def to_dict(self) -> dict:
        return {"status": self.status, "message": self.message, "details": list(self.details),
                "measurements": [m.to_dict() for m in self.measurements]}


@dataclass
class StepResult:
    id: str
    name: str
    type: str
    status: str
    attempts: list[Attempt]
    equipment_id: str | None = None

    @property
    def message(self) -> str:
        if not self.attempts:
            return ""
        last = self.attempts[-1]
        if self.status == "FAIL" and last.status == "PASS":
            failed = next(a for a in reversed(self.attempts) if a.status == "FAIL")
            return f"{failed.message} (not stable: failed again on retry)"
        return last.message

    @property
    def passed_after_retry(self) -> bool:
        return self.status == "PASS" and len(self.attempts) > 1

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "type": self.type, "status": self.status,
                "message": self.message, "passed_after_retry": self.passed_after_retry,
                "equipment_id": self.equipment_id,
                "attempts": [a.to_dict() for a in self.attempts]}


def _iso(t: datetime | None) -> str | None:
    return t.isoformat() if t is not None else None


@dataclass
class RunResult:
    mode: str
    serial_number: str
    rma: str | None
    profile_name: str
    profile_version: int
    station: str
    operator: str | None
    started: datetime
    finished: datetime | None
    tool_version: str
    steps: list[StepResult]
    status: str
    only: list[str] | None = None

    def to_dict(self) -> dict:
        return {"mode": self.mode, "serial_number": self.serial_number, "rma": self.rma,
                "profile": {"name": self.profile_name, "version": self.profile_version},
                "station": self.station, "operator": self.operator,
                "started": _iso(self.started), "finished": _iso(self.finished),
                "tool_version": self.tool_version, "status": self.status, "only": self.only,
                "steps": [s.to_dict() for s in self.steps]}
