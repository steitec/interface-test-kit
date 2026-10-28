from pathlib import Path

import pytest

from itk.station import Station, load_station


def test_station_defaults(tmp_path):
    path = tmp_path / "station.yaml"
    path.write_text("report_dir: /mnt/share/itk\n")
    st = load_station(path)
    assert st.report_dir == Path("/mnt/share/itk")
    assert st.profile_dir == Path("/etc/itk/profiles")
    assert st.spool_dir == Path("/var/lib/itk/spool")
    assert st.name and st.mount_point is None and not st.ask_operator


def test_station_all_fields(tmp_path):
    path = tmp_path / "station.yaml"
    path.write_text("report_dir: r\nprofile_dir: p\nspool_dir: s\nname: EOL-1\n"
                    "mount_point: /mnt/share\nask_operator: true\n")
    st = load_station(path)
    assert st == Station(Path("r"), Path("p"), Path("s"), "EOL-1", Path("/mnt/share"), True)


@pytest.mark.parametrize("text,needle", [
    ("report_dir: r\nreprot: x\n", "reprot"),
    ("profile_dir: p\n", "report_dir"),
    ("- a\n", "mapping"),
])
def test_station_errors(tmp_path, text, needle):
    path = tmp_path / "station.yaml"
    path.write_text(text)
    with pytest.raises(ValueError) as e:
        load_station(path)
    assert needle in str(e.value)
