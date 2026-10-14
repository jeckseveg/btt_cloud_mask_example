"""Simple functions for finding Maxar images, loading them, and making cloud masks.

Typical use::

    import example_cloud_detector as ecd

    urls = ecd.find_images("Hurricane-Ian-9-26-2022", n=3, min_cloud=20)
    image = ecd.load_image(urls[0])          # pixels for your own model
    mask = ecd.create_mask(urls[0])          # reference cloud mask (OmniCloudMask)
    mask.plot(image)
    ecd.compare(my_prediction, mask)         # how close is your model?
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError

import numpy as np
import pystac
import rasterio
from rasterio.enums import Resampling
from rasterio.errors import RasterioIOError
from rasterio.warp import reproject

from example_cloud_detector.detectors import DETECTORS, get_detector
from example_cloud_detector.pipeline import load_item
from example_cloud_detector.raster import (
    CLASS_NAMES, CLEAR, CLOUD, NODATA, REMOTE_GDAL_ENV, SHADOW, band_indexes, read_scene, write_mask,
)
from example_cloud_detector.stac import find_items, normalize_url

MAXAR_CATALOG = "https://maxar-opendata.s3.amazonaws.com/events/catalog.json"
BROWSE_URL = "https://browser.moregeo.it/external/maxar-opendata.s3.amazonaws.com/events/catalog.json"
DEFAULT_MODEL = "omnicloudmask"
DEFAULT_BANDS = ("red", "green", "blue", "nir")

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

@dataclass(repr=False)
class Image:
    """Pixels of one image as reflectance (0-1), plus where they are on Earth.

    Attributes:
        data: numpy array shaped (bands, height, width), float32 reflectance.
        bands: band names, in the same order as `data`.
        valid: (height, width) True where there is image data (False at the empty edges).
        resolution: pixel size in metres.
        crs, transform: map projection and pixel-to-map transform (for saving GeoTIFFs).
    """

    data: np.ndarray
    bands: list
    valid: np.ndarray
    resolution: float
    crs: object
    transform: object
    item: pystac.Item = field(default=None)

    @property
    def url(self):
        return self.item.get_self_href()

    @property
    def sensor(self):
        return self.item.properties.get("platform")

    @property
    def shape(self):
        return self.valid.shape

    def band(self, name):
        """One band as a (height, width) array, e.g. `image.band("nir")`."""
        names = [BAND_ALIASES.get(b, b) for b in self.bands]
        key = BAND_ALIASES.get(name.lower(), name.lower())
        if key not in names:
            raise CloudMaskError(f"This image has no '{name}' band. It has: {', '.join(self.bands)}")
        return self.data[names.index(key)]

    def rgb(self):
        """A (height, width, 3) array scaled 0-1 for display (grayscale if there is no colour)."""
        names = [BAND_ALIASES.get(b, b) for b in self.bands]
        if all(c in names for c in ("red", "green", "blue")):
            arr = np.stack([self.band(c) for c in ("red", "green", "blue")], axis=-1)
        else:
            arr = np.repeat(self.data[0][..., None], 3, axis=-1)
        values = arr[self.valid]
        lo, hi = (np.percentile(values, [2, 98]) if values.size else (0, 1))
        return np.clip((arr - lo) / max(hi - lo, 1e-6), 0, 1) * self.valid[..., None]

    def plot(self, ax=None):
        """Show the image (true colour where available)."""
        import matplotlib.pyplot as plt

        ax = ax or plt.subplots(figsize=(6, 6))[1]
        ax.imshow(self.rgb())
        ax.set_title(f"{self.sensor} {self.item.id}", fontsize=9)
        ax.axis("off")
        return ax

    def __repr__(self):
        return (f"Image(sensor={self.sensor}, bands={self.bands}, shape={self.shape}, "
                f"resolution={self.resolution:.2f} m, url={self.url})")


def load_image(image, bands=DEFAULT_BANDS, resolution=None):
    """Load an image's pixels as reflectance values between 0 and 1.

    Args:
        image: an image URL (from `find_images`), a STAC Browser link, or a downloaded folder.
        bands: which bands to load, in order. Default: red, green, blue, nir. Others include
            "coastal", "yellow", "rededge", "nir2" (WorldView-2/3 only) and "pan".
        resolution: pixel size in metres. Default: the image's own resolution (about 1.2-3.5 m).
            Use the same value in `create_mask` so the two line up pixel for pixel.

    Returns:
        An `Image`. `image.data` is a numpy array shaped (bands, height, width).

    Example:
        >>> img = load_image(url)
        >>> img.band("nir").mean()
    """
    item = _to_item(image)
    wanted = [BAND_ALIASES.get(b.lower(), b.lower()) for b in bands]
    if wanted != ["pan"]:
        _check_bands(item, wanted, list(bands))
    scene = _read(lambda: read_scene(item, wanted, resolution), item)
    return Image(data=scene.data, bands=list(bands), valid=scene.valid, resolution=scene.res,
                 crs=scene.crs, transform=scene.transform, item=item)


# ----------------------------------------------------------------------------- masks

@dataclass(repr=False)
class CloudMask:
    """A cloud mask: one number per pixel.

    0 = no data, 1 = clear, 2 = cloud, 3 = cloud shadow.

    Attributes:
        data: numpy uint8 array shaped (height, width).
        model: the model that made it.
        resolution: pixel size in metres.
        crs, transform: map projection and pixel-to-map transform.
    """

    data: np.ndarray
    model: str
    resolution: float
    crs: object
    transform: object
    item: pystac.Item = field(default=None)

    CLASSES = {NODATA: "no data", CLEAR: "clear", CLOUD: "cloud", SHADOW: "cloud shadow"}

    @property
    def url(self):
        return self.item.get_self_href() if self.item else None

    @property
    def shape(self):
        return self.data.shape

    @property
    def cloud(self):
        """True where there is cloud."""
        return self.data == CLOUD

    def _fraction(self, cls):
        valid = self.data != NODATA
        return float((self.data[valid] == cls).mean()) if valid.any() else 0.0

    @property
    def cloud_fraction(self):
        """Share of image pixels that are cloud (0-1)."""
        return self._fraction(CLOUD)

    @property
    def shadow_fraction(self):
        return self._fraction(SHADOW)

    @property
    def clear_fraction(self):
        return self._fraction(CLEAR)

    def save(self, path):
        """Save as a GeoTIFF that opens in QGIS/rasterio. Returns the path."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        return write_mask(path, self.data, self.transform, self.crs)

    def plot(self, image=None, ax=None):
        """Show the mask, next to `image` (from `load_image`) if you pass one."""
        import matplotlib.pyplot as plt
        from matplotlib.colors import ListedColormap
        from matplotlib.patches import Patch

        colors = ["#000000", "#2b8a3e", "#f1f3f5", "#7048e8"]
        if image is not None:
            fig, (ax_img, ax) = plt.subplots(1, 2, figsize=(12, 6))
            image.plot(ax_img)
        ax = ax or plt.subplots(figsize=(6, 6))[1]
        ax.imshow(self.data, cmap=ListedColormap(colors), vmin=0, vmax=3, interpolation="nearest")
        ax.legend(handles=[Patch(color=c, label=self.CLASSES[i]) for i, c in enumerate(colors)],
                  loc="lower right", fontsize=8)
        ax.set_title(f"{self.model}: {100 * self.cloud_fraction:.0f}% cloud", fontsize=9)
        ax.axis("off")
        return ax

    def __repr__(self):
        return (f"CloudMask(model={self.model}, cloud={100 * self.cloud_fraction:.1f}%, "
                f"shadow={100 * self.shadow_fraction:.1f}%, clear={100 * self.clear_fraction:.1f}%, "
                f"shape={self.shape}, resolution={self.resolution:.2f} m)")


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
        A `CloudMask`. `mask.data` is a numpy array: 0 no data, 1 clear, 2 cloud, 3 cloud shadow.

    Example:
        >>> mask = create_mask(url)
        >>> mask.cloud_fraction
        0.37
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
    mask = CloudMask(data=detector.detect(scene), model=name, resolution=scene.res, crs=scene.crs,
                     transform=scene.transform, item=item)
    if save_to:
        mask.save(save_to)
    return mask


