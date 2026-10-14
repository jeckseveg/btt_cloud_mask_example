import example_cloud_detector
from example_cloud_detector.cli import main


def test_version():
    assert example_cloud_detector.__version__ == "0.1.0"


def test_cli_version(capsys):
    try:
        main(["--version"])
    except SystemExit:
        pass
    assert "0.1.0" in capsys.readouterr().out
