"""Run a detector over STAC items and write cloud masks."""

from __future__ import annotations

from pathlib import Path

import pystac

from example_cloud_detector.detectors import get_detector
from example_cloud_detector.raster import read_scene, to_source_grid, write_mask


def load_item(path_or_url):
    """Load a STAC item from a local item.json, a directory containing one, or a URL."""
    path = Path(str(path_or_url))
    if path.is_dir():
        path = path / "item.json"
    return pystac.Item.from_file(str(path) if path.exists() else str(path_or_url))


def detect_item(item, detector, out_dir, source_grid=True):
    """Run `detector` (instance or name) on `item` and write `<out_dir>/<item id>_<detector>.tif`.

    The model runs at `detector.res`; with `source_grid=True` the mask is then resampled
    (nearest neighbour) onto the item's native asset grid so it lines up pixel-for-pixel
    with the imagery. Returns the output path.
    """
    if isinstance(detector, str):
        detector = get_detector(detector)
    if isinstance(item, (str, Path)):
        item = load_item(item)
    scene = read_scene(item, detector.bands, detector.res)
    mask = detector.detect(scene)
    transform = scene.transform
    if source_grid:
        mask, transform = to_source_grid(mask, scene), scene.source_transform
    out = Path(out_dir) / f"{item.id.replace('/', '_')}_{detector.name}.tif"
    out.parent.mkdir(parents=True, exist_ok=True)
    return write_mask(out, mask, transform, scene.crs)
