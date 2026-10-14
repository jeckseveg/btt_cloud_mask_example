"""Search a STAC catalog and download item assets."""

from __future__ import annotations

from pathlib import Path
from urllib.request import urlretrieve

from pystac_client import Client


def search_items(catalog_url, collection, bbox=None, datetime=None, max_items=10, **kwargs):
    """Return a list of pystac Items from `collection` in the catalog at `catalog_url`."""
    client = Client.open(catalog_url)
    search = client.search(
        collections=[collection], bbox=bbox, datetime=datetime, max_items=max_items, **kwargs
    )
    return list(search.items())


def download_assets(item, out_dir, asset_keys=None):
    """Download the selected assets of `item` into `out_dir/<item.id>/`. Returns {key: path}."""
    item_dir = Path(out_dir) / item.id
    item_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for key, asset in item.assets.items():
        if asset_keys is not None and key not in asset_keys:
            continue
        name = Path(asset.href.split("?")[0]).name or key
        dest = item_dir / name
        if not dest.exists():
            urlretrieve(asset.href, dest)
        paths[key] = dest
    return paths
