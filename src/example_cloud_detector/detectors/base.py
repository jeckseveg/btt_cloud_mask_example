"""Base class shared by all detectors."""

from __future__ import annotations

import importlib

import numpy as np

from example_cloud_detector.raster import CLEAR, CLOUD, NODATA, Scene


class Detector:
    name: str = ""
    bands: tuple[str, ...] = ()  # eo:bands common names, in the order the model wants
    default_res: float | None = 10.0  # metres; None means the source resolution
    extra: str = ""  # pip extra that installs the model package
    module: str = ""  # import name of the model package
    supports_pan: bool = False  # can run on pan-only items (WV01)

    def __init__(self, res="default", min_cloud_reflectance=0.08):
        """`res`: metres, None for source resolution, or "default" for the detector's default.

        `min_cloud_reflectance`: cloud pixels whose mean visible reflectance is below this are
        relabelled clear. Guards against dark, featureless tiles (open water) being called cloud.
        Set to 0 to disable.
        """
        self.res = self.default_res if res == "default" else res
        self.min_cloud_reflectance = min_cloud_reflectance

    def _import(self):
        try:
            return importlib.import_module(self.module)
        except ImportError as err:
            raise ImportError(
                f"The '{self.name}' detector needs extra packages: "
                f"pip install 'example_cloud_detector[{self.extra}]'"
            ) from err

    def predict(self, scene: Scene) -> np.ndarray:
        """Return shared-class labels for `scene` (fill handling is done by `detect`)."""
        raise NotImplementedError

    def detect(self, scene: Scene) -> np.ndarray:
        """Run the model on `scene` and apply fill and brightness post-processing."""
        if scene.asset == "pan_analytic" and not self.supports_pan:
            raise ValueError(f"The '{self.name}' detector needs multispectral bands; item is pan-only")
        mask = self.predict(scene).astype(np.uint8)
        if self.min_cloud_reflectance:
            visible = [b for b in ("red", "green", "blue") if b in scene.bands]
            brightness = np.mean([scene.band(b) for b in visible], axis=0)
            mask[(mask == CLOUD) & (brightness < self.min_cloud_reflectance)] = CLEAR
        mask[~scene.valid] = NODATA
        return mask
