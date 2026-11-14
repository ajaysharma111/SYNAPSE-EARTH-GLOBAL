# SYNAPSE EARTH v20 — search performance update

This package uses the v16 hospital-discovery codebase supplied by the user, labelled locally as v20.

Changes:
- Short-lived (25 second) cache for successful safe-zone searches at the same GPS fix, hazard, travel mode, data mode, and installed-region version.
- Cache returns deep copies so UI/API callers cannot mutate cached data.
- Route requests use simplified geometry to reduce response payload while preserving route distance, duration, and turn-step data.
- Concurrent candidate route requests increased from 4 to 6 workers.

Safety and correctness:
- All discovered candidates are still retained; this update does not cap the list or silently omit hospitals/shelters.
- First-time search still depends on Overpass, elevation (for flood/cyclone), and routing service response times.
- Cache is short-lived and keyed to GPS coordinates; a changed GPS fix triggers a fresh search.
- Routes remain candidate routes, not verified safe routes. Facility capacity/open status remains unverified.
- Automated tests: 26 passed, 1 expected duplicate-SHA256 warning.
