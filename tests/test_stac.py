import json

import pytest

from example_cloud_detector.stac import download_assets, find_items, normalize_url


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj))


def _item(item_id, platform, cloud, assets):
    return {
        "type": "Feature",
        "stac_version": "1.0.0",
        "id": item_id,
        "geometry": None,
        "properties": {
            "datetime": "2022-01-01T00:00:00Z",
            "platform": platform,
            "tile:clouds_percent": cloud,
        },
        "links": [],
        "assets": {k: {"href": f"./{item_id}-{k}.tif"} for k in assets},
    }


@pytest.fixture
def catalog(tmp_path):
    """root -> event -> acquisition -> items, mirroring the Maxar Open Data layout."""
    _write(tmp_path / "catalog.json", {"type": "Catalog", "id": "root", "links": [
        {"rel": "child", "href": "./event-a/collection.json"},
        {"rel": "child", "href": "./event-b/collection.json"},
    ]})
    _write(tmp_path / "event-b/collection.json", {"type": "Collection", "id": "event-b", "links": []})
    _write(tmp_path / "event-a/collection.json", {"type": "Collection", "id": "event-a", "links": [
        {"rel": "child", "href": "./acq/acq1.json"},
    ]})
    items = [
        _item("pan-cloudy", "WV01", 40, ["pan_analytic"]),
        _item("ms-clear", "WV02", 0, ["ms_analytic", "pan_analytic"]),
        _item("ms-cloudy", "WV03", 55, ["ms_analytic", "pan_analytic"]),
    ]
    _write(tmp_path / "event-a/acq/acq1.json", {"type": "Collection", "id": "acq1", "links": [
        {"rel": "item", "href": f"../items/{i['id']}.json"} for i in items
    ]})
    for i in items:
        _write(tmp_path / f"event-a/items/{i['id']}.json", i)
        for key in i["assets"]:
            (tmp_path / f"event-a/items/{i['id']}-{key}.tif").write_bytes(b"tif")
    return tmp_path / "catalog.json"


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
