"""Find items in a STAC catalog (static or API) and download their assets."""

from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import urlopen, urlretrieve

import pystac

# STAC Browser wraps external catalogs as https://<browser-host>/external/<host>/<path>
_BROWSER_MARKER = "/external/"


def normalize_url(url):
    """Turn a STAC Browser link into the underlying catalog URL; other URLs pass through."""
    if url.startswith(("http://", "https://")) and _BROWSER_MARKER in url:
        rest = url.split(_BROWSER_MARKER, 1)[1]
        return rest if rest.startswith(("http://", "https://")) else "https://" + rest
    return url


def _read_json(href):
    if href.startswith(("http://", "https://")):
        with urlopen(href, timeout=60) as resp:
            return json.load(resp)
    return json.loads(Path(href).read_text())


def _links(obj, rel, base):
    return [urljoin(base, link["href"]) for link in obj.get("links", []) if link["rel"] == rel]


def _matches(item, platforms, min_cloud, max_cloud, required_assets):
    props = item.properties
    if platforms and props.get("platform") not in platforms:
        return False
    cloud = props.get("tile:clouds_percent", props.get("eo:cloud_cover"))
    if (min_cloud is not None or max_cloud is not None) and cloud is None:
        return False
    if min_cloud is not None and cloud < min_cloud:
        return False
    if max_cloud is not None and cloud > max_cloud:
        return False
    return all(key in item.assets for key in required_assets or ())


def find_items(
    catalog_url,
    collection=None,
    *,
    platforms=None,
    min_cloud=None,
    max_cloud=None,
    required_assets=None,
    max_items=10,
    workers=16,
):
    """Return up to `max_items` pystac Items matching the filters.

    Works on static catalogs by walking child/item links breadth-first, fetching
    item JSON in parallel. `collection` is the id of a direct child of the root
    (e.g. a Maxar Open Data event); omit it to walk the whole catalog. Cloud
    filters use `tile:clouds_percent`, falling back to `eo:cloud_cover`.
    """
    root_href = normalize_url(catalog_url)
    root = _read_json(root_href)
    if collection is not None:
        children = [(href, _read_json(href)) for href in _links(root, "child", root_href)]
        matches = [(href, c) for href, c in children if c.get("id") == collection]
        if not matches:
            raise ValueError(f"No child '{collection}' in {root_href}")
        root_href, root = matches[0]

    found = []
    queue = [(root_href, root)]
    with ThreadPoolExecutor(workers) as pool:
        while queue and len(found) < max_items:
            href, node = queue.pop(0)
            item_hrefs = _links(node, "item", href)
            for item_href, data in zip(item_hrefs, pool.map(_read_json, item_hrefs)):
                item = pystac.Item.from_dict(data, href=item_href)
                if _matches(item, platforms, min_cloud, max_cloud, required_assets):
                    found.append(item)
                    if len(found) >= max_items:
                        break
            child_hrefs = _links(node, "child", href)
            queue.extend(zip(child_hrefs, pool.map(_read_json, child_hrefs)))
    return found


def download_assets(item, out_dir, asset_keys=None):
    """Download the selected assets of `item` into `out_dir/<item id>/`. Returns {key: path}."""
    item_dir = Path(out_dir) / item.id.replace("/", "_")
    item_dir.mkdir(parents=True, exist_ok=True)
    (item_dir / "item.json").write_text(json.dumps(item.to_dict(), indent=1))
    paths = {}
    for key, asset in item.assets.items():
        if asset_keys is not None and key not in asset_keys:
            continue
        href = asset.get_absolute_href()
        dest = item_dir / (Path(href.split("?")[0]).name or key)
        if not dest.exists():
            tmp = dest.with_suffix(dest.suffix + ".part")
            if href.startswith(("http://", "https://")):
                urlretrieve(href, tmp)
            else:
                shutil.copyfile(href, tmp)
            tmp.rename(dest)
        paths[key] = dest
    return paths
