"""Download regional maps ONCE and remember what was done, so they are never re-downloaded on visits or restarts.

Scope syntax (CLI flag / SYNAPSE_PREFETCH env var):
    all                  every leaf extract in the Geofabrik catalogue (tens of GB - use with a size cap and a big disk)
    IN,US,GB             every leaf extract of those ISO country codes
    id:asia-india-western-zone,id:europe-monaco    specific catalogue ids
"""
import json, os, time
from pathlib import Path
from .catalog import get_catalog

STATE = "prefetch_state.json"
RETRY_AFTER_S = 24 * 3600


def read_state(data_dir):
    try:
        return json.loads((Path(data_dir) / STATE).read_text())
    except Exception:  # noqa: BLE001
        return {"items": {}}


def record(data_dir, it):
    st = read_state(data_dir)
    st.setdefault("items", {})[it["region_id"]] = {"status": it["status"], "message": it.get("message", ""), "at": time.time(), "name": it["name"]}
    p = Path(data_dir) / STATE
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(st)); tmp.replace(p)


def select(catalog, scope, data_dir, max_mb, first=None):
    scope = (scope or "").strip()
    regions = catalog.get("regions", [])
    parents = {x.get("parent_id") for x in regions}
    leaves = [x for x in regions if x["id"] not in parents]
    if scope.lower() == "all":
        chosen = leaves
    else:
        toks = [t.strip() for t in scope.split(",") if t.strip()]
        ids = {t[3:].lower() for t in toks if t.lower().startswith("id:")}
        ccs = {t.upper() for t in toks if not t.lower().startswith("id:")}
        chosen = [x for x in regions if x["id"] in ids] + [x for x in leaves if (x.get("country") or "").upper() in ccs and x["id"] not in ids]
    first = [c.strip().upper() for c in (os.environ.get("SYNAPSE_PREFETCH_FIRST", "IN") if first is None else first).split(",") if c.strip()]
    chosen = sorted(chosen, key=lambda x: (first.index((x.get("country") or "").upper()) if (x.get("country") or "").upper() in first else len(first)))
    st = read_state(data_dir).get("items", {})
    out = []
    for x in chosen:
        if (Path(data_dir) / (x["id"] + ".json")).exists():
            continue                                   # already on disk: never download again
        s = st.get(x["id"])
        if s and s["status"] in ("failed", "skipped") and time.time() - s["at"] < RETRY_AFTER_S:
            continue                                   # failed / too big recently: don't hammer it on every restart
        out.append({"pbf": x["pbf"], "name": x["name"], "region_id": x["id"], "country_code": (x.get("country") or "XX"), "bbox": x["bbox"]})
    return out


def plan(data_dir, scope, max_mb, fetch=None):
    return select(get_catalog(data_dir, fetch=fetch), scope, data_dir, max_mb)
