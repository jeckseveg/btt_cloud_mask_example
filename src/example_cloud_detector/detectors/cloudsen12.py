"""CloudSEN12 `dtacs4bands` model (https://github.com/IPL-UV/cloudsen12_models).

Code LGPL-3.0, weights CC-BY-NC-4.0. Trained on Sentinel-2 L1C NIR/red/green/blue.
"""

import numpy as np

from example_cloud_detector.detectors.base import Detector
from example_cloud_detector.raster import CLEAR, CLOUD, SHADOW


class CloudSEN12(Detector):
    name = "cloudsen12"
    bands = ("nir08", "red", "green", "blue")
    extra = "cloudsen12"
    module = "cloudsen12_models.cloudsen12"

    def __init__(self, res="default", min_cloud_reflectance=0.08, thin_is_cloud=True, device="cpu"):
        """`thin_is_cloud`: count the "thin cloud" class as cloud (else clear)."""
        super().__init__(res, min_cloud_reflectance)
        self.thin_is_cloud = thin_is_cloud
        self.device = device
        self._model = None

    def predict(self, scene):
        if self._model is None:
            self._model = self._import().load_model_by_name("dtacs4bands", device=self.device)
        labels = np.asarray(self._model.predict(scene.data))  # 0 clear, 1 thick, 2 thin, 3 shadow
        cloud = (labels == 1) | ((labels == 2) & self.thin_is_cloud)
        return np.select([labels == 3, cloud], [SHADOW, CLOUD], CLEAR)
