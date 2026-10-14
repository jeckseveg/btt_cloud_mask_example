# example_cloud_detector

Prebuilt cloud detectors that read imagery from a public STAC collection and write cloud masks.

## Install

The cloud models are optional extras, so install the ones you want:

```bash
pip install "example_cloud_detector[omnicloudmask]"   # or [ukis], [cloudsen12], [all]
pip install -e ".[all,dev]"                           # from a clone, for development
```

| Detector | Extra | Bands used | Licence |
|----------|-------|------------|---------|
| `omnicloudmask` | `[omnicloudmask]` | red, green, NIR (pan-only WV01 supported, experimental) | MIT |
| `ukis` | `[ukis]` | blue, green, red, NIR | Apache-2.0 |
| `cloudsen12` | `[cloudsen12]` | NIR, red, green, blue | LGPL-3.0 code, CC-BY-NC-4.0 weights |

All masks use the same classes: 0 nodata, 1 clear, 2 cloud, 3 cloud shadow.

## Usage

Works with static STAC catalogs (and STAC Browser links to them). The default example source is
[Maxar Open Data](https://maxar-opendata.s3.amazonaws.com/events/catalog.json), where each
disaster event is a child collection.

```bash
# List cloudy multispectral tiles from one event without downloading
cloud-detect fetch https://maxar-opendata.s3.amazonaws.com/events/catalog.json \
    Hurricane-Ian-9-26-2022 --platform WV02 WV03 GE01 --min-cloud 20 \
    --assets ms_analytic --max-items 4 --dry-run

# Download them (drop --dry-run); files land in data/<item id>/

# Write cloud masks (one COG per item, on the source imagery grid)
cloud-detect run omnicloudmask data/*/ --out masks
cloud-detect run ukis data/*/ --res 10         # run the model at 10 m instead of source resolution
```

`run` also accepts item URLs, so imagery can be read straight from the catalog without downloading.

```python
from example_cloud_detector.stac import find_items, download_assets

items = find_items(catalog_url, "Hurricane-Ian-9-26-2022", platforms=["WV02"],
                   min_cloud=20, required_assets=["ms_analytic"], max_items=4)
for item in items:
    download_assets(item, "data", ["ms_analytic", "data-mask"])

from example_cloud_detector.pipeline import detect_item
from example_cloud_detector.detectors import get_detector

detector = get_detector("omnicloudmask")               # source resolution; res=10 for 10 m
detect_item(items[0], detector, "masks")               # -> masks/<item id>_omnicloudmask.tif
```

Maxar `ms_analytic` assets are 8-band uint16 GeoTIFFs (coastal, blue, green, yellow, red,
red edge, nir08, nir09) at ~1.85 m; `tile:clouds_percent` gives per-tile cloud cover.

See [docs/DATA.md](docs/DATA.md) for sensors, bands, formats and data gotchas, and
[docs/DETECTORS.md](docs/DETECTORS.md) for how the detectors compare.

**Data license:** Maxar Open Data imagery is CC-BY-NC-4.0. This package does not redistribute it.

## Development

```bash
pytest
python -m build          # builds sdist + wheel into dist/
twine check dist/*
```
