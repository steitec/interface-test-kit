"""Command line interface: ``itk run``, ``itk selftest``, ``itk demo`` and helpers."""

from __future__ import annotations

import argparse

from . import __version__
from .profile import ProfileError, load_profile
from .report import report_reachable, sync_spool
from .station import load_station, station_path


def _check_profile(files: list[str]) -> int:
    rc = 0
    for name in files:
        try:
            p = load_profile(name)
        except (ProfileError, OSError) as e:
            print(f"ERROR {name}: {e}")
            rc = 2
        else:
            print(f"OK  {name}  {p.name} v{p.version}, {len(p.steps)} steps")
    return rc


def _sync(station_arg: str | None) -> int:
    try:
        station = load_station(station_path(station_arg))
    except (ValueError, OSError) as e:
        print(f"Error: {e}")
        return 2
    if not report_reachable(station):
        print(f"Network drive not reachable: {station.report_dir}")
        return 2
    for path in sync_spool(station):
        print(f"Uploaded {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="itk", description=__doc__)
    parser.add_argument("--version", action="version", version=f"itk {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    p_check = sub.add_parser("check-profile", help="validate profile files")
    p_check.add_argument("files", nargs="+", metavar="FILE")

    p_sync = sub.add_parser("sync", help="upload reports saved locally while the network drive was down")
    p_sync.add_argument("--station", help="station file (default: $ITK_STATION or /etc/itk/station.yaml)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "check-profile":
        return _check_profile(args.files)
    if args.cmd == "sync":
        return _sync(args.station)
    parser.print_help()
    return 2
