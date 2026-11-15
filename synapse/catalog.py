"""Geofabrik regional extract catalogue, cached on disk so it is NOT re-downloaded on every visit."""
import json, re, time, urllib.request
from pathlib import Path

INDEX_URL = "https://download.geofabrik.de/index-v1.json"
MAX_AGE_S = 7 * 24 * 3600          # refresh at most once a week


def _walk(v, coords):
    if isinstance(v, (list, tuple)):
        if len(v) >= 2 and isinstance(v[0], (int, float)) and isinstance(v[1], (int, float)):
            coords.append((float(v[0]), float(v[1])))
        else:
            for x in v:
                _walk(x, coords)


def build_catalog(index):
    items = []
    for f in index.get("features", []):
        prop = f.get("properties") or {}; urls = prop.get("urls") or {}
        pbf = urls.get("pbf")
        if not pbf:
            continue
        if pbf.startswith("/"):
            pbf = "https://download.geofabrik.de" + pbf
        if not pbf.startswith("https://download.geofabrik.de/"):
            continue
        coords = []; _walk((f.get("geometry") or {}).get("coordinates", []), coords)
        if not coords:
            continue
        bbox = [min(x for x, y in coords), min(y for x, y in coords), max(x for x, y in coords), max(y for x, y in coords)]
        path_ = re.sub(r"^https://download\.geofabrik\.de/|-latest\.osm\.pbf$", "", pbf)
        rid = re.sub(r"[^a-z0-9_-]+", "-", path_.lower()).strip("-")[:110]
        if not rid:
            continue
        parent_id = re.sub(r"[^a-z0-9_-]+", "-", path_.rsplit("/", 1)[0].lower()).strip("-") if "/" in path_ else ""
        parent = prop.get("parent")
        if isinstance(parent, dict):
            parent = parent.get("name") or parent.get("id")
        raw = prop.get("iso3166-1:alpha2") or prop.get("country") or ""
        if isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else ""
        cc = re.sub(r"[^A-Za-z]", "", str(raw)).upper()[:2]
        items.append({"id": rid, "name": str(prop.get("name") or "Unnamed region"), "pbf": pbf, "bbox": bbox, "parent": parent,
                      "parent_id": parent_id, "country": cc, "level": "subregion" if parent else "country_or_region"})
    byid = {x["id"]: x for x in items}
    for x in items:                      # inherit the country code from the nearest ancestor that has one
        cur = x; hops = 0
        while not x["country"] and cur.get("parent_id") in byid and hops < 6:
            cur = byid[cur["parent_id"]]; x["country"] = cur["country"]; hops += 1
    parents = {x["parent_id"] for x in items}
    for x in items:
        x["leaf"] = x["id"] not in parents
    unique = {x["id"]: x for x in items}
    items = sorted(unique.values(), key=lambda x: (x["country"], str(x.get("parent") or ""), x["name"].lower()))
    return {"source": "Geofabrik global OpenStreetMap extracts", "regions": items, "count": len(items), "license": "OpenStreetMap ODbL",
            "scope_note": "Worldwide catalogue of extracts published by Geofabrik; availability and subdivision depth vary by country."}


def get_catalog(data_dir, max_age_s=MAX_AGE_S, force=False, fetch=None):
    """Return the catalogue, downloading it only when there is no cache or the cache is older than max_age_s."""
    cache = Path(data_dir) / "global_region_catalog.json"
    if cache.exists() and not force:
        try:
            if time.time() - cache.stat().st_mtime < max_age_s:
                c = json.loads(cache.read_text())
                if c.get("regions"):
                    c["cached"] = True; c["cache_fresh"] = True
                    return c
        except Exception:  # noqa: BLE001
            pass
    try:
        if fetch is None:
            req = urllib.request.Request(INDEX_URL, headers={"User-Agent": "SYNAPSE-EARTH/1.1 (global regional map catalogue)"})
            with urllib.request.urlopen(req, timeout=25) as r:
                index = json.loads(r.read(60_000_000))
        else:
            index = fetch()
        payload = build_catalog(index)
        cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache.with_suffix(".tmp"); tmp.write_text(json.dumps(payload, ensure_ascii=False)); tmp.replace(cache)
        return payload
    except Exception as e:  # noqa: BLE001
        try:
            c = json.loads(cache.read_text()); c["cached"] = True
            c["scope_note"] = "Showing the last successfully downloaded Geofabrik catalogue. New regions require an internet connection."
            return c
        except Exception:  # noqa: BLE001
            raise RuntimeError("Global regional map catalogue unavailable: %s" % e)
