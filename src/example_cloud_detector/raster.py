"""Read item bands into reflectance arrays and write masks as Cloud-Optimized GeoTIFFs."""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np
import rasterio
from affine import Affine
from rasterio.enums import Resampling
from rasterio.warp import reproject

# Maxar ARD stores reflectance as uint16 scaled by 10,000 (no scale tag); 0 is fill.
REFLECTANCE_SCALE = 10_000

# Output classes shared by every detector.
NODATA, CLEAR, CLOUD, SHADOW = 0, 1, 2, 3
CLASS_NAMES = {NODATA: "nodata", CLEAR: "clear", CLOUD: "cloud", SHADOW: "cloud_shadow"}


@dataclass
class Scene:
    """Bands of one item resampled to a common grid."""

    data: np.ndarray  # (bands, height, width) float32 reflectance
    bands: list[str]  # common names, in `data` order
    valid: np.ndarray  # (height, width) bool; False where the source is fill
    transform: Affine
    crs: object
    source_shape: tuple[int, int]  # native (height, width), for writing back to the source grid
    source_transform: Affine
    asset: str = "ms_analytic"  # which item asset the bands came from

    @property
    def res(self):
        return abs(self.transform.a)

    def band(self, name):
        return self.data[self.bands.index(name)]

    def select(self, bands):
        """Return a copy of this scene with only `bands`, in that order (for sharing one read)."""
        return replace(self, data=np.stack([self.band(b) for b in bands]), bands=list(bands))


# GDAL settings for reading remote COGs: fewer, larger HTTP range requests.
REMOTE_GDAL_ENV = dict(
    GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
    GDAL_HTTP_MERGE_CONSECUTIVE_RANGES="YES",
    GDAL_HTTP_MULTIPLEX="YES",
    GDAL_HTTP_VERSION="2",
    GDAL_HTTP_MAX_RETRY="3",
    GDAL_HTTP_RETRY_DELAY="1",
    VSI_CACHE="TRUE",
    CPL_VSIL_CURL_CHUNK_SIZE=str(4 * 1024 * 1024),
)


def _open_href(href):
    if href.startswith(("http://", "https://")):
        return rasterio.open("/vsicurl/" + href)
    return rasterio.open(href)


def band_indexes(item, asset_key):
    """Map `common_name` (or `name` when no common name) to 1-based band index for an asset."""
    bands = item.assets[asset_key].extra_fields.get("eo:bands", [])
    return {b.get("common_name", b["name"]): i + 1 for i, b in enumerate(bands)}


def pick_asset(item, wanted):
    """Return (asset_key, {band: index}) for the first asset that has every band in `wanted`.

    Falls back to the panchromatic asset (as every requested band) for pan-only sensors such as WV01.
    """
    for key in ("ms_analytic",):
        if key in item.assets:
            idx = band_indexes(item, key)
            if all(b in idx for b in wanted):
                return key, {b: idx[b] for b in wanted}
    if "pan_analytic" in item.assets:
        return "pan_analytic", {b: 1 for b in wanted}
    raise ValueError(f"Item {item.id} has no asset with bands {wanted}")


def read_scene(item, bands, res=None):
    """Read `bands` (common names) of `item` as reflectance, resampled to `res` metres.

    `res=None` reads at the asset's native resolution. Downsampling uses area averaging and
    reads from COG overviews where possible, so coarse reads of remote files are cheap.
    """
    key, idx = pick_asset(item, bands)
    with rasterio.Env(**REMOTE_GDAL_ENV), _open_href(item.assets[key].get_absolute_href()) as ds:
        native = abs(ds.transform.a)
        scale = 1.0 if res is None else native / res
        height, width = max(1, round(ds.height * scale)), max(1, round(ds.width * scale))
        raw = ds.read(
            [idx[b] for b in bands],
            out_shape=(len(bands), height, width),
            resampling=Resampling.average,
        )
        transform = ds.transform * Affine.scale(ds.width / width, ds.height / height)
        crs, source_shape, source_transform = ds.crs, (ds.height, ds.width), ds.transform
    return Scene(
        data=raw.astype("float32") / REFLECTANCE_SCALE,
        bands=list(bands),
        valid=raw.any(axis=0),
        transform=transform,
        crs=crs,
        source_shape=source_shape,
        source_transform=source_transform,
        asset=key,
    )


def to_source_grid(mask, scene):
    """Nearest-neighbour resample a class mask from the scene grid onto the source asset grid."""
    if mask.shape == scene.source_shape:
        return mask
    out = np.zeros(scene.source_shape, dtype=np.uint8)
    reproject(
        mask.astype(np.uint8), out,
        src_transform=scene.transform, src_crs=scene.crs,
        dst_transform=scene.source_transform, dst_crs=scene.crs,
        resampling=Resampling.nearest,
    )
    return out


def write_mask(path, mask, transform, crs):
    """Write a uint8 class mask as a COG with class names in the band description."""
    profile = dict(
        driver="COG", dtype="uint8", count=1, height=mask.shape[0], width=mask.shape[1],
        transform=transform, crs=crs, nodata=NODATA, compress="deflate",
        overview_resampling="nearest",
    )
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(mask.astype(np.uint8), 1)
        dst.set_band_description(1, "cloud_mask")
        dst.update_tags(1, **{f"class_{v}": n for v, n in CLASS_NAMES.items()})
    return path
