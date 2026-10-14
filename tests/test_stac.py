import datetime

import pystac
import pytest

from btt_cloud_mask_example.stac import data_coverage, download_assets, find_items, normalize_url


def test_data_coverage():
    def item(area):
        it = pystac.Item("x", None, None, datetime.datetime(2022, 1, 1), {"tile:data_area": area})
        # 2500 px x 2 m = 5 km tile -> 25 km2; proj:bbox would only bound the data, so it isn't used
        it.add_asset("ms_analytic", pystac.Asset("ms.tif", extra_fields={
            "proj:shape": [2500, 2500], "proj:transform": [2.0, 0, 0, 0, -2.0, 0]}))
        return it

    assert data_coverage(item(25.0)) == 1.0
    assert data_coverage(item(5.0)) == pytest.approx(0.2)
    assert data_coverage(pystac.Item("x", None, None, datetime.datetime(2022, 1, 1), {})) is None


def test_normalize_stac_browser_url():
    url = "https://browser.moregeo.it/external/maxar-opendata.s3.amazonaws.com/events/catalog.json"
    assert normalize_url(url) == "https://maxar-opendata.s3.amazonaws.com/events/catalog.json"
    assert normalize_url("https://example.com/catalog.json") == "https://example.com/catalog.json"


def test_find_all_items(catalog):
    ids = [i.id for i in find_items(str(catalog), "event-a")]
    assert ids == ["pan-cloudy", "ms-clear", "ms-cloudy"]


def test_filters(catalog):
    found = find_items(str(catalog), "event-a", min_cloud=10, required_assets=["ms_analytic"])
    assert [i.id for i in found] == ["ms-cloudy"]
    found = find_items(str(catalog), platforms=["WV02"])
    assert [i.id for i in found] == ["ms-clear"]


def test_max_items(catalog):
    assert len(find_items(str(catalog), max_items=2)) == 2


def test_unknown_collection(catalog):
    with pytest.raises(ValueError):
        find_items(str(catalog), "nope")


def test_download_assets(catalog, tmp_path):
    (item,) = find_items(str(catalog), "event-a", platforms=["WV03"])
    out = tmp_path / "out"
    paths = download_assets(item, out, ["ms_analytic"])
    assert list(paths) == ["ms_analytic"]
    assert paths["ms_analytic"].read_bytes() == b"tif"
    assert (out / "ms-cloudy" / "item.json").exists()


def test_downloaded_item_json_is_self_contained(catalog, tmp_path):
    import pystac

    (item,) = find_items(str(catalog), "event-a", platforms=["WV03"])
    download_assets(item, tmp_path / "out", ["ms_analytic"])
    saved = pystac.Item.from_file(str(tmp_path / "out" / "ms-cloudy" / "item.json"))
    assert saved.assets["ms_analytic"].get_absolute_href() == str(tmp_path / "out" / "ms-cloudy" / "ms-cloudy-ms_analytic.tif")
    assert saved.assets["pan_analytic"].get_absolute_href().endswith("event-a/items/ms-cloudy-pan_analytic.tif")
