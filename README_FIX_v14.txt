SYNAPSE EARTH v14 — reliability patch

1. Extract this folder.
2. Double-click START_SYNapse_EARTH.command, or run:
   cd ~/Desktop/SYNAPSE_EARTH_GLOBAL_v14
   chmod +x START_SYNapse_EARTH.command
   ./START_SYNapse_EARTH.command

3. The launcher creates .venv, installs requirements, downloads/validates the world country overview, then starts the server.
4. Open http://127.0.0.1:8080 and click Detect my location.
5. In Brave, allow Location for 127.0.0.1. In macOS enable Location Services and allow Brave.
6. Click Browse worldwide maps, wait for the catalogue, search for your country/subregion, select a SMALL regional extract, and click Install selected. The server must remain running.

Important fixes:
- World GeoJSON is validated before being served. A truncated/invalid existing file is replaced.
- World-map downloader writes to a temporary file and only replaces the final file after validation.
- GPS now shows a clear permission-denied message and a visible timeout fallback instead of appearing stuck.

No app can preinstall every road in the world in a small download. Country overview is lightweight; regional road packages must be downloaded individually. GPS requires browser/macOS permission. A route is only a candidate route, not a certified safe evacuation instruction.
