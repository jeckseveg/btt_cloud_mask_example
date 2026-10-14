"""Prebuilt cloud detectors behind one interface.

Each detector reads the bands it needs from a STAC item, runs a pretrained model and returns a
uint8 mask with the shared classes in `btt_cloud_mask_example.raster` (0 nodata, 1 clear,
2 cloud, 3 cloud shadow). Model packages are optional extras and imported lazily.
"""

from btt_cloud_mask_example.detectors.base import Detector
from btt_cloud_mask_example.detectors.cloudsen12 import CloudSEN12
from btt_cloud_mask_example.detectors.omnicloudmask import OmniCloudMask
from btt_cloud_mask_example.detectors.ukis import UkisCSmask

DETECTORS = {d.name: d for d in (OmniCloudMask, UkisCSmask, CloudSEN12)}


def get_detector(name, **kwargs):
    """Instantiate a detector by name: 'omnicloudmask', 'ukis', or 'cloudsen12'."""
    try:
        return DETECTORS[name](**kwargs)
    except KeyError:
        raise ValueError(f"Unknown detector '{name}'. Choose from {sorted(DETECTORS)}") from None


__all__ = ["DETECTORS", "Detector", "get_detector"]
