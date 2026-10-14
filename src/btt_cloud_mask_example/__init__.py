"""Cloud masks for Maxar Open Data imagery, from prebuilt models.

    import btt_cloud_mask_example as bcm

    urls = bcm.find_images("Hurricane-Ian-9-26-2022", n=3, min_cloud=20)
    data, profile = bcm.load_image(urls[0])     # numpy (bands, height, width) + rasterio profile
    mask = bcm.create_mask(urls[0])             # numpy bool (height, width): True = cloud
    bcm.compare(my_prediction, mask)            # iou, precision, recall, f1, accuracy
"""

__version__ = "0.2.1"

from btt_cloud_mask_example.api import (  # noqa: E402
    CloudMaskError,
    compare,
    create_mask,
    find_images,
    load_image,
    rgb,
)

__all__ = ["CloudMaskError", "compare", "create_mask", "find_images", "load_image", "rgb"]
