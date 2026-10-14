import numpy as np
import pytest
import rasterio

import example_cloud_detector as ecd
from example_cloud_detector import api


def test_load_image_defaults(ms_item):
    img = ecd.load_image(ms_item)
    assert img.data.shape == (4, 64, 64) and img.bands == ["red", "green", "blue", "nir"]
    assert img.resolution == pytest.approx(2.0) and img.sensor == "WV02"
    assert (img.band("nir") == img.data[3]).all() and (img.band("NIR") == img.band("nir08")).all()
    assert img.rgb().shape == (64, 64, 3)
    assert not img.valid[:, :16].any()
    assert "WV02" in repr(img)


def test_load_image_resolution_and_bands(tmp_path):
    from conftest import make_item

    item = make_item(tmp_path)
    img = ecd.load_image(str(tmp_path), bands=["coastal", "nir2"], resolution=8)
    assert img.data.shape == (2, 16, 16)
    with pytest.raises(ecd.CloudMaskError, match="no swir"):
        ecd.load_image(item, bands=["swir"])


def test_load_image_pan_only(pan_item):
    with pytest.raises(ecd.CloudMaskError, match="panchromatic"):
        ecd.load_image(pan_item)
    assert ecd.load_image(pan_item, bands=["pan"]).data.shape == (1, 64, 64)


def test_create_mask_defaults_to_omnicloudmask(ms_item, tmp_path):
    mask = ecd.create_mask(ms_item, save_to=tmp_path / "out" / "m.tif")
    img = ecd.load_image(ms_item)
    assert mask.model == "omnicloudmask" and mask.shape == img.shape
    assert mask.data.dtype == np.uint8 and set(np.unique(mask.data)) <= {0, 1, 2, 3}
    assert (mask.data[:, :16] == 0).all()
    assert 0 <= mask.cloud_fraction <= 1 and "omnicloudmask" in repr(mask)
    with rasterio.open(tmp_path / "out" / "m.tif") as ds:
        assert (ds.read(1) == mask.data).all()


def test_create_mask_friendly_errors(ms_item, pan_item):
    with pytest.raises(ecd.CloudMaskError, match="Unknown model"):
        ecd.create_mask(ms_item, model="magic")
    with pytest.raises(ecd.CloudMaskError, match="panchromatic"):
        ecd.create_mask(pan_item, model="ukis")
    with pytest.raises(ecd.CloudMaskError, match="collection of images"):
        ecd.create_mask("https://example.com/events/catalog.json")
    with pytest.raises(ecd.CloudMaskError, match="Couldn't open"):
        ecd.create_mask("/no/such/folder")


def test_create_mask_pan_only_uses_coarser_grid(tmp_path):
    from conftest import make_item

    item = make_item(tmp_path, ms=False, size=256)
    mask = ecd.create_mask(item)  # omnicloudmask handles pan-only images, at 4x the pan pixel size
    assert mask.resolution == pytest.approx(8.0) and mask.shape == (64, 64)


def test_create_mask_too_small(ms_item):
    with pytest.raises(ecd.CloudMaskError, match="at least 32x32"):
        ecd.create_mask(ms_item, resolution=8)


def _mask(data, res=2.0):
    from rasterio.transform import from_origin

    return api.CloudMask(data=np.asarray(data, np.uint8), model="test", resolution=res, crs="EPSG:32617",
                         transform=from_origin(400000, 3000000, res, res))


def test_compare_input_types():
    ref = _mask([[0, 1, 2, 2], [1, 1, 2, 3]])  # nodata pixel at [0, 0] is ignored
    cloud = np.array([[True, False, True, False], [False, False, True, False]])
    for pred in (cloud, cloud.astype(int), cloud * 0.9, np.where(cloud, 2, 1)):
        s = ecd.compare(pred, ref)
        assert s["pixels"] == 7 and s["iou"] == pytest.approx(2 / 3, abs=1e-3) and s["precision"] == 1.0
    assert ecd.compare(ref, ref)["iou"] == 1.0


def test_compare_shapes():
    ref = _mask(np.full((4, 4), 2))
    with pytest.raises(ecd.CloudMaskError, match="different sizes"):
        ecd.compare(np.ones((2, 2), bool), ref)
    coarse = _mask(np.full((2, 2), 2), res=4.0)  # same footprint, half the pixels
    assert ecd.compare(coarse, ref)["iou"] == 1.0


def test_compare_reads_geotiffs(tmp_path):
    clear = _mask(np.ones((4, 4)))  # our own mask with no cloud: values are only 0/1
    path = clear.save(tmp_path / "clear.tif")
    assert ecd.compare(path, clear)["prediction_cloud_fraction"] == 0


def test_find_images(catalog, monkeypatch):
    monkeypatch.setattr(api, "MAXAR_CATALOG", str(catalog))
    assert len(ecd.find_images("event-a")) == 2  # multispectral only by default
    assert len(ecd.find_images("event-a", sensors=["WV01", "WV02", "WV03"])) == 3
    assert ecd.find_images("event-a", min_cloud=50)[0].endswith("ms-cloudy.json")
    with pytest.raises(ecd.CloudMaskError, match="no event"):
        ecd.find_images("nope")
    with pytest.raises(ecd.CloudMaskError, match="No images"):
        ecd.find_images("event-a", min_cloud=99)
