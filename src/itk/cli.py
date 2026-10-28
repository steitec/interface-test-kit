"""Command line interface: ``itk run``, ``itk selftest``, ``itk demo`` and helpers."""

from __future__ import annotations

import argparse

from . import __version__
from .profile import ProfileError, load_profile


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="itk", description=__doc__)
    parser.add_argument("--version", action="version", version=f"itk {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    p_check = sub.add_parser("check-profile", help="validate profile files")
    p_check.add_argument("files", nargs="+", metavar="FILE")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "check-profile":
        return _check_profile(args.files)
    parser.print_help()
    return 2
