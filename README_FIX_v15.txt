SYNAPSE EARTH v15 — Detect-location fix, real world map, safer-zone routing, new UI

ROOT CAUSE of the dead "Detect my location" button (and several others)
  v14's page script contained  $('route').onclick = ...  but the Route button no longer existed.
  That line threw "Cannot set properties of null", which aborted the whole script: the GPS, map,
  catalogue and route handlers after it were never attached. v15 binds every control defensively,
  so one failing feature can no longer disable the rest, and unexpected errors show as on-screen toasts.

WHAT'S NEW
  * Real interactive world map (Leaflet, bundled in ui/vendor — no CDN). Pan/zoom to street level.
    Layers: Streets (OSM), Esri streets, Satellite, Dark gray (keyless online tiles) + offline country boundaries that always work.
  * Detect my location: precise GPS (12 s) -> network location (15 s) -> automatic approximate IP fallback.
    Clear messages for permission-denied / Brave / macOS. Also: "Pick on map", type a place name or "lat, lon".
  * Safer zones: after your location is set, SYNAPSE finds mapped shelters/assembly points, medical
    facilities and community buildings (installed offline data first, OpenStreetMap/Overpass when online),
    ranks them for the chosen hazard (Flood/Cyclone prefer higher ground via Open-Meteo elevation),
    and draws the route: installed offline road graph -> online OSM road routing -> straight-line bearing.
    Walking / driving modes, turn list, links to OSM/Google Maps, emergency number by country.
  * Fixes: bus stops tagged shelter=yes are no longer treated as shelters; route lat/lon swap removed;
    AI-agent assessment works without a regional package; readable agent cards; literal "\n" bug.
  * New responsive UI (desktop, tablet, phone).

RUN
  ./START_SYNapse_EARTH.command   (or: python3 -m synapse.server --data ./data) then open http://127.0.0.1:8080

HONEST LIMITS
  * Online features (map tiles, shelter search, road routing, elevation, IP location, place search) need internet;
    without it the app uses installed packages and the offline country map and says so.
  * Shelters are OpenStreetMap records. Opening status, capacity, closures and hazard exposure are NOT verified.
    Routes are candidates only — follow local emergency authorities.
  * The online calls could not be exercised against the live services in the build sandbox; they are covered by
    mocked unit tests (tests/test_online.py). Please try them once on a connected machine.

BULK REGION INSTALL (new)
  Section 4 -> "Bulk install": smallest extract around you / all extracts in your country / whole world.
  Runs as a server-side queue: one extract at a time, per-extract size cap (default 300 MB), free-disk check,
  skips already-installed, continues past failures, cancellable, progress bar. Needs internet + the 'osmium' package.
  Whole-world means tens of GB of downloads/disk and hours of processing - a confirmation is shown first.
  Large installs are now fast to use: package manifests are cached, and only regions covering your position are loaded.
