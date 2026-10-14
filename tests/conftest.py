import json

import numpy as np
import pystac
import pytest
import rasterio
from rasterio.transform import from_origin

MS_BANDS = ["coastal", "blue", "green", "yellow", "red", "rededge", "nir08", "nir09"]


def write_tif(path, data, res):
    with rasterio.open(
        path, "w", driver="GTiff", dtype="uint16", count=data.shape[0], height=data.shape[1],
        width=data.shape[2], crs="EPSG:32617", transform=from_origin(400000, 3000000, res, res),
    ) as dst:
        dst.write(data)


def make_item(tmp_path, ms=True, size=64, res=2.0):
    """A Maxar-like item: left quarter fill, a bright 'cloud' square, dark 'water' elsewhere."""
    rng = np.random.default_rng(0)
    bands = 8 if ms else 1
    data = (rng.random((bands, size, size)) * 200 + 300).astype("uint16")  # dark surface ~0.03
    data[:, 16:40, 24:48] = 6000  # cloud ~0.6
    data[:, :, : size // 4] = 0  # fill
    assets = {}
    if ms:
        write_tif(tmp_path / "ms.tif", data, res)
        assets["ms_analytic"] = {"href": str(tmp_path / "ms.tif"),
                                 "eo:bands": [{"name": b.upper(), "common_name": b} for b in MS_BANDS]}
    write_tif(tmp_path / "pan.tif", data[:1], res)
    assets["pan_analytic"] = {"href": str(tmp_path / "pan.tif"), "eo:bands": [{"name": "BAND_P"}]}
    item = {"type": "Feature", "stac_version": "1.0.0", "id": "17/000/TEST" if ms else "17/000/PAN",
            "geometry": None, "properties": {"datetime": "2022-01-01T00:00:00Z", "platform": "WV02" if ms else "WV01"},
            "links": [], "assets": assets}
    (tmp_path / "item.json").write_text(json.dumps(item))
    return pystac.Item.from_file(str(tmp_path / "item.json"))


@pytest.fixture
def ms_item(tmp_path):
    return make_item(tmp_path)


@pytest.fixture
def pan_item(tmp_path):
    return make_item(tmp_path, ms=False)
