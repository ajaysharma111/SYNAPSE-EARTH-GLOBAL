SYNAPSE EARTH GLOBAL v16 — AUTOMATIC REGIONAL MAP DOWNLOAD

What changed
- When a user sets an accurate GPS/map location, the app checks whether an installed regional package already covers it.
- If not, it fetches the Geofabrik regional catalogue, selects the smallest catalogue leaf extract covering the coordinates, and queues a background install automatically.
- Automatic downloads are enabled by default and can be disabled with the new checkbox in the map panel.
- Automatic installs are limited to 500 MB per extract; the existing installer checks available disk space, validates official Geofabrik HTTPS URLs, imports the OSM extract, and activates the package locally.
- If the browser reports a cellular connection, automatic downloading pauses; users can connect to Wi-Fi or install manually. Browsers that do not expose connection type cannot reliably distinguish Wi-Fi from cellular.
- Existing installed coverage prevents duplicate downloads. Existing manual catalogue and batch installation controls remain available.

Important limitations
- First regional download requires internet and the server process must remain running.
- The Python environment must have dependencies from requirements.txt installed (including osmium).
- Some regions have no small extract, exceed the 500 MB automatic limit, or are not represented as a leaf in the Geofabrik catalogue. In those cases the app reports the limitation and manual installation remains available.
- This does not preload detailed street data for the entire world. A device only has detailed offline data for regions it has downloaded or received from another device.
- Map freshness, OSM completeness, facility operational status and route safety remain unverified; follow emergency authorities.

Verification
- Python compileall: passed.
- Automated unit tests: 22 passed.
- Browser JavaScript syntax check (node --check): passed.
- Full end-to-end regional download was not run in this build environment; it must be verified on the user's Mac with a real network connection.
