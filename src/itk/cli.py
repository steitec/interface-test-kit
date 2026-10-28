"""Command line interface: ``itk run``, ``itk selftest``, ``itk demo`` and helpers."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import __version__
from .profile import ProfileError, load_profile
from .report import report_reachable, sync_spool
from .station import load_station, station_path
from .ui import ConsoleUI

_EXIT = {"PASS": 0, "FAIL": 1, "ABORTED": 2}


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


def _session(args, mode: str) -> int:
    from .session import real_context, run_session
    try:
        station = load_station(station_path(args.station))
        only = [s.strip() for s in args.only.split(",") if s.strip()] if getattr(args, "only", None) else None
        run = run_session(station, real_context(mode), ConsoleUI(),
                          rma=getattr(args, "rma", None), only=only)
    except KeyboardInterrupt:
        print("\nAborted.")
        return 2
    except (ValueError, ProfileError, OSError) as e:
        print(f"Error: {e}")
        return 2
    return _EXIT[run.status]


def _demo(args) -> int:
    import tempfile
    from importlib import resources

    from .runner import RETRY_PROMPT
    from .session import run_session
    from .sim.world import FAULTS, SERIAL_NUMBER, AutoUI, build_world
    from .station import Station

    if args.list_faults:
        for name, text in FAULTS.items():
            print(f"  {name:<16} {text}")
        return 0
    fault = None if args.fault == "none" else args.fault
    profile = load_profile(Path(str(resources.files("itk"))) / "profiles" / "demo.yaml")
    with tempfile.TemporaryDirectory(prefix="itk-demo-") as tmp:
        root = Path(tmp)
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        station = Station(report_dir=out, spool_dir=root / "spool", profile_dir=root, name="demo")
        no_to = (RETRY_PROMPT,) + (("power LED",) if fault == "led_off" else ())
        print(f"Simulated unit, fault: {args.fault}\n")
        run = run_session(station, build_world(fault, root), AutoUI(SERIAL_NUMBER, no_to),
                          profiles=[profile])
    return _EXIT[run.status]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="itk", description=__doc__)
    parser.add_argument("--version", action="version", version=f"itk {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    p_check = sub.add_parser("check-profile", help="validate profile files")
    p_check.add_argument("files", nargs="+", metavar="FILE")

    station_help = "station file (default: $ITK_STATION or /etc/itk/station.yaml)"
    p_run = sub.add_parser("run", help="test a unit")
    p_run.add_argument("--station", help=station_help)
    p_run.add_argument("--rma", help="RMA number, stored in the report")
    p_run.add_argument("--only", help="comma-separated step ids to run, e.g. serial-1,usb")

    p_self = sub.add_parser("selftest", help="check the test equipment on a reference unit")
    p_self.add_argument("--station", help=station_help)

    from .sim.world import FAULTS
    p_demo = sub.add_parser("demo", help="run a full session against a simulated unit")
    p_demo.add_argument("--fault", default="none", choices=["none", *FAULTS], metavar="FAULT",
                        help="inject a fault (see --list-faults)")
    p_demo.add_argument("--list-faults", action="store_true", help="list the faults and exit")
    p_demo.add_argument("--out", default="reports", help="report folder (default: reports)")

    p_sync = sub.add_parser("sync", help="upload reports saved locally while the network drive was down")
    p_sync.add_argument("--station", help=station_help)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "check-profile":
        return _check_profile(args.files)
    if args.cmd == "run":
        return _session(args, "unit")
    if args.cmd == "selftest":
        return _session(args, "selftest")
    if args.cmd == "demo":
        return _demo(args)
    if args.cmd == "sync":
        return _sync(args.station)
    parser.print_help()
    return 2
