# Data notes: Maxar Open Data STAC catalog

Source: <https://maxar-opendata.s3.amazonaws.com/events/catalog.json> (static STAC, browsable at
<https://browser.moregeo.it/external/maxar-opendata.s3.amazonaws.com/events/catalog.json>).

Purpose of this package: produce cloud masks over this imagery that students can use as a
**comparison baseline** for their own models. We assume no reference masks exist and generate our own.

Survey of 2026-10-14: all 55 events, 1,109 acquisitions,
~40,000 items; 2 items sampled per acquisition (2,199) plus COG headers for one item per sensor.

## Layout

```
catalog.json
└── <event>/collection.json                       55 events
    └── ard/acquisition_collections/<catalog_id>_collection.json   one per satellite pass
        └── ard/<utm_zone>/<quadkey>/<date>/<catalog_id>.json      ~5 km UTM tile (item)
```

All imagery is optical (Maxar ARD); no SAR or other modalities. Every asset in an item covers the
same tile footprint at different resolutions. Licence: CC-BY-NC-4.0 for all events.

## Sensors

| Sensor | Share | `ms_analytic` bands | MS res | Pan res |
|--------|------:|---------------------|--------|---------|
| WV02   | 40%   | 8: coastal, blue, green, yellow, red, rededge, nir08, nir09 | 1.8–3.5 m | 0.46–0.88 m |
| WV03   | 35%   | 8 (same as WV02)    | 1.2–2.3 m | 0.31–0.57 m |
| GE01   | 17%   | 4: blue, green, red, nir08 | 1.6–2.9 m | 0.41–0.72 m |
| WV01   | 7%    | none: pan only      | –         | 0.50–1.1 m  |
| WV04   | <1%   | 4: blue, green, red, nir08 | 1.25–1.5 m | 0.31–0.38 m |

- **Common band set across multispectral sensors: blue, green, red, nir08.** Select bands by
  `eo:bands[].common_name`, never by index (red is band 5 on WV02/03, band 3 on GE01/WV04).
- GSD varies with off-nadir angle (1–49°), so resolution varies within a sensor too.
- WV01 has no multispectral asset; it needs a pan-only detector or should be skipped.

## Assets and file formats

| Asset | Format | Pixels |
|-------|--------|--------|
| `ms_analytic`  | COG, deflate, 512 px blocks, overviews | uint16, 4 or 8 bands |
| `pan_analytic` | COG, deflate | uint16, 1 band |
| `visual`       | COG, JPEG (YCbCr) | uint8, 17408², 0.31 m; RGB, but **1 band on WV01** |
| `data-mask`    | GeoPackage (one valid-data polygon) | – |

All COGs read efficiently over HTTP (`/vsicurl/` range requests), so full downloads are optional.
`visual` is an upsampled, lossy display product; use `ms_analytic` for detection.

Some items also carry Maxar cloud/shadow/water/etc. masks (~10%, in a handful of events).
**We ignore these**: the package assumes no masks are available.

## Gotchas

1. **No nodata value is set on any raster; 0 is fill.** Many tiles are mostly empty (edge tiles;
   50–99% zeros seen). Valid pixels = `data-mask` polygon if present, else any band non-zero.
2. **`data-mask` is missing on some items** (e.g. many in HurricaneHelene-Oct24).
3. **No scale/offset metadata.** `ms_analytic` values look like reflectance × 10,000 (clear land
   ~100–4,000; clouds up to ~8,000), but this is undocumented, so keep thresholds tunable.
   Saturated pixels (65535) occur.
4. **Asset sets vary**: one WV02 item has only `visual` (no ms/pan). Filter on required assets.
5. `tile:clouds_percent` exists on every item (72% are 0%, 7% ≥ 50%) and is handy for picking
   cloudy tiles. One tile reports 101% with zero data area: clamp it, and skip empty tiles.
6. **Many UTM zones** (`proj:epsg` per item). Write masks in each tile's own CRS and grid.
7. Minor metadata inconsistencies: five 2021–22 events lack the `raster` extension and `grid:code`;
   six WV01 items have an undocumented `hd: true`; WV04 item ids are UUIDs (`…-inv`).
8. **Some listed assets do not exist.** In `volcano-indonesia21`, items list `ms_analytic`, `pan_analytic`
   and the masks, but only `visual` is hosted (the rest return HTTP 404). Expect occasional broken items.
9. The same location appears in several acquisitions (shared quadkey). If students split
   train/test, split by location or acquisition rather than by tile to avoid leakage.

Image dates and event context are not relevant to this package.

## Implications for the detectors

- Input: `ms_analytic`, bands selected by common name; baseline = blue/green/red/nir08, extra
  WV02/03 bands optional.
- Valid-data mask from `data-mask` if present, else non-zero pixels; output 0 outside it.
- Output: uint8 COG in the source tile's CRS and grid. Suggested classes: 0 = nodata, 1 = clear,
  2 = cloud, 3 = cloud shadow.
