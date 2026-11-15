#!/usr/bin/env python3
"""Download regional maps ONCE (build time or first boot) so visitors never trigger downloads.

Examples
  python scripts/prefetch_regions.py --scope IN --max-mb 300          # all India extracts up to 300 MB each
  python scripts/prefetch_regions.py --scope IN,US,GB --max-mb 250
  python scripts/prefetch_regions.py --scope id:asia-india-western-zone
  python scripts/prefetch_regions.py --scope all --max-mb 200 --time-limit 3000   # whole world: needs tens of GB + hours
  python scripts/prefetch_regions.py --scope IN --dry-run              # just list what would be downloaded

Already-installed regions are skipped, failures are remembered for 24 h (data/prefetch_state.json),
and --time-limit stops cleanly so a hosting build never times out half way through a file.
Requires:  pip install osmium
"""
import argparse, os, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from synapse import prefetch
from synapse.installer import BatchInstaller


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scope", default=os.environ.get("SYNAPSE_PREFETCH", ""), help="all | IN,US | id:<catalogue-id>[,..]")
    ap.add_argument("--max-mb", type=int, default=int(os.environ.get("SYNAPSE_PREFETCH_MAX_MB", "300")), help="skip extracts larger than this (default 300)")
    ap.add_argument("--data", default=os.environ.get("SYNAPSE_DATA", "./data"))
    ap.add_argument("--time-limit", type=int, default=0, help="stop after this many seconds (0 = no limit)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.scope:
        ap.error("--scope is required (for example --scope IN)")
    Path(a.data).mkdir(parents=True, exist_ok=True)
    try:
        items = prefetch.plan(a.data, a.scope, a.max_mb)
    except Exception as e:  # noqa: BLE001
        print("Could not read the regional catalogue (needs internet once):", e); return 0
    print("%d extract(s) to download for scope %r (max %d MB each)" % (len(items), a.scope, a.max_mb))
    if a.dry_run or not items:
        for it in items[:200]:
            print("  -", it["region_id"], "|", it["name"])
        return 0
    try:
        import osmium  # noqa: F401
    except ImportError:
        print("The 'osmium' package is missing: pip install osmium"); return 1
    b = BatchInstaller(a.data, on_item=lambda it: prefetch.record(a.data, it))
    b.start(items, a.max_mb, True)
    t0 = time.time(); seen = {}
    while True:
        st = b.status()
        for it in st["items"]:
            key = (it["region_id"], it["status"])
            if it["status"] in ("installed", "failed", "skipped", "cancelled") and key not in seen:
                seen[key] = 1
                print("  [%s] %s %s" % (it["status"].upper(), it["name"], ("- " + it["message"]) if it["message"] else ""), flush=True)
        if not st["running"]:
            break
        if a.time_limit and time.time() - t0 > a.time_limit:
            print("Time limit reached; stopping cleanly. Run again to continue (finished maps are kept).", flush=True); b.cancel()
            a.time_limit = 0
        time.sleep(2)
    n = sum(1 for i in b.status()["items"] if i["status"] == "installed")
    print("Done: %d installed this run in %.0f s." % (n, time.time() - t0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
