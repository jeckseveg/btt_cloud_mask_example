"""OmniCloudMask (https://github.com/DPIRD-DMA/OmniCloudMask), MIT licence.

Sensor-agnostic model trained on Sentinel-2; needs red, green and NIR. Designed for 10-50 m.
"""

import numpy as np

from example_cloud_detector.detectors.base import Detector
from example_cloud_detector.raster import CLEAR, CLOUD, SHADOW


class OmniCloudMask(Detector):
    name = "omnicloudmask"
    bands = ("red", "green", "nir08")
    extra = ""  # installed by default
    module = "omnicloudmask"
    supports_pan = True

    def __init__(self, res="default", min_cloud_reflectance=0.08, thin_is_cloud=True, inference_device=None, **kwargs):
        """`thin_is_cloud`: count OmniCloudMask's "thin cloud" class as cloud (else clear)."""
        super().__init__(res, min_cloud_reflectance)
        self.thin_is_cloud = thin_is_cloud
        self.kwargs = dict(kwargs, inference_device=inference_device) if inference_device else kwargs

    def predict(self, scene):
        ocm = self._import()
        data = scene.data.copy()
        if scene.asset == "pan_analytic":
            data[2] = 0  # no NIR: OmniCloudMask is trained to accept a zeroed NIR band
        labels = ocm.predict_from_array(data, **self.kwargs)[0]  # 0 clear, 1 thick, 2 thin, 3 shadow
        cloud = (labels == 1) | ((labels == 2) & self.thin_is_cloud)
        return np.select([labels == 3, cloud], [SHADOW, CLOUD], CLEAR)
