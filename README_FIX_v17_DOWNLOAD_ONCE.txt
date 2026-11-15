SYNAPSE EARTH v17 - regional maps are downloaded ONCE, not on every visit

What was wrong
- Each visit could trigger region installs (auto-download), re-fetch of the Geofabrik catalogue,
  and loading whole region packages into the browser.

What changed
1. Visitors can no longer trigger downloads on a public host (install endpoints return 403;
   UI hides the install tools). Localhost keeps full install ability.  Override: SYNAPSE_ALLOW_INSTALL=1/0.
2. Catalogue is cached on disk for 7 days (data/global_region_catalog.json); stale copy used if offline.
3. scripts/prefetch_regions.py downloads regions once and skips anything installed:
     python scripts/prefetch_regions.py --scope all --max-mb 300      (every leaf region under 300 MB)
     python scripts/prefetch_regions.py --scope IN,PK --dry-run
   Failures are remembered 24h in data/prefetch_state.json so they are not retried every start.
4. Server option --prefetch / SYNAPSE_PREFETCH=<scope> does the same in the background once at startup.
5. Browser loads small endpoints (/api/region-info, /api/region-roads?bbox=) instead of whole packages;
   /api/world is ETag/max-age cached; auto-download is tried at most once per region per 24h.
6. render.yaml runs the prefetch at BUILD time (see its comments).

Honest limits
- Render free disk is wiped on every restart/deploy; build-time prefetch repeats per deploy (not per visit).
  For permanent storage attach a persistent disk (paid) and set SYNAPSE_DATA.
- The whole world at road detail is tens of GB: too big for git or Render free. Use --max-mb and country scopes.
- Real Geofabrik downloads were not testable in the build sandbox; unit tests and browser tests use mocks (31 tests pass).

v18 additions
- No safer zone within 10 km: online search widens to ~80 km, installed offline data to 150 km; the UI says how far the nearest one is.
- On arrival, "Find next safer zone from here" searches again from that point (visited zones are skipped).
- Service worker (ui/sw.js): app shell, vendor files, world map, region data and viewed map tiles keep working with no internet.
- Online search is skipped (with a clear note) when the browser is offline.
