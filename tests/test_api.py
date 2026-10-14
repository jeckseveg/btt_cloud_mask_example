import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

import btt_cloud_mask_example as bcm
from btt_cloud_mask_example import api


def test_load_image_returns_numpy_and_profile(ms_item, tmp_path):
    data, profile = bcm.load_image(ms_item)
    assert isinstance(data, np.ndarray) and data.dtype == np.float32 and data.shape == (4, 64, 64)
    assert profile["count"] == 4 and (profile["height"], profile["width"]) == (64, 64)
    assert profile["nodata"] == 0 and profile["transform"].a == pytest.approx(2.0)
    assert not data[:, :, :16].any()  # fill
    with rasterio.open(tmp_path / "img.tif", "w", **profile) as dst:  # profile works as-is
        dst.write(data)
    assert bcm.rgb(data).shape == (64, 64, 3)


def test_load_image_bands_and_resolution(tmp_path):
    from conftest import make_item

    item = make_item(tmp_path)
    data, profile = bcm.load_image(str(tmp_path), bands=["coastal", "nir2"], resolution=8)
    assert data.shape == (2, 16, 16) and profile["transform"].a == pytest.approx(8.0)
    nir_only, _ = bcm.load_image(item, bands=["NIR"])
    full, _ = bcm.load_image(item)
    assert (nir_only[0] == full[3]).all()
    with pytest.raises(bcm.CloudMaskError, match="no swir"):
        bcm.load_image(item, bands=["swir"])


def test_load_image_pan_only(pan_item):
    with pytest.raises(bcm.CloudMaskError, match="panchromatic"):
        bcm.load_image(pan_item)
    data, _ = bcm.load_image(pan_item, bands=["pan"])
    assert data.shape == (1, 64, 64) and bcm.rgb(data).shape == (64, 64, 3)


def test_create_mask_defaults_to_omnicloudmask(ms_item, tmp_path):
    mask, profile = bcm.create_mask(ms_item, save_to=tmp_path / "out" / "m.tif")
    data, image_profile = bcm.load_image(ms_item)
    assert mask.dtype == np.uint8 and mask.shape == data.shape[1:]
    assert profile["transform"] == image_profile["transform"] and profile["dtype"] == "uint8"
    assert set(np.unique(mask)) <= set(bcm.CLASSES) and (mask[:, :16] == 0).all()
    with rasterio.open(tmp_path / "out" / "m.tif") as ds:
        assert (ds.read(1) == mask).all() and ds.tags(1)["class_2"] == "cloud"


def test_create_mask_friendly_errors(ms_item, pan_item):
    with pytest.raises(bcm.CloudMaskError, match="Unknown model"):
        bcm.create_mask(ms_item, model="magic")
    with pytest.raises(bcm.CloudMaskError, match="panchromatic"):
        bcm.create_mask(pan_item, model="ukis")
    with pytest.raises(bcm.CloudMaskError, match="collection of images"):
        bcm.create_mask("https://example.com/events/catalog.json")
    with pytest.raises(bcm.CloudMaskError, match="Couldn't open"):
        bcm.create_mask("/no/such/folder")
    with pytest.raises(bcm.CloudMaskError, match="at least 32x32"):
        bcm.create_mask(ms_item, resolution=8)


def test_create_mask_pan_only_uses_coarser_grid(tmp_path):
    from conftest import make_item

    item = make_item(tmp_path, ms=False, size=256)
    mask, profile = bcm.create_mask(item)  # omnicloudmask handles pan-only images, at 4x the pan pixel size
    assert profile["transform"].a == pytest.approx(8.0) and mask.shape == (64, 64)


def test_compare_prediction_types():
    ref = np.array([[0, 1, 2, 2], [1, 1, 2, 3]], np.uint8)  # no-data pixel at [0, 0] is ignored
    cloud = np.array([[True, False, True, False], [False, False, True, False]])
    for pred in (cloud, cloud.astype(int), cloud * 0.9, np.where(cloud, 2, 1)):
        s = bcm.compare(pred, ref)
        assert s["pixels"] == 7 and s["iou"] == pytest.approx(2 / 3, abs=1e-3) and s["precision"] == 1.0
    assert bcm.compare(ref, ref)["iou"] == 1.0


def test_compare_errors():
    ref = np.full((4, 4), 2, np.uint8)
    with pytest.raises(bcm.CloudMaskError, match="different sizes"):
        bcm.compare(np.ones((2, 2), bool), ref)
    with pytest.raises(bcm.CloudMaskError, match="swap"):
        bcm.compare(ref, np.full((4, 4), 0.7))


def _write(path, arr, res):
    profile = dict(driver="GTiff", dtype="uint8", count=1, height=arr.shape[0], width=arr.shape[1],
                   crs="EPSG:32617", transform=from_origin(400000, 3000000, res, res), nodata=0)
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr.astype(np.uint8), 1)
    return path


def test_compare_geotiffs_on_different_grids(tmp_path):
    fine = _write(tmp_path / "fine.tif", np.full((4, 4), 2), res=2.0)
    coarse = _write(tmp_path / "coarse.tif", np.full((2, 2), 2), res=4.0)  # same footprint, half the pixels
    assert bcm.compare(coarse, fine)["iou"] == 1.0


def test_compare_reads_our_saved_masks(ms_item, tmp_path):
    mask, _ = bcm.create_mask(ms_item, save_to=tmp_path / "m.tif")
    scores = bcm.compare(tmp_path / "m.tif", mask)  # file vs the same array: identical
    assert scores["accuracy"] == 1.0 and scores["pixels"] == int((mask != 0).sum())


def test_find_images(catalog, monkeypatch):
    monkeypatch.setattr(api, "MAXAR_CATALOG", str(catalog))
    assert len(bcm.find_images("event-a")) == 2  # multispectral only by default
    assert len(bcm.find_images("event-a", sensors=["WV01", "WV02", "WV03"])) == 3
    assert bcm.find_images("event-a", min_cloud=50)[0].endswith("ms-cloudy.json")
    with pytest.raises(bcm.CloudMaskError, match="no event"):
        bcm.find_images("nope")
    with pytest.raises(bcm.CloudMaskError, match="No images"):
        bcm.find_images("event-a", min_cloud=99)
