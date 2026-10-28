"""Station settings: where reports and profiles live on this test station."""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_STATION = Path("/etc/itk/station.yaml")


@dataclass(frozen=True)
class Station:
    report_dir: Path
    profile_dir: Path = Path("/etc/itk/profiles")
    spool_dir: Path = Path("/var/lib/itk/spool")
    name: str = field(default_factory=socket.gethostname)
    require_mount: bool = False
    ask_operator: bool = False


_PATHS = {"report_dir", "profile_dir", "spool_dir"}
_BOOLS = {"require_mount", "ask_operator"}


def load_station(path: Path) -> Station:
    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path}: the station file must be a mapping of settings")
    known = _PATHS | _BOOLS | {"name"}
    for key in data:
        if key not in known:
            raise ValueError(f"{path}: unknown setting '{key}'")
    if "report_dir" not in data:
        raise ValueError(f"{path}: report_dir: missing")
    kwargs = {}
    for key, value in data.items():
        if key in _PATHS:
            kwargs[key] = Path(str(value))
        elif key in _BOOLS:
            if not isinstance(value, bool):
                raise ValueError(f"{path}: {key}: must be true or false")
            kwargs[key] = value
        else:
            kwargs[key] = str(value)
    return Station(**kwargs)
