"""Pick the profile that matches this device's DMI product name or device-tree model."""

from __future__ import annotations

from .context import Context
from .profile import Profile

_SOURCES = {"dmi_product_name": "/sys/class/dmi/id/product_name",
            "devicetree_model": "/proc/device-tree/model"}


def _read(ctx: Context, path: str) -> str | None:
    try:
        return ctx.path(path).read_bytes().decode(errors="replace").strip().rstrip("\0").strip()
    except OSError:
        return None


def detect_profiles(profiles: list[Profile], ctx: Context) -> list[Profile]:
    values = {key: _read(ctx, path) for key, path in _SOURCES.items()}
    return [p for p in profiles
            if p.detect and all(values.get(k) == v for k, v in p.detect.items())]
