"""Command-line entry point: `cloud-detect`."""

import argparse

from example_cloud_detector import __version__
from example_cloud_detector.stac import download_assets, find_items

DETECTOR_NAMES = ["omnicloudmask", "ukis", "cloudsen12"]


def _res(value):
    return None if value == "native" else value if value == "default" else float(value)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cloud-detect", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="Download items from a STAC catalog")
    fetch.add_argument("catalog_url", help="Catalog URL (STAC Browser links are accepted)")
    fetch.add_argument("collection", nargs="?", help="Child collection id, e.g. an event")
    fetch.add_argument("--platform", nargs="*", help="e.g. WV02 WV03 GE01")
    fetch.add_argument("--min-cloud", type=float)
    fetch.add_argument("--max-cloud", type=float)
    fetch.add_argument("--max-items", type=int, default=5)
    fetch.add_argument("--assets", nargs="*", help="Asset keys to download (default: all)")
    fetch.add_argument("--out", default="data")
    fetch.add_argument("--dry-run", action="store_true", help="List matches without downloading")

    run = sub.add_parser("run", help="Write cloud masks for STAC items")
    run.add_argument("detector", choices=DETECTOR_NAMES)
    run.add_argument("items", nargs="+", help="item.json files, directories containing one, or item URLs")
    run.add_argument("--res", type=_res, default="default",
                     help="Model resolution in metres, 'native' for source resolution, or 'default'")
    run.add_argument("--out", default="masks")
    run.add_argument("--model-grid", action="store_true",
                     help="Write masks at the model resolution instead of the source grid")
    run.add_argument("--thin-is-clear", action="store_true", help="Label thin cloud as clear")
    run.add_argument("--min-cloud-reflectance", type=float, default=0.08,
                     help="Cloud darker than this mean visible reflectance becomes clear (0 disables)")

    args = parser.parse_args(argv)
    if args.command == "run":
        from example_cloud_detector.detectors import get_detector
        from example_cloud_detector.pipeline import detect_item

        kwargs = dict(res=args.res, min_cloud_reflectance=args.min_cloud_reflectance)
        if args.detector != "ukis":
            kwargs["thin_is_cloud"] = not args.thin_is_clear
        detector = get_detector(args.detector, **kwargs)
        for item in args.items:
            try:
                print(detect_item(item, detector, args.out, source_grid=not args.model_grid))
            except ValueError as err:
                print(f"skipped {item}: {err}")
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