# ----------------------------------------------------------------------------- comparing

def compare(prediction, reference):
    """Score a predicted cloud mask against a reference mask.

    Args:
        prediction: your mask. Any of: a True/False array (True = cloud); a 0/1 array (1 = cloud);
            a probability array (above 0.5 = cloud); a `CloudMask`; or a path to a GeoTIFF.
        reference: the mask to compare against, usually from `create_mask`. Same options.
            "No data" pixels in a `CloudMask` reference are ignored.

    Arrays must have the same shape (use the same `resolution` in `load_image` and
    `create_mask`). Masks with map information (CloudMask, GeoTIFF) are lined up automatically.

    Returns:
        A dict with iou, precision, recall, f1 and accuracy for the cloud class, plus the
        cloud fraction of each mask and the number of pixels compared.
    """
    pred, pred_geo = _as_cloud(prediction, "prediction")
    ref, ref_geo = _as_cloud(reference, "reference")
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


def _as_cloud(mask, label):
    """-> ((cloud bool array, valid bool array), (transform, crs) or None)."""
    if isinstance(mask, CloudMask):
        return (mask.data == CLOUD, mask.data != NODATA), (mask.transform, mask.crs)
    if isinstance(mask, (str, Path)):
        with rasterio.open(mask) as ds:
            arr, geo, tags = ds.read(1), (ds.transform, ds.crs), ds.tags(1)
        if tags.get(f"class_{CLOUD}") != "cloud" and set(np.unique(arr)) <= {0, 1}:  # not one of our masks
            return (arr == 1, np.ones(arr.shape, bool)), geo
        return (arr == CLOUD, arr != NODATA), geo
    arr = np.asarray(mask)
    if arr.ndim == 3 and arr.shape[0] == 1:
        arr = arr[0]
    if arr.ndim != 2:
        raise CloudMaskError(f"The {label} should be a 2-D (height, width) array; got shape {arr.shape}.")
    valid = np.ones(arr.shape, bool)
    if arr.dtype == bool:
        return (arr, valid), None
    if np.issubdtype(arr.dtype, np.floating) and np.nanmin(arr) >= 0 and np.nanmax(arr) <= 1:
        return (arr > 0.5, valid & ~np.isnan(arr)), None
    if set(np.unique(arr)) <= {0, 1}:
        return (arr == 1, valid), None
    if set(np.unique(arr)) <= set(CLASS_NAMES):
        return (arr == CLOUD, arr != NODATA), None
    raise CloudMaskError(f"Couldn't read the {label}: use True/False, 0/1 (1 = cloud), probabilities 0-1, "
                         "or the class codes 0 no data, 1 clear, 2 cloud, 3 shadow.")


def _regrid(mask, src_geo, shape, dst_geo):
    out = []
    for arr in mask:
        dst = np.zeros(shape, np.uint8)
        reproject(arr.astype(np.uint8), dst, src_transform=src_geo[0], src_crs=src_geo[1],
                  dst_transform=dst_geo[0], dst_crs=dst_geo[1], resampling=Resampling.nearest)
        out.append(dst.astype(bool))
    return tuple(out)


# ----------------------------------------------------------------------------- helpers

def _to_item(image):
    if isinstance(image, (Image, CloudMask)):
        return image.item
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
        names = [b for b in available]
        raise CloudMaskError(f"This {item.properties.get('platform')} image has no {', '.join(missing)} band. "
                             f"It has: {', '.join(names)}")


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
