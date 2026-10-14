"""Simple functions for finding Maxar images, loading them, and making cloud masks.

Everything returns plain numpy arrays plus a rasterio profile (a dict with the map projection,
pixel-to-map transform, nodata value, etc.), so it works with numpy, matplotlib and rasterio.

Typical use::

    import btt_cloud_mask_example as bcm
    import matplotlib.pyplot as plt

    urls = bcm.find_images("Hurricane-Ian-9-26-2022", n=3, min_cloud=20)
    data, profile = bcm.load_image(urls[0])      # numpy (bands, height, width), reflectance 0-1
    mask, mask_profile = bcm.create_mask(urls[0])  # numpy (height, width): 0 no data, 1 clear, 2 cloud, 3 shadow
    plt.imshow(bcm.rgb(data))
    bcm.compare(my_prediction, mask)             # how close is your model?
"""

from __future__ import annotations

from pathlib import Path
from urllib.error import HTTPError

import numpy as np
import pystac
import rasterio
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError
from rasterio.warp import reproject

from btt_cloud_mask_example.detectors import DETECTORS, get_detector
from btt_cloud_mask_example.pipeline import load_item
from btt_cloud_mask_example.raster import (
    CLASS_NAMES, CLOUD, NODATA, REMOTE_GDAL_ENV, band_indexes, read_scene,
)
from btt_cloud_mask_example.stac import find_items, normalize_url

MAXAR_CATALOG = "https://maxar-opendata.s3.amazonaws.com/events/catalog.json"
BROWSE_URL = "https://browser.moregeo.it/external/maxar-opendata.s3.amazonaws.com/events/catalog.json"
DEFAULT_MODEL = "omnicloudmask"
DEFAULT_BANDS = ("red", "green", "blue", "nir")

#: Mask values and what they mean.
CLASSES = {0: "no data", 1: "clear", 2: "cloud", 3: "cloud shadow"}

# Friendly band names -> the STAC `eo:bands` common names Maxar uses.
BAND_ALIASES = {"nir": "nir08", "nir1": "nir08", "nir2": "nir09", "red_edge": "rededge", "panchromatic": "pan"}
MODEL_ALIASES = {"omni": "omnicloudmask", "ocm": "omnicloudmask", "csmask": "ukis", "ukis-csmask": "ukis",
                 "cs12": "cloudsen12"}


class CloudMaskError(Exception):
    """A problem with the inputs, explained in plain language."""


# ----------------------------------------------------------------------------- finding images

def find_images(event, n=5, min_cloud=None, max_cloud=None, sensors=None, min_coverage=0.5):
    """Return up to `n` image URLs from a Maxar Open Data event.

    Args:
        event: event name, e.g. "Hurricane-Ian-9-26-2022". Browse events at
            https://browser.moregeo.it/external/maxar-opendata.s3.amazonaws.com/events/catalog.json
        n: how many images to return.
        min_cloud, max_cloud: keep images whose cloud cover (Maxar's estimate, 0-100 %) is in range.
        sensors: satellites to include, e.g. ["WV02", "WV03", "GE01"]. Default: any with
            multispectral bands. Add "WV01" to include panchromatic-only images.
        min_coverage: skip images whose tile is mostly empty (edges of the satellite's path).
            0.5 means at least half the tile has image data; 0 keeps everything.

    Returns:
        A list of image URLs to pass to `load_image` or `create_mask`.

    Example:
        >>> urls = find_images("Hurricane-Ian-9-26-2022", n=3, min_cloud=20)
    """
    pan_ok = sensors is not None and "WV01" in sensors
    try:
        items = find_items(MAXAR_CATALOG, event, platforms=sensors, min_cloud=min_cloud,
                           max_cloud=max_cloud, required_assets=None if pan_ok else ["ms_analytic"],
                           min_coverage=min_coverage or None, max_items=n)
    except ValueError:
        raise CloudMaskError(f"There is no event called '{event}'. Event names are listed at {BROWSE_URL}") from None
    if not items:
        raise CloudMaskError(f"No images in '{event}' matched those filters. Try a wider cloud range or fewer filters.")
    return [item.get_self_href() for item in items]


