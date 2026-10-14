import btt_cloud_mask_example
from btt_cloud_mask_example.cli import main


def test_version():
    assert btt_cloud_mask_example.__version__ == "0.1.0"


def test_cli_version(capsys):
    try:
        main(["--version"])
    except SystemExit:
        pass
    assert "0.1.0" in capsys.readouterr().out


def test_run_continues_after_failed_item(ms_item, tmp_path, capsys):
    import pytest

    pytest.importorskip("ukis_csmask")
    item_dir = tmp_path  # conftest wrote item.json here
    rc = None
    try:
        main(["run", "ukis", str(tmp_path / "missing"), str(item_dir), "--out", str(tmp_path / "masks"), "--res", "native"])
    except SystemExit as exc:
        rc = exc.code
    out = capsys.readouterr()
    assert "1 of 2 items failed" in str(rc)
    assert "failed" in out.err and "17_000_TEST_ukis.tif" in out.out
