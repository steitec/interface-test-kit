"""Command line interface: ``itk run``, ``itk selftest``, ``itk demo`` and helpers."""

from __future__ import annotations

import argparse

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="itk", description=__doc__)
    parser.add_argument("--version", action="version", version=f"itk {__version__}")
    parser.add_subparsers(dest="cmd")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    parser.print_help()
    return 2
