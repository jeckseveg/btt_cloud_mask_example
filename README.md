# btt_cloud_mask_example

Reference cloud masks for satellite images, so you can check how well **your** cloud-detection
model does.

The images come from [Maxar Open Data](https://www.maxar.com/open-data): very high resolution
(about 0.3–3.5 m) imagery of natural disasters, published as a free
[STAC catalog](https://browser.moregeo.it/external/maxar-opendata.s3.amazonaws.com/events/catalog.json).
The masks come from pretrained cloud models, [OmniCloudMask](https://github.com/DPIRD-DMA/OmniCloudMask)
by default.

## Install

```bash
pip install btt_cloud_mask_example
```

This includes OmniCloudMask. Two more models are optional:

```bash
pip install "btt_cloud_mask_example[all]"     # adds ukis-csmask and CloudSEN12
```

The first mask you make downloads OmniCloudMask's model weights (about 55 MB).

## Quickstart

```python
import example_cloud_detector as ecd

# 1. Find some cloudy images from a disaster event
urls = ecd.find_images("Hurricane-Ian-9-26-2022", n=3, min_cloud=20)

# 2. Load an image: reflectance values from 0 to 1, shaped (bands, height, width)
image = ecd.load_image(urls[0])              # bands: red, green, blue, nir
image.data.shape                             # e.g. (4, 2868, 2868)
image.plot()

# 3. Make a reference cloud mask for the same image
mask = ecd.create_mask(urls[0])
mask.cloud_fraction                          # e.g. 0.37 (share of pixels that are cloud)
mask.plot(image)                             # image and mask side by side

# 4. Compare your model's prediction against the reference
my_prediction = my_model(image.data)         # True/False, 0/1 or probabilities, shaped (height, width)
ecd.compare(my_prediction, mask)
# e.g. {'iou': 0.71, 'precision': 0.93, 'recall': 0.75, 'f1': 0.83, 'accuracy': 0.91, ...}
```

`load_image` and `create_mask` use the same pixel grid, so `image.data[:, y, x]` and
`mask.data[y, x]` are the same spot on the ground.

### What's in a mask

`mask.data` is a numpy array with one number per pixel:

| Value | Meaning |
|------:|---------|
| 0 | no data (the empty edges of an image) |
| 1 | clear |
| 2 | cloud |
| 3 | cloud shadow |

`mask.cloud` gives a True/False array of just the cloud. `mask.save("mask.tif")` writes a
GeoTIFF that opens in QGIS.

### Useful options

```python
ecd.find_images(event, n=10, min_cloud=10, max_cloud=60, sensors=["WV02", "WV03"])
ecd.load_image(url, bands=["red", "green", "blue", "nir", "rededge"])   # pick bands
ecd.load_image(url, resolution=10)                 # resample to 10 m pixels (smaller, faster)
ecd.create_mask(url, resolution=10)                # ...and a mask on the same 10 m grid
ecd.create_mask(url, model="ukis")                 # another model, for comparison
ecd.create_mask(url, save_to="masks/one.tif")
```

Event names (like `Hurricane-Ian-9-26-2022`) are listed in the
[catalog browser](https://browser.moregeo.it/external/maxar-opendata.s3.amazonaws.com/events/catalog.json).
You can also pass a link copied from the browser straight into `load_image` or `create_mask`.

### Bands

| Name | WorldView-2/3 (WV02, WV03) | GeoEye-1 (GE01), WorldView-4 (WV04) |
|------|:--:|:--:|
| `coastal`, `yellow`, `rededge`, `nir2` | ✓ | |
| `blue`, `green`, `red`, `nir` | ✓ | ✓ |

WorldView-1 (WV01) images are black-and-white only: load them with `bands=["pan"]`.
`find_images` skips them unless you ask for `sensors=["WV01", ...]`.

## Command line

```bash
cloud-detect find Hurricane-Ian-9-26-2022 --n 3 --min-cloud 20     # prints image URLs
cloud-detect mask <url> [<url> ...] --out masks                      # writes GeoTIFF masks
cloud-detect mask <url> --model ukis --resolution 10
```

## The models

| Model | Install | Uses | Licence |
|-------|---------|------|---------|
| `omnicloudmask` (default) | included | red, green, NIR | MIT |
| `ukis` | `[ukis]` | blue, green, red, NIR | Apache-2.0 |
| `cloudsen12` | `[cloudsen12]` | NIR, red, green, blue | LGPL-3.0 code, CC-BY-NC-4.0 weights |

None of them was trained on Maxar imagery. Compared with Maxar's own cloud masks on 34 cloudy
images, OmniCloudMask agreed best (cloud IoU 0.83, F1 0.90), ahead of CloudSEN12 (0.72) and
ukis (0.71). Treat the masks as a strong baseline, not ground truth. Details are in
[docs/DETECTORS.md](docs/DETECTORS.md); data quirks are in [docs/DATA.md](docs/DATA.md).

## Data licence

Maxar Open Data imagery is licensed [CC-BY-NC-4.0](https://creativecommons.org/licenses/by-nc/4.0/)
(non-commercial). This package reads it from Maxar's servers and does not redistribute it.

## For developers

The friendly functions above are built on a lower-level layer you can use directly:
`example_cloud_detector.stac` (search and download from any static STAC catalog),
`.raster` (reading bands, writing masks), `.detectors` (the model wrappers) and `.pipeline`.
The `cloud-detect fetch` and `cloud-detect run` commands expose the same layer.

```bash
git clone https://github.com/jeckseveg/example-cloud-detector-package
cd example-cloud-detector-package
pip install -e ".[all,dev]"
pytest
python -m build && twine check dist/*
```
