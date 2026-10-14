"""Command-line entry point: `cloud-detect`."""

import argparse

from example_cloud_detector import __version__
from example_cloud_detector.stac import download_assets, search_items


def main(argv=None):
    parser = argparse.ArgumentParser(prog="cloud-detect", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="Download items from a STAC collection")
    fetch.add_argument("catalog_url")
    fetch.add_argument("collection")
    fetch.add_argument("--bbox", type=float, nargs=4, metavar=("W", "S", "E", "N"))
    fetch.add_argument("--datetime")
    fetch.add_argument("--max-items", type=int, default=5)
    fetch.add_argument("--assets", nargs="*", help="Asset keys to download (default: all)")
    fetch.add_argument("--out", default="data")

    args = parser.parse_args(argv)
    if args.command == "fetch":
        items = search_items(
            args.catalog_url, args.collection, args.bbox, args.datetime, args.max_items
        )
        for item in items:
            paths = download_assets(item, args.out, args.assets)
            print(f"{item.id}: {len(paths)} assets")


if __name__ == "__main__":
    main()
