# Detectors

All detectors return the same classes: **0 nodata, 1 clear, 2 cloud, 3 cloud shadow**.
By default they run at the **source resolution** of the item's `ms_analytic` asset (1.2–3.5 m)
and write the mask on that grid. Use `--res 10` (CLI) or `res=10` (Python) to run coarser.

| Detector | Extra | Bands | Trained on | Licence | Pan-only (WV01) |
|----------|-------|-------|-----------|---------|-----------------|
| `omnicloudmask` | `[omnicloudmask]` | red, green, NIR | Sentinel-2, sensor-agnostic normalisation | MIT | yes (experimental: pan as red+green, NIR zeroed) |
| `ukis` | `[ukis]` | blue, green, red, NIR | Sentinel-2 | Apache-2.0 | no |
| `cloudsen12` | `[cloudsen12]` | NIR, red, green, blue | Sentinel-2 L1C (CloudSEN12) | LGPL-3.0 code, CC-BY-NC-4.0 weights | no |

None of these models was trained on Maxar imagery, and no reference masks are assumed, so treat
their output as a **baseline to compare against**, not ground truth.

## Shared post-processing

- **Fill:** pixels that are 0 in every band are nodata (Maxar sets no nodata value).
- **Brightness floor:** cloud pixels whose mean visible reflectance is below 0.08 are relabelled
  clear (`min_cloud_reflectance`). Real cloud measured 0.44–0.67; open water 0.02–0.04.
  This removes a failure where a featureless dark-water tile was labelled 100% cloud.
- **Thin cloud:** OmniCloudMask and CloudSEN12 separate thick and thin cloud; both count as cloud
  by default (`--thin-is-clear` to drop thin). The thick/thin split is the least stable part of
  their output and shifts with resolution; the merged cloud class is stable.

## Comparison on sample tiles (2026-10-14)

Cloud % of valid pixels, with Maxar's per-tile `tile:clouds_percent` for reference. Brightness
floor off. IoU columns compare cloud masks after resampling to 10 m.

| Tile | Maxar | OCM 10 m / native | ukis 10 m / native | CloudSEN12 10 m / native | Cross-model IoU (native) |
|------|------:|------------------:|-------------------:|-------------------------:|-------------------------:|
| Brazil, WV02 | 56 | 58 / 54 | 53 / 52 | 50 / 46 | 0.85–0.90 |
| Hurricane Helene, WV03 | 47 | 45 / 45 | 44 / 43 | 43 / 42 | 0.80–0.90 |
| Texas, GE01 | 29 | 29 / 28 | 27 / 26 | 24 / 22 | 0.80–0.87 |
| NWT Canada (smoke/haze), WV03 | 59 | 95 / 86 | 22 / 37 | 100 / 100 | 0.37–0.86 |
| Kentucky, GE01 | 66 | 74 / 75 | 67 / 37 | 17 / 15 | 0.20–0.48 |
| Open water, WV02 | 0 | **100** / 0 | 0 / 0 | 0 / 0 | – |
| Desert / urban, WV02–03 | 0 | 0 / 0 | ≤0.5 | 0 / 0 | – |

Stability across resolution (IoU of each model's native mask vs its 10 m mask, cloudy tiles):
OmniCloudMask 0.89–0.95, CloudSEN12 0.63–1.00, ukis 0.35–0.87.

Takeaways:
- On ordinary cloudy tiles the three models agree closely, at any resolution.
- OmniCloudMask is the most resolution-stable; ukis is the least stable on hazy scenes.
- Haze and smoke are where models disagree most. This is a good place for students to look.
- CloudSEN12 missed most of the cloud on one GE01 tile.

## Runtime

CPU (Apple Silicon), per ~5 km tile: 10 m takes 0.3–2 s for every model. Source resolution takes
2–9 s (OmniCloudMask), 6–21 s (ukis) or 5–26 s (CloudSEN12), plus reading the imagery: about
7 s remote or under 1 s for local files.