# ----------------------------------------------------------------------------- images

def load_image(image, bands=DEFAULT_BANDS, resolution=None):
    """Load an image's pixels as reflectance values between 0 and 1.

    Args:
        image: an image URL (from `find_images`), a STAC Browser link, or a downloaded folder.
        bands: which bands to load, in order. Default: red, green, blue, nir. Others include
            "coastal", "yellow", "rededge", "nir2" (WorldView-2/3 only) and "pan".
        resolution: pixel size in metres. Default: the image's own resolution (about 1.2-3.5 m).
            Use the same value in `create_mask` so the two line up pixel for pixel.

    Returns:
        (data, profile):
        - data: numpy float32 array shaped (bands, height, width), in the order of `bands`.
          Pixels that are 0 in every band are "no data" (the empty edges of an image).
        - profile: rasterio profile dict (crs, transform, width, height, count, dtype, nodata),
          ready for `rasterio.open(path, "w", **profile)`.

    Example:
        >>> data, profile = load_image(url)
        >>> nir = data[3]
    """
    item = _to_item(image)
    wanted = [BAND_ALIASES.get(b.lower(), b.lower()) for b in bands]
    if wanted != ["pan"]:
        _check_bands(item, wanted, list(bands))
    scene = _read(lambda: read_scene(item, wanted, resolution), item)
    return scene.data, _profile(scene, count=len(wanted), dtype="float32")


def rgb(data):
    """Turn image data into an (height, width, 3) array for `plt.imshow`.

    Uses the first three bands as red, green, blue (the default `load_image` order), or
    grey for a single band, and stretches brightness so the picture is easy to see.
    """
    data = np.asarray(data)
    arr = np.moveaxis(data[:3], 0, -1) if data.shape[0] >= 3 else np.repeat(data[0][..., None], 3, axis=-1)
    valid = data.any(axis=0)
    values = arr[valid]
    lo, hi = np.percentile(values, [2, 98]) if values.size else (0, 1)
    return np.clip((arr - lo) / max(hi - lo, 1e-6), 0, 1) * valid[..., None]


# ----------------------------------------------------------------------------- masks

def create_mask(image, model=DEFAULT_MODEL, resolution=None, save_to=None, **options):
    """Make a cloud mask for an image with a pretrained model.

    Args:
        image: an image URL (from `find_images`), a STAC Browser link, or a downloaded folder.
        model: "omnicloudmask" (default, most accurate), "ukis" or "cloudsen12". The last two
            need extra installs: pip install "btt_cloud_mask_example[all]".
        resolution: pixel size in metres. Default: the image's own resolution, so the mask lines
            up with `load_image(image)` pixel for pixel.
        save_to: optional path to also save the mask as a GeoTIFF.
        **options: advanced model settings, e.g. thin_is_cloud=False or min_cloud_reflectance=0.

    Returns:
        (mask, profile):
        - mask: numpy uint8 array shaped (height, width): 0 no data, 1 clear, 2 cloud,
          3 cloud shadow (see `CLASSES`).
        - profile: rasterio profile dict, ready for `rasterio.open(path, "w", **profile)`.

    Example:
        >>> mask, profile = create_mask(url)
        >>> (mask == 2).mean()      # share of pixels that are cloud (including no-data pixels)
    """
    name = MODEL_ALIASES.get(model.lower(), model.lower())
    if name not in DETECTORS:
        raise CloudMaskError(f"Unknown model '{model}'. Choose one of: {', '.join(DETECTORS)}")
    item = _to_item(image)
    pan_only = "ms_analytic" not in item.assets
    if pan_only and not DETECTORS[name].supports_pan:
        raise CloudMaskError(f"This image is panchromatic only ({item.properties.get('platform')}), and "
                             f"'{name}' needs colour bands. Use model='omnicloudmask' instead.")
    if pan_only and resolution is None:
        # Pan pixels are ~0.5 m; running at ~4x that matches multispectral resolution and is much faster.
        resolution = 4 * _asset_resolution(item, "pan_analytic")
    try:
        detector = get_detector(name, res=resolution, **options)
    except TypeError as err:
        raise CloudMaskError(f"Unknown option for '{name}': {err}") from None
    try:
        detector._import()
    except ImportError as err:
        raise CloudMaskError(str(err)) from None
    scene = _read(lambda: read_scene(item, detector.bands, detector.res), item)
    if min(scene.valid.shape) < 32:
        raise CloudMaskError(f"At {scene.res:.1f} m the image is only {scene.valid.shape[1]}x{scene.valid.shape[0]} "
                             "pixels; the models need at least 32x32. Use a smaller resolution number.")
    mask = detector.detect(scene)
    profile = _profile(scene, count=1, dtype="uint8", nodata=NODATA, compress="deflate")
    if save_to:
        Path(save_to).parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(save_to, "w", **profile) as dst:
            dst.write(mask, 1)
            dst.update_tags(1, **{f"class_{v}": n for v, n in CLASS_NAMES.items()})
    return mask, profile


