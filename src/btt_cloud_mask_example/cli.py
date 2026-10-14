"""Command-line entry point: `cloud-detect`."""

import argparse
import sys
from pathlib import Path

from btt_cloud_mask_example import __version__
from btt_cloud_mask_example.stac import download_assets, find_items

DETECTOR_NAMES = ["omnicloudmask", "ukis", "cloudsen12"]


def _res(value):
    return None if value == "native" else value if value == "default" else float(value)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cloud-detect", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    find = sub.add_parser("find", help="List image URLs from a Maxar Open Data event")
    find.add_argument("event", help="Event name, e.g. Hurricane-Ian-9-26-2022")
    find.add_argument("--n", type=int, default=5, help="How many images (default 5)")
    find.add_argument("--min-cloud", type=float, help="Minimum cloud cover, 0-100")
    find.add_argument("--max-cloud", type=float, help="Maximum cloud cover, 0-100")

    mask = sub.add_parser("mask", help="Make a cloud mask GeoTIFF for each image URL")
    mask.add_argument("images", nargs="+", help="Image URLs (from `cloud-detect find`) or downloaded folders")
    mask.add_argument("--model", default="omnicloudmask", help="omnicloudmask (default), ukis or cloudsen12")
    mask.add_argument("--resolution", type=float, help="Pixel size in metres (default: the image's own)")
    mask.add_argument("--out", default="masks", help="Folder for the GeoTIFFs (default: masks)")

    fetch = sub.add_parser("fetch", help="Advanced: download items from any static STAC catalog")
    fetch.add_argument("catalog_url", help="Catalog URL (STAC Browser links are accepted)")
    fetch.add_argument("collection", nargs="?", help="Child collection id, e.g. an event")
    fetch.add_argument("--platform", nargs="*", help="e.g. WV02 WV03 GE01")
    fetch.add_argument("--min-cloud", type=float)
    fetch.add_argument("--max-cloud", type=float)
    fetch.add_argument("--max-items", type=int, default=5)
    fetch.add_argument("--assets", nargs="*", help="Asset keys to download (default: all)")
    fetch.add_argument("--out", default="data")
    fetch.add_argument("--dry-run", action="store_true", help="List matches without downloading")

    run = sub.add_parser("run", help="Advanced: write cloud masks on the source grid with detector options")
    run.add_argument("detector", choices=DETECTOR_NAMES)
    run.add_argument("items", nargs="+", help="item.json files, directories containing one, or item URLs")
    run.add_argument("--res", type=_res, default="default",
                     help="Model resolution in metres or 'native' (default: native, the source resolution)")
    run.add_argument("--out", default="masks")
    run.add_argument("--model-grid", action="store_true",
                     help="Write masks at the model resolution instead of the source grid")
    run.add_argument("--thin-is-clear", action="store_true", help="Label thin cloud as clear")
    run.add_argument("--min-cloud-reflectance", type=float, default=0.08,
                     help="Cloud darker than this mean visible reflectance becomes clear (0 disables)")

    args = parser.parse_args(argv)
    if args.command in ("find", "mask"):
        from btt_cloud_mask_example.api import MODEL_ALIASES, CloudMaskError, _to_item, create_mask, find_images

        try:
            if args.command == "find":
                print("\n".join(find_images(args.event, args.n, args.min_cloud, args.max_cloud)))
                return
            failed = 0
            model = MODEL_ALIASES.get(args.model.lower(), args.model.lower())
            for image in args.images:
                try:
                    item = _to_item(image)
                    path = Path(args.out) / f"{item.id.replace('/', '_')}_{model}.tif"
                    mask = create_mask(item, model, args.resolution, save_to=path)
                    print(f"{path}  cloud {100 * mask.mean():.1f}%")
                except CloudMaskError as err:
                    failed += 1
                    print(f"skipped {image}: {err}", file=sys.stderr)
            if failed:
                sys.exit(f"{failed} of {len(args.images)} images skipped")
        except CloudMaskError as err:
            sys.exit(str(err))
    if args.command == "run":
        from btt_cloud_mask_example.detectors import get_detector
        from btt_cloud_mask_example.pipeline import detect_item

        kwargs = dict(res=args.res, min_cloud_reflectance=args.min_cloud_reflectance)
        if args.detector != "ukis":
            kwargs["thin_is_cloud"] = not args.thin_is_clear
        detector = get_detector(args.detector, **kwargs)
        failed = 0
        for item in args.items:
            try:
                print(detect_item(item, detector, args.out, source_grid=not args.model_grid))
            except Exception as err:  # keep going; one bad item shouldn't stop a batch
                failed += 1
                print(f"failed {item}: {err}", file=sys.stderr)
        if failed:
            sys.exit(f"{failed} of {len(args.items)} items failed")
    if args.command == "fetch":
        items = find_items(
            args.catalog_url,
            args.collection,
            platforms=args.platform,
            min_cloud=args.min_cloud,
            max_cloud=args.max_cloud,
            required_assets=args.assets,
            max_items=args.max_items,
        )
        for item in items:
            p = item.properties
            line = f"{item.id}  {p.get('platform')}  {p.get('datetime')}  cloud={p.get('tile:clouds_percent')}%"
            if not args.dry_run:
                paths = download_assets(item, args.out, args.assets)
                line += f"  -> {len(paths)} assets"
            print(line)


if __name__ == "__main__":
    main()
