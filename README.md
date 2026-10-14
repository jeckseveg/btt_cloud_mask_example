# example_cloud_detector

Prebuilt cloud detectors that read imagery from a public STAC collection and write cloud masks.

## Install

```bash
pip install example_cloud_detector          # once published
pip install -e ".[dev]"                     # from a clone, for development
```

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
```

```python
from example_cloud_detector.stac import find_items, download_assets

items = find_items(catalog_url, "Hurricane-Ian-9-26-2022", platforms=["WV02"],
                   min_cloud=20, required_assets=["ms_analytic"], max_items=4)
for item in items:
    download_assets(item, "data", ["ms_analytic", "data-mask"])
```

Maxar `ms_analytic` assets are 8-band uint16 GeoTIFFs (coastal, blue, green, yellow, red,
red edge, nir08, nir09) at ~1.85 m; `tile:clouds_percent` gives per-tile cloud cover.

See [docs/DATA.md](docs/DATA.md) for sensors, bands, formats and data gotchas.

**Data license:** Maxar Open Data imagery is CC-BY-NC-4.0. This package does not redistribute it.

## Development

```bash
pytest
python -m build          # builds sdist + wheel into dist/
twine check dist/*
```