# ----------------------------------------------------------------------------- comparing

def compare(prediction, reference):
    """Score a predicted cloud mask against a reference mask.

    Args:
        prediction: your mask, as a numpy array shaped (height, width). Any of: True/False
            (True = cloud); 0/1 (1 = cloud); probabilities from 0 to 1 (above 0.5 = cloud); or
            the class values 0-3 from `create_mask`. A GeoTIFF path also works.
        reference: the mask to compare against, usually the mask from `create_mask`
            (class values 0-3; "no data" pixels are ignored). A GeoTIFF path also works.

    Arrays must have the same shape: use the same `resolution` in `load_image` and
    `create_mask`. GeoTIFF files are lined up automatically.

    Returns:
        A dict with iou, precision, recall, f1 and accuracy for the cloud class, plus the
        cloud fraction of each mask and the number of pixels compared.
    """
    pred, pred_geo = _prediction_cloud(prediction)
    ref, ref_geo = _reference_cloud(reference)
    if pred[0].shape != ref[0].shape:
        if pred_geo and ref_geo:
            pred = _regrid(pred, pred_geo, ref[0].shape, ref_geo)
        else:
            raise CloudMaskError(
                f"The masks are different sizes: prediction {pred[0].shape}, reference {ref[0].shape}. "
                "Load the image and make the mask at the same resolution, e.g. load_image(url) and create_mask(url).")
    (p_cloud, p_valid), (r_cloud, r_valid) = pred, ref
    valid = p_valid & r_valid
    p, r = p_cloud[valid], r_cloud[valid]
    tp, fp, fn = int((p & r).sum()), int((p & ~r).sum()), int((~p & r).sum())
    n = int(valid.sum())
    div = lambda a, b: round(a / b, 4) if b else float("nan")
    return dict(iou=div(tp, tp + fp + fn), precision=div(tp, tp + fp), recall=div(tp, tp + fn),
                f1=div(2 * tp, 2 * tp + fp + fn), accuracy=div(n - fp - fn, n),
                prediction_cloud_fraction=div(int(p.sum()), n), reference_cloud_fraction=div(int(r.sum()), n),
                pixels=n)


def _read_tif(path):
    with rasterio.open(path) as ds:
        return ds.read(1), (ds.transform, ds.crs), ds.tags(1)


def _as_2d(arr, label):
    arr = np.asarray(arr)
    if arr.ndim == 3 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.ndim != 2:
        raise CloudMaskError(f"The {label} should be a 2-D (height, width) array; got shape {arr.shape}.")
    return arr


