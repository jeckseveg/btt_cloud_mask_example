"""Cloud masks for Maxar Open Data imagery, from prebuilt models.

    import example_cloud_detector as ecd

    urls = ecd.find_images("Hurricane-Ian-9-26-2022", n=3, min_cloud=20)
    image = ecd.load_image(urls[0])     # pixels as reflectance, for your own model
    mask = ecd.create_mask(urls[0])     # reference cloud mask (OmniCloudMask by default)
    ecd.compare(my_prediction, mask)    # iou, precision, recall, f1, accuracy
"""

__version__ = "0.1.0"

from example_cloud_detector.api import (  # noqa: E402
    CloudMask,
    CloudMaskError,
    Image,
    compare,
    create_mask,
    find_images,
    load_image,
)

__all__ = ["CloudMask", "CloudMaskError", "Image", "compare", "create_mask", "find_images", "load_image"]
