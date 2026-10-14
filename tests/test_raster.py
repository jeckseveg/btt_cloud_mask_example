import numpy as np
import pytest
import rasterio

from example_cloud_detector.raster import pick_asset, read_scene, to_source_grid, write_mask


def test_pick_asset_by_common_name(ms_item):
    key, idx = pick_asset(ms_item, ("red", "green", "nir08"))
    assert key == "ms_analytic" and idx == {"red": 5, "green": 3, "nir08": 7}


def test_pick_asset_falls_back_to_pan(pan_item):
    key, idx = pick_asset(pan_item, ("red", "green", "nir08"))
    assert key == "pan_analytic" and set(idx.values()) == {1}


def test_read_native(ms_item):
    scene = read_scene(ms_item, ("red", "nir08"))
    assert scene.data.shape == (2, 64, 64) and scene.res == pytest.approx(2.0)
    assert scene.data.max() == pytest.approx(0.6)  # scaled to reflectance
    assert not scene.valid[:, :16].any() and scene.valid[:, 16:].all()


def test_read_resampled_and_back(ms_item, tmp_path):
    scene = read_scene(ms_item, ("red",), res=8.0)
    assert scene.data.shape == (1, 16, 16) and scene.res == pytest.approx(8.0)
    mask = np.ones((16, 16), dtype=np.uint8)
    back = to_source_grid(mask, scene)
    assert back.shape == (64, 64) and (back == 1).all()
    path = write_mask(tmp_path / "m.tif", back, scene.source_transform, scene.crs)
    with rasterio.open(path) as ds:
        assert ds.dtypes[0] == "uint8" and ds.nodata == 0 and ds.tags(1)["class_2"] == "cloud"
