# SYNAPSE EARTH AI — Global Offline Disaster Response Command Centre

> **v15:** fixed Detect location, added an interactive world map and safer-shelter routing, new UI. See `README_FIX_v15.txt`.

## v5 additions: GPS-first, accounts and emergency guest access

- The browser can request device geolocation; it does not ask people to type coordinates.
- GPS coordinates are sent to the local server for offline reverse lookup against installed regional OSM settlement records.
- The result is explicitly marked as the nearest mapped settlement, not a guaranteed postal address.
- If no regional package covers the coordinates, the app retains GPS coordinates and clearly reports that offline country/city lookup is unavailable. It does not fabricate a country or city.
- Country/region selection and manual place search remain fallback options.
- Signup/login use SQLite, scrypt password hashing, opaque random sessions (only SHA-256 token hashes are stored), HttpOnly/SameSite cookies, session expiry, login throttling and CSRF-protected logout.
- Emergency guest mode is always available. Core emergency/map functions do not require login.

### Authentication limitations and production checklist
This is a hackathon prototype, not a production identity service. Signup does not send email verification, and password-reset delivery is not implemented. For public deployment, use HTTPS only, set secure cookies at the TLS-terminating proxy, configure verified email and password recovery, add MFA for privileged operators, security headers/CSP, audit logging, database backups, dependency scanning and an external penetration test. Do not expose the development server directly to the public internet.

## What this project is
A global-first, offline-capable disaster decision-support prototype. The global overview is separate from high-detail regional data. Install OSM packages for the places where offline operation is expected. A regional package can contain road segments, named cities/towns/villages/hamlets, and mapped facility nodes.

## Important truth about worldwide maps
It is not practical to bundle every street, city, village and point of interest on Earth in this source ZIP. Geofabrik's continent extracts alone are multi-gigabyte and the planet-scale database is much larger. This project therefore supports country/subdivision extracts on demand. It works in any country for which a suitable OSM extract is available and downloaded, but coverage/completeness varies by place. Geofabrik provides country and subdivision extracts and says most are updated daily: https://www.geofabrik.de/data/download.html

## Setup on macOS
```bash
cd SYNAPSE_EARTH_GLOBAL_v4
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
python3 scripts/download_world_map.py
python3 -m synapse.server --data ./data --host 127.0.0.1 --port 8080
```
Open http://127.0.0.1:8080. The world boundary GeoJSON is stored locally; after this one-time download, the overview works without internet.

## Install a real country or subregion map
1. Visit https://download.geofabrik.de/ and choose a country or subdivision `.osm.pbf` link. Prefer a state/province/county extract for a manageable first import.
2. Download it (replace URL with the official `.osm.pbf` URL):
```bash
python3 scripts/download_pbf.py --url https://download.geofabrik.de/asia/india-latest.osm.pbf
```
3. Import roads, named settlements and facilities:
```bash
python3 -m synapse.osm_import --pbf ./downloads/india-latest.osm.pbf --name "India extract" --country-code IN --region-id india-demo --out ./regions
```
4. Activate the package in the local server data directory:
```bash
curl -X POST --data-binary @./regions/india-demo.synapsepack http://127.0.0.1:8080/api/activate
```
5. Refresh installed regions in the UI. Select the package. City/town/village/hamlet names and road graph are now available offline for the imported extract.

### Smaller-area import
The importer also accepts `--bbox min_lon,min_lat,max_lon,max_lat`, for example:
```bash
python3 -m synapse.osm_import --pbf ./downloads/india-latest.osm.pbf --name "Pune demo area" --country-code IN --region-id pune-demo --bbox 72.5,18.0,73.5,19.0 --out ./regions
```
A bbox reduces the output graph but the importer still reads the source PBF. For large extracts, use a smaller Geofabrik subdivision extract to reduce RAM/time.

