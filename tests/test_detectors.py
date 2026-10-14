import numpy as np
import pytest

from example_cloud_detector.detectors import DETECTORS, Detector, get_detector
from example_cloud_detector.raster import CLEAR, CLOUD, NODATA, read_scene


class AllCloud(Detector):
    """Stand-in model that labels every pixel cloud, to test shared post-processing."""

    name = "allcloud"
    bands = ("blue", "green", "red", "nir08")
    default_res = None

    def predict(self, scene):
        return np.full(scene.valid.shape, CLOUD, dtype=np.uint8)


def test_registry():
    assert set(DETECTORS) == {"omnicloudmask", "ukis", "cloudsen12"}
    assert get_detector("ukis", res=5).res == 5
    assert get_detector("omnicloudmask").res is None  # source resolution by default
    with pytest.raises(ValueError):
        get_detector("nope")


def test_postprocess_fill_and_dark_pixels(ms_item):
    det = AllCloud()
    mask = det.detect(read_scene(ms_item, det.bands))
    assert (mask[:, :16] == NODATA).all()  # fill
    assert (mask[16:40, 24:48] == CLOUD).all()  # bright square stays cloud
    assert (mask[50:, 50:] == CLEAR).all()  # dark surface fails the brightness floor
    assert (AllCloud(min_cloud_reflectance=0).detect(read_scene(ms_item, det.bands))[50:, 50:] == CLOUD).all()


def test_pan_only_rejected_for_multispectral_models(pan_item):
    det = AllCloud()
    with pytest.raises(ValueError, match="pan-only"):
        det.detect(read_scene(pan_item, det.bands))


@pytest.mark.parametrize("name", sorted(DETECTORS))
def test_real_models_on_synthetic_tile(name, ms_item):
    pytest.importorskip(DETECTORS[name].module)
    det = get_detector(name, res=None)
    mask = det.detect(read_scene(ms_item, det.bands, det.res))
    assert mask.shape == (64, 64) and mask.dtype == np.uint8
    assert set(np.unique(mask)) <= {0, 1, 2, 3} and (mask[:, :16] == NODATA).all()


def test_detect_item_writes_source_grid_mask(ms_item, tmp_path, monkeypatch):
    import rasterio

    from example_cloud_detector import detectors, pipeline

    monkeypatch.setattr(pipeline, "get_detector", lambda name: AllCloud(res=8.0))
    out = pipeline.detect_item(ms_item, "allcloud", tmp_path / "masks")
    with rasterio.open(out) as ds:
        assert ds.shape == (64, 64) and out.name == "17_000_TEST_allcloud.tif"
    out = pipeline.detect_item(ms_item, AllCloud(res=8.0), tmp_path / "m2", source_grid=False)
    with rasterio.open(out) as ds:
        assert ds.shape == (16, 16)
