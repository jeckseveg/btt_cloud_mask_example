"""ukis-csmask (https://github.com/dlr-eoc/ukis-csmask), Apache-2.0 licence.

U-Net (ONNX, weights bundled with the package) trained on Sentinel-2; 4-band blue/green/red/NIR model.
"""

import warnings

import numpy as np

from btt_cloud_mask_example.detectors.base import Detector
from btt_cloud_mask_example.raster import CLEAR, CLOUD, SHADOW


class UkisCSmask(Detector):
    name = "ukis"
    bands = ("blue", "green", "red", "nir08")
    extra = "ukis"
    module = "ukis_csmask.mask"

    def __init__(self, res="default", min_cloud_reflectance=0.08, product_level="l2a",
                 providers=("CPUExecutionProvider",)):
        """`providers`: onnxruntime execution providers. CPU by default: the CoreML provider on
        macOS supports only a handful of this model's ops and is no faster."""
        super().__init__(res, min_cloud_reflectance)
        self.product_level = product_level
        self.providers = list(providers) if providers else None

    def predict(self, scene):
        mask_mod = self._import()
        img = np.ascontiguousarray(np.moveaxis(scene.data, 0, -1))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cs = mask_mod.CSmask(img, ["blue", "green", "red", "nir"], self.product_level, nodata_value=0,
                                  providers=self.providers)
        labels = cs.csm[..., 0]  # 0 clear, 1 cloud, 2 shadow
        return np.select([labels == 2, labels == 1], [SHADOW, CLOUD], CLEAR)
