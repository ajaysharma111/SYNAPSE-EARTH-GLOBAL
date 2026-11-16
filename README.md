# SYNAPSE EARTH — Global Offline Disaster Response Intelligence

Offline-first disaster decision-support web app. It detects your location, finds the **shortest and safest** shelters, assembly points, community buildings and medical facilities around you, draws the road path on a Google-Maps-style map, and gives live turn-by-turn guidance. Python standard-library server + a single-file UI (`ui/index.html`) with Leaflet vendored locally.

Live demo (Render): https://synapse-earth-global.onrender.com

## Features
- **Location**: GPS, approximate (IP), click on map, or type a place / `lat, lon`. Works worldwide.
- **Safer-zone search (~30 s cap)**: near (8 km) and wide (25 km) OpenStreetMap searches run in parallel; first results appear in seconds. If nothing safe is within 10 km it widens to ~80 km and says how far the nearest one is.
- **Shortest + safest ranking**: cost = real travel time x safety factor (shelter 1.0, hospital 1.2, community building 1.3, hazard-aware: flood/cyclone prefer higher ground, earthquake prefers open assembly points). Cards show **Best balance / Shortest / Safest** badges. Up to 30 zones listed and mapped.
- **Routes**: installed offline road graph first, then online OSRM (foot / car), then a clearly marked straight line.
- **Start navigation**: live remaining distance, ETA, next turn, off-route re-routing, voice, wake lock. On arrival, **Find next safer zone from here** searches again from that point.
- **Map always visible**: online or offline. Missing detail tiles are rebuilt by enlarging the nearest saved lower-zoom tile; about 100 tiles around your location (zoom 5-16) are saved while online; with no tiles at all you still get country shapes, a lat/lon grid, your position, zones, routes and installed roads. The map re-syncs to its container on resize so it never goes blank after zooming.
- **Live freshness check (Tavily + Bifrost)**: map records are snapshots. **Check if still open (live)** on a selected zone searches the last month of news/web pages with Tavily and has a model (through the Bifrost gateway) judge whether the place is open, closed or damaged, citing the sources. Closed/damaged places are dropped from the list. A verdict that cites no real source is discarded; with no model configured it only lists sources. Keys stay on the server. Enable with `TAVILY_API_KEY` (+ `BIFROST_URL` and `BIFROST_MODELS` for the AI judge). Rate-limited and cached. Sibling project: FreshProxy (freshness scoring for any AI answer).
- **Offline**: installed regional maps, offline country boundaries, a service worker (app shell + visited tiles), and places found online are remembered on the device for later offline use.
- **Regional maps install automatically**: the server downloads Geofabrik extracts in the background (India first, then every other country, default 150 MB per-extract cap). Nobody has to press Install; downloads happen once and are skipped if already on disk.
- Guest mode, optional accounts (SQLite, scrypt, CSRF-protected sessions), five deterministic assessment agents.

## Run locally
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/download_world_map.py        # once; offline country boundaries
python3 -m synapse.server --data ./data --host 127.0.0.1 --port 8080
```
Open http://127.0.0.1:8080. macOS: `START_SYNapse_EARTH.command`.

Server options (flag / environment variable):

| Option | Meaning |
|---|---|
| `--prefetch` / `SYNAPSE_PREFETCH` | `all` (default), `IN,US`, `id:<catalogue-id>`, or `off` |
| `--prefetch-max-mb` / `SYNAPSE_PREFETCH_MAX_MB` | skip extracts bigger than this (default 300) |
| `SYNAPSE_PREFETCH_FIRST` | countries downloaded first (default `IN`) |
| `SYNAPSE_ALLOW_INSTALL` | `1`/`0`: let the web page start installs (default: only on localhost) |
| `SYNAPSE_DATA`, `SYNAPSE_PERSISTENT` | data directory; mark it as persistent storage |
| `TAVILY_API_KEY`, `BIFROST_URL`, `BIFROST_MODELS`, `BIFROST_API_KEY` | enable the live freshness check (all optional) |

Manual pre-download (build time): `python scripts/prefetch_regions.py --scope IN --max-mb 150 --time-limit 1500` (`--dry-run` lists what it would fetch). Importing PBF extracts needs `osmium` (in `requirements.txt`).

## Deploy on Render
`render.yaml` is included. It prefetches maps at build time and in the background at start, and disables visitor-triggered installs. Free Render disk is wiped on each deploy and is too small for the whole world, so expect partial coverage; attach a persistent disk (`SYNAPSE_DATA=/var/data`, `SYNAPSE_PERSISTENT=1`) for permanent storage.

## Honest limits
- Whole-world road detail is tens of GB; it cannot live in git. Maps are downloaded on the server, not bundled.
- Online search relies on public OpenStreetMap services (Overpass, OSRM, Nominatim, Open-Meteo), which can be slow or rate-limited. Results are mapped records only: opening status, capacity and safety are **not verified**.
- Routing does not model live closures, hazard polygons, turn restrictions or vehicle profiles. Decision support only; always confirm with local emergency authorities.
- Offline street tiles exist only for areas you opened while online on that device; elsewhere you get the basic offline map.
- No live hazard feeds; severity is operator-entered.
- This is a prototype, not a production identity service: see `SECURITY.md` before exposing it publicly.

## Tests
```bash
python3 -m unittest discover -s tests -v
```

## Repository layout
`synapse/` server, routing engine, online helpers, catalogue/prefetch/installer · `ui/` single-page app, service worker, vendored Leaflet · `scripts/` map download/prefetch tools · `data/` world boundaries (regional packages are generated, git-ignored) · `tests/` unit tests.

## Sources and licences
OpenStreetMap data (ODbL): https://www.openstreetmap.org/copyright · Geofabrik extracts: https://download.geofabrik.de · Natural Earth boundaries · Leaflet (BSD-2). See `LICENSES_AND_ATTRIBUTION.md`.
