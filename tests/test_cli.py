import pytest

from itk.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and "0.1.0" in capsys.readouterr().out