## Offline operation
- Download the world boundary file and regional OSM package(s) before connectivity is lost.
- Start the server locally; no cloud API or remote JS/CSS is needed.
- The map canvas renders country polygons, imported roads and settlement points from local files.
- Search for settlements only inside installed regional packages.
- Route calculations run locally using Dijkstra over the installed graph.
- If the region is absent, a road is missing, or the graph is disconnected, the app returns an explicit no-data/no-route result.
- Offline coverage is limited to the packages actually stored on the device. This is not an automatic worldwide offline map download.

## Agent design
1. Coverage Agent — source date, package scope, road nodes/segments, settlements and coverage warnings.
2. Hazard Agent — processes operator-entered disaster type/severity; does not pretend to detect live disasters offline.
3. Infrastructure Agent — summarizes mapped facilities; OSM presence does not prove operational status/capacity.
4. Route Agent — local shortest-path candidate only; does not certify hazard-safe routing.
5. Response Coordinator — produces human review actions and safety gates.

The five agents are deterministic local agents in v4. This is intentional for offline reproducibility. A local LLM can later produce explanations, but critical routing, package validation and safety gates should stay deterministic. Do not call this a cloud multi-agent LLM system.

## FieldSync / peer transfer
`GET /sync/{region_id}` exports a package. `POST /api/activate` imports a package with checksum/schema validation. For demo use on a trusted LAN only. Before exposing this to untrusted networks, add mutual authentication, TLS, signed packages, device pairing, audit logs, and replay protection. Do not port-forward this development server to the public internet.

## Known limitations (must disclose to judges)
- The world overview is Natural Earth country boundaries, not global city/village street mapping.
- City/village and road detail is available for imported OSM regions only.
- Current renderer is a canvas vector renderer, not a full commercial-style tiled street basemap with labels at every zoom.
- PBF importer handles selected highway classes and named place/facility nodes. It does not yet parse every settlement polygon/relation or all POI ways/relations.
- Routing does not yet model turn restrictions, complex access rules, bridges/tunnels/levels, live closures, hazard polygons or vehicle profiles.
- No live hazard feeds are included. Scenario severity is operator-entered.
- Not certified emergency navigation; local authorities and human operators must verify every action.

## Tests
```bash
python3 -m unittest discover -s tests -v
```

## Sources
Geofabrik downloads and regional extracts: https://www.geofabrik.de/data/download.html
OSM attribution and ODbL: https://www.openstreetmap.org/copyright
Natural Earth country data: https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/


## v6 additions: GPS-centred emergency map and nearby services

After the user grants browser location permission:
1. The map centres on the device's GPS coordinates and displays a cyan current-location marker.
2. The server searches only installed regional packages whose recorded geographic bounding box contains the GPS point.
3. The offline coverage strip reports whether a matching regional package is installed.
4. The nearby-services panel searches mapped facility records within 15 km and shows their straight-line distance.
5. The map marks returned facilities in amber. The list includes only records present in the installed package.

The nearby API is `GET /api/location/nearby?lat=<lat>&lon=<lon>&radius_m=15000`.
It returns either `FACILITY_DATA_AVAILABLE` or `NO_INSTALLED_REGIONAL_COVERAGE`.
The reverse lookup is `GET /api/location/reverse?lat=<lat>&lon=<lon>`.

### Nearby-service data limitations
The current OSM importer collects facility **nodes** tagged with amenity, healthcare, emergency or shelter. It does not yet fully import facility polygons/ways and relations. OSM completeness varies. A mapped facility is not proof that it is open, staffed, operational, safe, accessible or reachable. Distances are straight-line, not travel distances. The UI explicitly labels these as mapped records and does not certify them as emergency destinations.

The importer now records an extract bounding box automatically (or uses the explicit `--bbox`) so GPS matching does not accidentally match a settlement from an unrelated regional extract.


## v8 global map catalogue and GPS improvements

Start the server as usual. In the left panel, choose **Browse worldwide maps** while online, select a Geofabrik extract, then choose **Install selected**. The server downloads and imports the extract using its bounding box and activates it locally. Smaller regional extracts are recommended; the installer currently caps one PBF download at 3 GB.

