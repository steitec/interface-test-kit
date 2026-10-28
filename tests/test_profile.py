import textwrap
from pathlib import Path

import pytest

from itk.cli import main
from itk.profile import ProfileError, load_profile, load_profiles


def write(tmp_path: Path, text: str, name: str = "p.yaml") -> Path:
    path = tmp_path / name
    path.write_text(textwrap.dedent(text).lstrip("\n"))
    return path


def test_minimal_profile(tmp_path):
    p = load_profile(write(tmp_path, """
        name: EPC-24 B
        version: 3
        steps:
          - {type: confirm, name: Power LED, prompt: "Is the power LED green?"}
        """))
    assert p.name == "EPC-24 B" and p.version == 3
    assert p.max_attempts == 4 and not p.reference and p.setup == ""
    assert p.steps[0].id == "power-led" and p.steps[0].type == "confirm"
    assert p.steps[0].config.prompt == "Is the power LED green?"
    assert p.steps[0].line == 4


def test_full_top_level_fields(tmp_path):
    p = load_profile(write(tmp_path, """
        name: Ref
        version: 1
        reference: true
        max_attempts: 2
        setup: Plug everything in
        detect: {dmi_product_name: EPC-24B}
        serial_number: {pattern: "^EPC-24-\\\\d{5}$"}
        steps:
          - {type: confirm, name: A, id: led, equipment: Plug number, prompt: p}
        """))
    assert p.reference and p.max_attempts == 2 and p.setup == "Plug everything in"
    assert p.detect == {"dmi_product_name": "EPC-24B"}
    assert p.serial_pattern == r"^EPC-24-\d{5}$"
    assert p.steps[0].id == "led" and p.steps[0].equipment == "Plug number"


def test_unknown_field_reports_line(tmp_path):
    with pytest.raises(ProfileError) as e:
        load_profile(write(tmp_path, "name: X\nversion: 1\nsteps:\n"
                           "  - {type: confirm, name: A, prompt: p}\n"
                           "  - {type: confirm, name: B, promt: p}\n"))
    assert e.value.line == 5 and "promt" in str(e.value)
    assert str(e.value).startswith("line 5: steps[1] (B):")


@pytest.mark.parametrize("body,needle", [
    ("version: 1\nsteps: []", "name"),
    ("name: X\nversion: 0\nsteps: [{type: confirm, name: A, prompt: p}]", "version"),
    ("name: X\nversion: 1\nsteps: []", "steps"),
    ("name: X\nversion: 1\nsteps: [{type: laser, name: A}]", "laser"),
    ("name: X\nversion: 1\nsteps: [{type: confirm, prompt: p}]", "name"),
    ("name: X\nversion: 1\nmax_attempts: 11\nsteps: [{type: confirm, name: A, prompt: p}]", "max_attempts"),
    ("name: X\nversion: 1\ncolour: red\nsteps: [{type: confirm, name: A, prompt: p}]", "colour"),
    ("name: X\nversion: 1\ndetect: {bios: x}\nsteps: [{type: confirm, name: A, prompt: p}]", "bios"),
    ("name: X\nversion: 1\nserial_number: {pattern: '['}\nsteps: [{type: confirm, name: A, prompt: p}]", "pattern"),
    ("name: X\nversion: 1\nsteps: [{type: confirm, name: A, prompt: p}, {type: confirm, name: A, prompt: q}]", "duplicate"),
    ("- just a list", "mapping"),
    ("name: [unclosed", "YAML"),
])
def test_invalid_profiles(tmp_path, body, needle):
    with pytest.raises(ProfileError) as e:
        load_profile(write(tmp_path, body))
    assert needle in str(e.value)


def test_load_profiles_sorted_and_names_file(tmp_path):
    write(tmp_path, "name: B\nversion: 1\nsteps: [{type: confirm, name: A, prompt: p}]", "b.yaml")
    write(tmp_path, "name: A\nversion: 1\nsteps: [{type: confirm, name: A, prompt: p}]", "a.yaml")
    assert [p.name for p in load_profiles(tmp_path)] == ["A", "B"]
    write(tmp_path, "name: C\nversion: x\nsteps: []", "c.yaml")
    with pytest.raises(ProfileError) as e:
        load_profiles(tmp_path)
    assert "c.yaml" in str(e.value)


def test_check_profile_cli(tmp_path, capsys):
    good = write(tmp_path, "name: Good\nversion: 2\nsteps: [{type: confirm, name: A, prompt: p}]", "g.yaml")
    bad = write(tmp_path, "name: Bad\nversion: 1\nsteps: [{type: laser, name: A}]", "b.yaml")
    assert main(["check-profile", str(good)]) == 0
    assert main(["check-profile", str(good), str(bad)]) == 2
    out = capsys.readouterr().out
    assert f"OK  {good}  Good v2, 1 steps" in out
    assert f"ERROR {bad}:" in out and "laser" in out
