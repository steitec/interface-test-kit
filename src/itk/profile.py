"""Test profiles: one YAML file per product variant."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .checks import STEP_TYPES

_TOP_REQUIRED = {"name", "version", "steps"}
_TOP_OPTIONAL = {"setup", "detect", "serial_number", "reference", "max_attempts"}
_DETECT_KEYS = {"dmi_product_name", "devicetree_model"}
_STEP_COMMON = {"type", "name", "id", "equipment"}


@dataclass(frozen=True)
class Step:
    id: str
    name: str
    type: str
    config: Any
    equipment: str | None
    line: int


@dataclass(frozen=True)
class Profile:
    name: str
    version: int
    steps: list[Step]
    setup: str = ""
    detect: dict[str, str] = field(default_factory=dict)
    serial_pattern: str | None = None
    reference: bool = False
    max_attempts: int = 4
    path: Path | None = None


class ProfileError(Exception):
    def __init__(self, message: str, line: int | None = None):
        self.message = message
        self.line = line
        super().__init__(f"line {line}: {message}" if line else message)


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _step_lines(root: yaml.Node) -> list[int]:
    if isinstance(root, yaml.MappingNode):
        for key, value in root.value:
            if key.value == "steps" and isinstance(value, yaml.SequenceNode):
                return [item.start_mark.line + 1 for item in value.value]
    return []


def _key_line(root: yaml.Node, name: str) -> int | None:
    if isinstance(root, yaml.MappingNode):
        for key, _ in root.value:
            if key.value == name:
                return key.start_mark.line + 1
    return None


def _parse_step(index: int, raw: Any, line: int | None) -> Step:
    label = f"steps[{index}]"
    if not isinstance(raw, dict):
        raise ProfileError(f"{label}: must be a mapping", line)
    if isinstance(raw.get("name"), str) and raw["name"].strip():
        label += f" ({raw['name']})"
    try:
        if "name" not in raw or not str(raw["name"]).strip():
            raise ValueError("name: missing")
        if "type" not in raw:
            raise ValueError("type: missing")
        check = STEP_TYPES.get(raw["type"])
        if check is None:
            raise ValueError(f"type: unknown step type '{raw['type']}' "
                             f"(known: {', '.join(sorted(STEP_TYPES))})")
        name = str(raw["name"])
        step_id = str(raw.get("id") or slug(name))
        equipment = raw.get("equipment")
        config = check.parse({"name": name,
                              **{k: v for k, v in raw.items() if k not in _STEP_COMMON}})
    except ValueError as e:
        raise ProfileError(f"{label}: {e}", line) from None
    return Step(step_id, name, raw["type"], config,
                str(equipment) if equipment is not None else None, line or 0)


def load_profile(path: Path) -> Profile:
    path = Path(path)
    text = path.read_text()
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        raise ProfileError(f"invalid YAML: {getattr(e, 'problem', e)}",
                           mark.line + 1 if mark else None) from None
    if not isinstance(data, dict):
        raise ProfileError("a profile must be a mapping with name, version and steps")

    def err(key: str, message: str) -> ProfileError:
        return ProfileError(f"{key}: {message}", _key_line(root, key))

    for key in data:
        if key not in _TOP_REQUIRED and key not in _TOP_OPTIONAL:
            raise err(key, f"unknown field '{key}'")
    for key in sorted(_TOP_REQUIRED):
        if key not in data:
            raise ProfileError(f"{key}: missing")
    if not isinstance(data["name"], str) or not data["name"].strip():
        raise err("name", "must be a non-empty text")
    version = data["version"]
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise err("version", "must be a whole number of 1 or more")
    max_attempts = data.get("max_attempts", 4)
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) \
            or not 1 <= max_attempts <= 10:
        raise err("max_attempts", "must be a whole number from 1 to 10")
    reference = data.get("reference", False)
    if not isinstance(reference, bool):
        raise err("reference", "must be true or false")
    setup = data.get("setup", "") or ""
    if not isinstance(setup, str):
        raise err("setup", "must be a text")
    detect = data.get("detect") or {}
    if not isinstance(detect, dict):
        raise err("detect", "must be a mapping")
    for key in detect:
        if key not in _DETECT_KEYS:
            raise err("detect", f"unknown key '{key}' (known: {', '.join(sorted(_DETECT_KEYS))})")
    pattern = None
    if "serial_number" in data:
        sn = data["serial_number"]
        if not isinstance(sn, dict) or set(sn) - {"pattern"}:
            raise err("serial_number", "must be a mapping with a pattern")
        pattern = sn.get("pattern")
        try:
            re.compile(str(pattern))
        except re.error as e:
            raise err("serial_number", f"pattern is not a valid regular expression ({e})") from None
    steps_raw = data["steps"]
    if not isinstance(steps_raw, list) or not steps_raw:
        raise err("steps", "must be a non-empty list")

    lines = _step_lines(root)
    steps: list[Step] = []
    seen: set[str] = set()
    for i, raw in enumerate(steps_raw):
        line = lines[i] if i < len(lines) else None
        step = _parse_step(i, raw, line)
        if step.id in seen:
            raise ProfileError(f"steps[{i}] ({step.name}): duplicate step id '{step.id}' "
                               "(give the step a different name or an id)", line)
        seen.add(step.id)
        steps.append(step)

    return Profile(name=data["name"], version=version, steps=steps, setup=setup,
                   detect={k: str(v) for k, v in detect.items()},
                   serial_pattern=str(pattern) if pattern is not None else None,
                   reference=reference, max_attempts=max_attempts, path=path)


def load_profiles(directory: Path) -> list[Profile]:
    profiles = []
    for path in sorted(Path(directory).glob("*.yaml")):
        try:
            profiles.append(load_profile(path))
        except ProfileError as e:
            raise ProfileError(f"{path}: {e}") from None
    return sorted(profiles, key=lambda p: p.name)
