"""Find items in a STAC catalog (static or API) and download their assets."""

from __future__ import annotations

import json
import shutil
import ssl
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


# One TLS context for all requests: building a new one per request costs ~0.5 s of CPU.
_SSL_CONTEXT = ssl.create_default_context()


def _read_json(href):
    if href.startswith(("http://", "https://")):
        with urlopen(href, timeout=60, context=_SSL_CONTEXT) as resp:
            return json.load(resp)
    return json.loads(Path(href).read_text())


def _links(obj, rel, base):
    return [urljoin(base, link["href"]) for link in obj.get("links", []) if link["rel"] == rel]


def data_coverage(item):
    """Fraction of a Maxar tile that holds image data, from `tile:data_area` (km2).

    The full tile size comes from an asset's `proj:shape` and pixel size; the item's
    `proj:bbox` can't be used because it only bounds the data, not the whole tile.
    """
    area = item.properties.get("tile:data_area")
    if area is None:
        return None
    for asset in item.assets.values():
        shape, transform = asset.extra_fields.get("proj:shape"), asset.extra_fields.get("proj:transform")
        if shape and transform:
            tile_km2 = shape[0] * abs(transform[4]) * shape[1] * abs(transform[0]) / 1e6
            return min(1.0, area / tile_km2) if tile_km2 else None
    return None


def _matches(item, platforms, min_cloud, max_cloud, required_assets, min_coverage=None):
    props = item.properties
    coverage = data_coverage(item) if min_coverage is not None else None
    if coverage is not None and coverage < min_coverage:  # unknown coverage is not filtered
        return False
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
    min_coverage=None,
    max_items=10,
    workers=16,
):
    """Return up to `max_items` pystac Items matching the filters.

    Works on static catalogs by walking child/item links depth-first (so the first matches
    arrive quickly), fetching item JSON in parallel. `collection` is the id of a direct child
    of the root (e.g. a Maxar Open Data event); omit it to walk the whole catalog. Cloud
    filters use `tile:clouds_percent`, falling back to `eo:cloud_cover`. `min_coverage`
    (0-1) skips mostly-empty edge tiles, using Maxar's `tile:data_area`.
    """
    root_href = normalize_url(catalog_url)
    root = _read_json(root_href)
    with ThreadPoolExecutor(workers) as pool:
        if collection is not None:
            root_href, root = _find_child(root, root_href, collection, pool)

        found = []
        stack = [(root_href, root)]
        while stack and len(found) < max_items:
            href, node = stack.pop()
            item_hrefs = _links(node, "item", href)
            for item_href, data in zip(item_hrefs, pool.map(_read_json, item_hrefs)):
                item = pystac.Item.from_dict(data, href=item_href)
                if _matches(item, platforms, min_cloud, max_cloud, required_assets, min_coverage):
                    found.append(item)
                    if len(found) >= max_items:
                        break
            child_hrefs = _links(node, "child", href)
            stack.extend(reversed(list(zip(child_hrefs, pool.map(_read_json, child_hrefs)))))
    return found


def _find_child(root, root_href, child_id, pool):
    """Return (href, json) of the root's child with id `child_id`, guessing from the path first."""
    hrefs = _links(root, "child", root_href)
    likely = [h for h in hrefs if f"/{child_id}/" in h]
    for candidates in (likely, hrefs):
        for href, child in zip(candidates, pool.map(_read_json, candidates)):
            if child.get("id") == child_id:
                return href, child
    raise ValueError(f"No child '{child_id}' in {root_href}")


def download_assets(item, out_dir, asset_keys=None):
    """Download the selected assets of `item` into `out_dir/<item id>/`. Returns {key: path}.

    Also writes `item.json` alongside, with downloaded assets pointing at the local files and the
    rest at their absolute remote URLs, so `pystac.Item.from_file` on it works offline where possible.
    """
    item_dir = Path(out_dir) / item.id.replace("/", "_")
    item_dir.mkdir(parents=True, exist_ok=True)
    local = item.clone()
    paths = {}
    for key, asset in item.assets.items():
        href = asset.get_absolute_href()
        if asset_keys is not None and key not in asset_keys:
            local.assets[key].href = href
            continue
        dest = item_dir / (Path(href.split("?")[0]).name or key)
        if not dest.exists():
            tmp = dest.with_suffix(dest.suffix + ".part")
            if href.startswith(("http://", "https://")):
                urlretrieve(href, tmp)
            else:
                shutil.copyfile(href, tmp)
            tmp.rename(dest)
        local.assets[key].href = f"./{dest.name}"
        paths[key] = dest
    local.clear_links("self")
    (item_dir / "item.json").write_text(json.dumps(local.to_dict(include_self_link=False), indent=1))
    return paths