GPS coordinates and accuracy are displayed immediately after permission is granted. The app first checks installed offline settlement packages; when no local match exists and internet is available, it attempts an explicitly labelled OpenStreetMap Nominatim reverse lookup. Online city lookup is not stored for offline use.

See `TEST_RESULTS_v8_GLOBAL_MAP_GPS.txt` for validation and limitations.


## v10 fixes
- The worldwide catalogue uses stable region IDs for selection and installation.
- GPS detection automatically fills the route planner's start coordinate.
- Guest and sign-in controls are bound before map initialization, so map loading
  failures do not disable identity controls.
- Catalogue and installation errors are surfaced in the UI.

To install a regional offline package: start the server, choose **Browse worldwide
maps**, select a small Geofabrik region, and choose **Install selected**. The
world country boundary layer is not a road-network package. Regional extracts
must be downloaded individually and require internet during installation.
\n## v11 fixes\n- Corrected route coordinate order to latitude,longitude.\n- Existing valid `./regions/*.synapsepack` files are auto-activated at server startup.\n- Clicking a mapped nearby facility selects it as a candidate destination; this does not certify safety or operating status.\n- Use a small regional extract covering both route endpoints; very large graphs can exceed browser memory.\n

## Worldwide regional map catalogue (v12)

- Select **Browse worldwide maps** while connected to the internet to fetch Geofabrik's worldwide extract index.
- Search the catalogue by country, state/province or region; entries are grouped by country where the source provides country metadata.
- The latest successful catalogue response is cached in `data/global_region_catalog.json`, so the list can be browsed later without a network connection.
- Select one extract and choose **Install selected**. The server downloads that extract, builds a local OSM road/place/facility package, and activates it.
- The worldwide country-boundary overview is separate from detailed road data. A country appearing on the overview does not mean its roads or shelters are installed.
- Geofabrik's published subdivision depth varies by country. The catalogue includes available Geofabrik extracts, not every municipality or neighbourhood on Earth.
- Detailed regional data requires an internet connection for initial download and sufficient disk space. After installation, that package can be used offline.
- OpenStreetMap data is licensed under ODbL. Facility records are mapped objects, not proof of a shelter's safety, staffing, capacity or current operating status.


## v13 — GPS-first shelter candidate routing

- Detect device GPS first; the start coordinate is populated automatically.
- Use **Find safer shelters & routes** to search installed regional OSM data for explicitly tagged shelter / emergency assembly-point records.
- The app calculates candidate road paths from the current GPS position and displays the selected route on the map. A rough walking-time estimate is shown separately from the road distance.
- No manual destination is required for this workflow.
- A hospital, clinic or other nearby service is not automatically labelled a safe shelter.
- If no explicitly tagged shelter is found, or the road graph cannot connect to it, the app reports that limitation instead of inventing a route.
- The worldwide catalogue lists Geofabrik extracts. It is not a preinstalled worldwide road database: download and install the needed country or smaller subregion while online. Smaller extracts are usually more practical.
- Shelter data may be missing or stale. The app cannot verify whether a site is open, staffed, outside the hazard zone, or approved by emergency authorities. Confirm with official local responders.


## Offline search and coverage diagnostics
- The safer-zones panel includes **Force offline search**. When enabled, the browser sends `online=0`; the server searches only installed regional packages and does not contact Overpass, Nominatim, elevation or remote routing services.
- The API distinguishes `NO_INSTALLED_REGION` (no package bounding box covers the current coordinates) from `REGION_INSTALLED_NO_FACILITIES` (a package covers the point but has no mapped candidate facilities).
- A successful offline search still requires a suitable installed regional package with usable road graph and mapped facility records. The app does not manufacture shelters, roads or routes.
- The world country-boundary layer is not a detailed street basemap. Full offline street rendering requires locally stored map data; this change improves offline search diagnostics but does not add raster/vector tile packs.