def _prediction_cloud(mask):
    """-> ((cloud bool, valid bool), (transform, crs) or None) for a student's prediction."""
    geo = None
    if isinstance(mask, (str, Path)):
        mask, geo, tags = _read_tif(mask)
        if tags.get(f"class_{CLOUD}") == "cloud":  # one of our masks
            return (mask == CLOUD, mask != NODATA), geo
    arr = _as_2d(mask, "prediction")
    valid = np.ones(arr.shape, bool)
    if arr.dtype == bool:
        return (arr, valid), geo
    if np.issubdtype(arr.dtype, np.floating) and np.nanmin(arr) >= 0 and np.nanmax(arr) <= 1:
        return (arr > 0.5, ~np.isnan(arr)), geo
    values = set(np.unique(arr).tolist())
    if values <= {0, 1}:
        return (arr == 1, valid), geo
    if values <= set(CLASSES):
        return (arr == CLOUD, arr != NODATA), geo
    raise CloudMaskError("Couldn't read the prediction: use True/False, 0/1 (1 = cloud), probabilities 0-1, "
                         "or the class values 0 no data, 1 clear, 2 cloud, 3 shadow.")


def _reference_cloud(mask):
    """-> ((cloud bool, valid bool), geo) for a reference mask with class values 0-3."""
    geo = None
    if isinstance(mask, (str, Path)):
        mask, geo, _ = _read_tif(mask)
    arr = _as_2d(mask, "reference")
    if not set(np.unique(arr).tolist()) <= set(CLASSES):
        raise CloudMaskError("The reference should be a mask from create_mask (values 0 no data, 1 clear, "
                             "2 cloud, 3 shadow). Did you swap prediction and reference?")
    return (arr == CLOUD, arr != NODATA), geo


def _regrid(mask, src_geo, shape, dst_geo):
    out = []
    for arr in mask:
        dst = np.zeros(shape, np.uint8)
        reproject(arr.astype(np.uint8), dst, src_transform=src_geo[0], src_crs=src_geo[1],
                  dst_transform=dst_geo[0], dst_crs=dst_geo[1], resampling=Resampling.nearest)
        out.append(dst.astype(bool))
    return tuple(out)


# ----------------------------------------------------------------------------- helpers

def _profile(scene, **extra):
    height, width = scene.valid.shape
    profile = dict(driver="GTiff", width=width, height=height, crs=scene.crs, transform=scene.transform, nodata=0)
    profile.update(extra)
    return profile


def _to_item(image):
    if isinstance(image, pystac.Item):
        return image
    text = normalize_url(str(image))
    if text.endswith(("catalog.json", "collection.json")):
        raise CloudMaskError("That link is a collection of images, not a single image. "
                             "Use find_images(event) to get image links.")
    try:
        return load_item(text)
    except Exception as err:
        missing = isinstance(err.__cause__, HTTPError) or isinstance(err, (FileNotFoundError, HTTPError))
        hint = "Check the link, or get one from find_images()." if missing else str(err)
        raise CloudMaskError(f"Couldn't open the image at {text}. {hint}") from None


def _check_bands(item, wanted, asked):
    if "ms_analytic" not in item.assets:
        raise CloudMaskError(f"This image is panchromatic only ({item.properties.get('platform')}). "
                             "Load it with bands=['pan'].")
    available = band_indexes(item, "ms_analytic")
    missing = [a for a, w in zip(asked, wanted) if w not in available]
    if missing:
        raise CloudMaskError(f"This {item.properties.get('platform')} image has no {', '.join(missing)} band. "
                             f"It has: {', '.join(available)}")


def _asset_resolution(item, key):
    transform = item.assets[key].extra_fields.get("proj:transform")
    if transform:
        return abs(transform[0])
    href = item.assets[key].get_absolute_href()
    with rasterio.Env(**REMOTE_GDAL_ENV), rasterio.open(("/vsicurl/" if href.startswith("http") else "") + href) as ds:
        return abs(ds.transform.a)


def _read(fn, item):
    try:
        return fn()
    except RasterioIOError as err:
        if "404" in str(err):
            raise CloudMaskError(f"The files for image {item.id} are missing from the server "
                                 "(a known problem with some catalog entries). Try another image.") from None
        raise
