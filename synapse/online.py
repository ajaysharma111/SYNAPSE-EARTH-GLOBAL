"""Online helpers for SYNAPSE EARTH: safe-zone discovery, routing and approximate location.

Everything here is *best effort*. The app is offline-first: installed regional packages are
always tried first, and every function in this module degrades to an explicit "unavailable"
result instead of inventing data. All network calls go through `fetch_json`, which tests replace.
"""
import copy, json, math, re, sys, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from .engine import haversine, shortest_path

UA = "SYNAPSE-EARTH/1.1 (disaster-response prototype; local server)"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter", "https://overpass.private.coffee/api/interpreter"]
ROUTERS = {
    "foot": ["https://routing.openstreetmap.de/routed-foot/route/v1/foot/{c}"],
    "driving": ["https://routing.openstreetmap.de/routed-car/route/v1/driving/{c}",
                "https://router.project-osrm.org/route/v1/driving/{c}"],
}
IP_SERVICES = [
    ("https://ipwho.is/", lambda j: (j.get("latitude"), j.get("longitude"), j.get("city"), j.get("region"), j.get("country"), j.get("country_code")) if j.get("success", True) else None),
    ("https://ipapi.co/json/", lambda j: (j.get("latitude"), j.get("longitude"), j.get("city"), j.get("region"), j.get("country_name"), j.get("country_code"))),
    ("https://get.geojs.io/v1/ip/geo.json", lambda j: (j.get("latitude"), j.get("longitude"), j.get("city"), j.get("region"), j.get("country"), j.get("country_code"))),
]
HAZARDS = {"Flood", "Earthquake", "Wildfire", "Cyclone", "Landslide", "Infrastructure failure"}
# Hazards where reaching higher ground than the current position is a meaningful safety signal.
HIGH_GROUND_HAZARDS = {"Flood", "Cyclone"}
# Emergency numbers only for places where the number is well established; otherwise a generic hint.
EMERGENCY_NUMBERS = {
    "IN": "112", "US": "911", "CA": "911", "GB": "999 or 112", "AU": "000", "NZ": "111",
    "JP": "119 (fire/ambulance) · 110 (police)", "DE": "112", "FR": "112", "ES": "112", "IT": "112",
    "NL": "112", "PT": "112", "IE": "112 or 999", "SE": "112", "NO": "112", "FI": "112",
    "PL": "112", "ZA": "112 (mobile) · 10111 (police)", "SG": "995 (ambulance/fire) · 999 (police)",
}
DEFAULT_EMERGENCY = "112 works on many mobile networks worldwide; otherwise dial your local emergency number"

TIER_LABELS = {"shelter": "Mapped shelter / assembly point", "refuge": "Possible refuge building", "medical": "Medical facility"}


def fetch_json(url, data=None, timeout=12, headers=None):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(20_000_000))


# --------------------------------------------------------------------------- classification
def classify(tags):
    """Return 'shelter' | 'refuge' | 'medical' | None for an OSM-style tag dict.

    Only explicit tags count. A bare `shelter=yes` is deliberately NOT accepted: in OSM it is
    overwhelmingly used for bus stops. Picnic huts, weather shelters, bus shelters etc. are rejected.
    """
    g = lambda k: str(tags.get(k, "") or "").lower()
    stype = g("shelter_type") or g("shelter")
    if g("emergency") in ("assembly_point", "shelter", "emergency_shelter") or g("amenity") in ("evacuation_centre", "evacuation_center"):
        return "shelter"
    if g("disaster_shelter") == "yes" or g("emergency:social_facility") == "shelter":
        return "shelter"
    if g("amenity") == "shelter" or g("type") in ("shelter", "emergency_shelter"):
        if g("public_transport") or g("highway") == "bus_stop" or g("bus") == "yes":
            return None
        if stype in ("picnic_shelter", "weather_shelter", "public_transport", "basic_hut", "lean_to", "gazebo", "rock_shelter", "bus_stop", "wildlife_hide", "field_shelter"):
            return None
        return "shelter"
    if g("amenity") in ("hospital", "clinic") or g("healthcare") in ("hospital", "clinic") or g("type") in ("hospital", "clinic"):
        return "medical"
    if g("amenity") in ("community_centre", "townhall", "fire_station") or g("type") in ("community_centre", "townhall", "fire_station"):
        return "refuge"
    return None


def facility_to_tags(f):
    """Installed-package facility records use flat keys; normalise them for classify()."""
    return {"type": f.get("type", ""), "emergency": f.get("emergency", ""), "amenity": f.get("amenity", ""),
            "healthcare": f.get("healthcare", ""), "shelter": ""}


# --------------------------------------------------------------------------- candidates
def offline_candidates(regions, lat, lon, radius_m=30000):
    """regions: iterable of (package, meta). Returns candidate dicts from installed packages."""
    out = []
    for rp, meta in regions:
        bb = rp.get("manifest", {}).get("bbox")
        if not bb or not (bb[0] <= lon <= bb[2] and bb[1] <= lat <= bb[3]):
            continue
        for f in rp.get("facilities", []):
            tier = classify(facility_to_tags(f))
            if not tier:
                continue
            d = haversine({"lat": lat, "lon": lon}, f)
            lim = radius_m if tier == "shelter" else min(radius_m, 10000)
            if d <= lim:
                out.append({"id": "off-" + str(f.get("id")), "name": f.get("name") or "Unnamed " + TIER_LABELS[tier].lower(),
                            "tier": tier, "kind": f.get("type") or f.get("amenity") or f.get("emergency") or tier,
                            "lat": float(f["lat"]), "lon": float(f["lon"]), "straight_line_m": round(d),
                            "source": "installed offline map", "region_id": meta.get("region_id"), "_pkg": rp})
    return out


def overpass_query(lat, lon, shelter_r, other_r):
    a = f"(around:{int(shelter_r)},{lat:.6f},{lon:.6f})"
    b = f"(around:{int(other_r)},{lat:.6f},{lon:.6f})"
    return ("[out:json][timeout:25];"
            "(" +
            f'nwr{a}["emergency"~"^(assembly_point|shelter|emergency_shelter)$"];' +
            f'nwr{a}["amenity"~"^(evacuation_centre|evacuation_center)$"];' +
            f'nwr{a}["amenity"="shelter"]["shelter_type"!~"^(picnic_shelter|weather_shelter|public_transport|basic_hut|lean_to|gazebo|rock_shelter)$"]["public_transport"!~"."]["highway"!~"."];' +
            ")->.s;"
            "(" +
            f'nwr{b}["amenity"~"^(hospital|clinic)$"];' +
            f'nwr{b}["healthcare"~"^(hospital|clinic)$"];' +
            f'nwr{b}["amenity"~"^(community_centre|townhall|fire_station)$"];' +
            ")->.o;"
            ".s out tags center 150;.o out tags center 250;")


def _log(msg):
    print("[safezones] " + msg, file=sys.stderr, flush=True)


def _overpass_one(ep, q, fetch):
    return fetch(ep, data={"data": q}, timeout=28)


def online_candidates(lat, lon, shelter_r=25000, other_r=8000, fetch=fetch_json):
    """Query several Overpass mirrors in parallel and use the first that answers."""
    q = overpass_query(lat, lon, shelter_r, other_r)
    errors, j = [], None
    with ThreadPoolExecutor(max_workers=len(OVERPASS)) as ex:
        futs = {ex.submit(_overpass_one, ep, q, fetch): ep for ep in OVERPASS}
        for f in as_completed(futs):
            try:
                j = f.result()
                if isinstance(j, dict) and "elements" in j:
                    break
                errors.append("%s: unexpected reply" % urllib.parse.urlparse(futs[f]).netloc)
            except Exception as e:  # noqa: BLE001 - network failures are expected and reported
                errors.append("%s: %s" % (urllib.parse.urlparse(futs[f]).netloc, str(e)[:80]))
        else:
            j = None
    if j is None:
        _log("Overpass failed: " + "; ".join(errors))
        raise ConnectionError("all Overpass servers failed (" + "; ".join(errors) + ")")
    out = []
    for el in j.get("elements", []):
        tags = el.get("tags") or {}
        tier = classify(tags)
        if not tier:
            continue
        la = el.get("lat") if "lat" in el else (el.get("center") or {}).get("lat")
        lo = el.get("lon") if "lon" in el else (el.get("center") or {}).get("lon")
        if la is None or lo is None:
            continue
        d = haversine({"lat": lat, "lon": lon}, {"lat": la, "lon": lo})
        kind = tags.get("emergency") or tags.get("amenity") or tags.get("healthcare") or tier
        out.append({"id": "osm-%s%s" % (el.get("type", "n")[0], el.get("id")), "name": tags.get("name") or tags.get("name:en") or "Unnamed " + TIER_LABELS[tier].lower(),
                    "tier": tier, "kind": kind, "lat": float(la), "lon": float(lo), "straight_line_m": round(d),
                    "source": "OpenStreetMap (online)", "phone": tags.get("phone") or tags.get("contact:phone")})
    return out


NOMINATIM_TERMS = ["hospital", "clinic", "evacuation shelter", "assembly point", "community centre", "fire station"]


def nominatim_candidates(lat, lon, half_deg=0.12, fetch=fetch_json, pause=1.05):
    """Fallback when Overpass is down: Nominatim search, bounded to a box around the user."""
    box = "%.5f,%.5f,%.5f,%.5f" % (lon - half_deg, lat + half_deg, lon + half_deg, lat - half_deg)
    out, seen, last = [], set(), None
    for i, term in enumerate(NOMINATIM_TERMS):
        if i:
            time.sleep(pause)  # Nominatim usage policy: max 1 request/second
        try:
            res = fetch("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
                {"q": term, "format": "jsonv2", "limit": 20, "bounded": 1, "viewbox": box, "addressdetails": 0}), timeout=10)
        except Exception as e:  # noqa: BLE001
            last = e
            if not out:
                break          # service unreachable: fail fast instead of waiting through every term
            continue
        for x in res if isinstance(res, list) else []:
            tags = {x.get("category") or x.get("class") or "": x.get("type") or ""}
            tier = classify(tags)
            key = (x.get("osm_type"), x.get("osm_id"))
            if not tier or key in seen:
                continue
            seen.add(key)
            la, lo = float(x["lat"]), float(x["lon"])
            d = haversine({"lat": lat, "lon": lon}, {"lat": la, "lon": lo})
            out.append({"id": "nom-%s%s" % ((x.get("osm_type") or "n")[0], x.get("osm_id")),
                        "name": x.get("name") or (x.get("display_name") or "").split(",")[0] or "Unnamed " + TIER_LABELS[tier].lower(),
                        "tier": tier, "kind": x.get("type") or tier, "lat": la, "lon": lo, "straight_line_m": round(d),
                        "source": "OpenStreetMap search (online)", "phone": None})
    if not out and last is not None:
        raise ConnectionError(str(last)[:100])
    return out


def dedupe(cands, within_m=40):
    kept = []
    for c in sorted(cands, key=lambda x: (x["source"] != "installed offline map", x["straight_line_m"])):
        if any(k["tier"] == c["tier"] and haversine(k, c) < within_m for k in kept):
            continue
        kept.append(c)
    return kept


def elevations(points, fetch=fetch_json):
    """Open-Meteo elevation (metres). Returns list aligned with points, or None on failure."""
    if not points:
        return []
    try:
        j = fetch("https://api.open-meteo.com/v1/elevation?" + urllib.parse.urlencode({
            "latitude": ",".join("%.5f" % p[0] for p in points), "longitude": ",".join("%.5f" % p[1] for p in points)}), timeout=10)
        el = j.get("elevation")
        return el if isinstance(el, list) and len(el) == len(points) else None
    except Exception:  # noqa: BLE001
        return None


def pick(cands, hazard, user_elev=None, elev=None):
    """Score every mapped candidate; route distance determines final ordering later."""
    elev = elev or {}
    mult = {"shelter": 1.0, "refuge": 1.8, "medical": 1.5}
    for c in cands:
        c["elevation_m"] = elev.get(c["id"])
        gain = None
        if user_elev is not None and c["elevation_m"] is not None:
            gain = round(c["elevation_m"] - user_elev)
        c["elevation_gain_m"] = gain
        score = c["straight_line_m"] * mult[c["tier"]]
        notes = []
        if hazard in HIGH_GROUND_HAZARDS and gain is not None:
            if gain >= 5:
                score *= 0.8; notes.append("higher ground (+%d m)" % gain)
            elif gain <= -5:
                score *= 1.6; notes.append("lower than you (%d m) — avoid for %s" % (gain, hazard.lower()))
        c["notes"] = notes
        c["score"] = round(score)
    # Do not silently hide mapped candidates behind category quotas. Users need
    # alternatives if a facility is full, closed, inaccessible or unsuitable.
    return sorted(cands, key=lambda x: (x["score"], x["straight_line_m"]))


# --------------------------------------------------------------------------- routing
def bearing_text(lat1, lon1, lat2, lon2):
    y = math.sin(math.radians(lon2 - lon1)) * math.cos(math.radians(lat2))
    x = math.cos(math.radians(lat1)) * math.sin(math.radians(lat2)) - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(math.radians(lon2 - lon1))
    deg = (math.degrees(math.atan2(y, x)) + 360) % 360
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][int((deg + 22.5) // 45) % 8], round(deg)


def route_online(lat, lon, dlat, dlon, mode="foot", fetch=fetch_json):
    coords = "%.6f,%.6f;%.6f,%.6f" % (lon, lat, dlon, dlat)
    last = None
    for tpl in ROUTERS.get(mode, ROUTERS["foot"]):
        try:
            j = fetch(tpl.format(c=coords) + "?overview=simplified&geometries=geojson&steps=true", timeout=15)
            if j.get("code") != "Ok" or not j.get("routes"):
                last = j.get("code"); continue
            r = j["routes"][0]
            names, steps = [], []
            for leg in r.get("legs", []):
                for s in leg.get("steps", []):
                    if s.get("name"):
                        names.append(s["name"])
                    m = s.get("maneuver", {})
                    if m.get("type") not in (None, "depart", "arrive") or m.get("type") == "arrive":
                        steps.append({"text": _step_text(s), "distance_m": round(s.get("distance", 0))})
            return {"status": "CANDIDATE_ROUTE", "source": "online road routing (OpenStreetMap data)", "mode": mode,
                    "distance_m": round(r["distance"]), "duration_s": round(r["duration"]),
                    "coordinates": r["geometry"]["coordinates"], "road_names": list(dict.fromkeys(names))[:12], "steps": steps[:40],
                    "warning": "Candidate route only. Road closures, hazard exposure and access restrictions are not modelled; confirm with emergency authorities."}
        except Exception as e:  # noqa: BLE001
            last = e
    return {"status": "ROUTING_UNAVAILABLE", "message": "Online routing service unavailable: %s" % last}


def _step_text(s):
    m = s.get("maneuver", {})
    t, mod, name = m.get("type", ""), m.get("modifier", ""), s.get("name") or "the road"
    if t == "arrive":
        return "Arrive at destination"
    if t in ("turn", "end of road", "fork", "on ramp", "off ramp"):
        return "Turn %s onto %s" % (mod or "", name)
    if t == "roundabout":
        return "Take the roundabout onto %s" % name
    return "Continue on %s" % name


def straight_line_route(lat, lon, dlat, dlon, reason=""):
    d = haversine({"lat": lat, "lon": lon}, {"lat": dlat, "lon": dlon})
    card, deg = bearing_text(lat, lon, dlat, dlon)
    return {"status": "STRAIGHT_LINE_ONLY", "source": "straight-line bearing (no road data)", "distance_m": round(d),
            "coordinates": [[lon, lat], [dlon, dlat]], "road_names": [], "steps": [],
            "bearing": "%s (%d°)" % (card, deg),
            "warning": "No road route could be calculated%s. The dashed line is a direct bearing only and may cross water, barriers or hazards." % ((": " + reason) if reason else "")}


def route_one(c, lat, lon, mode, fetch=fetch_json, allow_online=True):
    pkg = c.get("_pkg")
    if pkg is not None:
        r = shortest_path(pkg, lat, lon, c["lat"], c["lon"])
        if r.get("status") == "CANDIDATE_ROUTE" and r["snap_start_m"] < 1500 and r["snap_end_m"] < 1500:
            r["source"] = "installed offline road graph"; r["mode"] = "offline"
            return r
    if allow_online:
        r = route_online(lat, lon, c["lat"], c["lon"], mode, fetch)
        if r["status"] == "CANDIDATE_ROUTE":
            return r
        return straight_line_route(lat, lon, c["lat"], c["lon"], r.get("message", ""))
    return straight_line_route(lat, lon, c["lat"], c["lon"], "offline and no installed road graph covers this route")


# --------------------------------------------------------------------------- orchestration
def _safe_zones_uncached(regions, lat, lon, hazard="Flood", mode="foot", fetch=fetch_json, use_online=True):
    hazard = hazard if hazard in HAZARDS else "Flood"
    mode = mode if mode in ROUTERS else "foot"
    notes, status = [], {"offline_data": False, "online_data": False}
    cands = offline_candidates(regions, lat, lon)
    status["offline_data"] = bool(cands)
    if use_online:
        on, why = [], None
        try:
            on = online_candidates(lat, lon, fetch=fetch)
            status["online_data"] = True
        except Exception as e:  # noqa: BLE001
            why = str(e)[:300]
        if not [c for c in on if c["tier"]]:
            try:
                fb = nominatim_candidates(lat, lon, fetch=fetch, pause=0 if fetch is not fetch_json else 1.05)
                if fb:
                    on += fb; status["online_data"] = True
                    if why:
                        notes.append("Main OpenStreetMap shelter service was unreachable, so results come from the slower fallback search and may be less complete.")
                    why = None
            except Exception as e2:  # noqa: BLE001
                why = (why + " | " if why else "") + "fallback: " + str(e2)[:120]
        if why:
            notes.append("Online shelter search failed: " + why)
        cands += on
    cands = dedupe(cands)
    if not cands:
        return {"status": "NO_MAPPED_SAFE_ZONES", "destinations": [], "sources": status, "notes": notes,
                "message": "No mapped shelters, assembly points, community buildings or medical facilities were found within range. "
                           "SYNAPSE will not invent a safe destination. Install a regional map package, try again while online, "
                           "or contact local emergency services."}
    # Keep every mapped candidate so the user can compare alternatives and report
    # a full/closed facility. This is deliberately not a claim that every facility is safe.
    pre = pick(cands, hazard)
    elev = {}
    user_elev = None
    if use_online and status["online_data"] and hazard in HIGH_GROUND_HAZARDS:
        pts = [(lat, lon)] + [(c["lat"], c["lon"]) for c in cands[:99]]
        ev = elevations(pts, fetch)
        if ev:
            user_elev = ev[0]
            elev = {c["id"]: ev[i + 1] for i, c in enumerate(cands[:99])}
            pre = pick(cands, hazard, user_elev, elev)
        else:
            notes.append("Elevation data unavailable; high-ground ranking skipped.")
    with ThreadPoolExecutor(max_workers=6) as ex:
        routes = list(ex.map(lambda c: route_one(c, lat, lon, mode, fetch, use_online), pre))
    dests = []
    for c, r in zip(pre, routes):
        d = {k: v for k, v in c.items() if not k.startswith("_")}
        d["tier_label"] = TIER_LABELS[c["tier"]]
        d["route"] = r
        d["verification"] = "Mapped record only: opening status, capacity, hazard exposure and safety are NOT verified."
        dests.append(d)
    # Rank by actual road distance where a road route exists. Keep direct-line
    # fallbacks after road-routed candidates and label them as approximate.
    dests.sort(key=lambda d: (
        d["route"].get("status") != "CANDIDATE_ROUTE",
        d["route"].get("distance_m", d["straight_line_m"]),
        d["straight_line_m"], d["tier"] != "shelter"))
    for i, d in enumerate(dests):
        d["rank"] = i + 1
    return {"status": "OK", "hazard": hazard, "mode": mode, "user_elevation_m": user_elev, "destinations": dests,
            "sources": status, "notes": notes}



# Short-lived response cache for repeat taps at the same GPS fix. Cache keys include
# installed package identity/version, travel mode, hazard and data mode so a changed
# location or newly installed region does not reuse unrelated results.
_SAFEZONE_CACHE = {}
_SAFEZONE_CACHE_LOCK = threading.RLock()
_SAFEZONE_CACHE_TTL = 25.0
_SAFEZONE_CACHE_MAX = 24


def safe_zones(regions, lat, lon, hazard="Flood", mode="foot", fetch=fetch_json, use_online=True):
    region_key = tuple(
        (id(pkg), (meta or {}).get("region_id"), (pkg.get("manifest") or {}).get("generated_at"))
        for pkg, meta in regions
    )
    key = (round(float(lat), 5), round(float(lon), 5), hazard, mode,
           bool(use_online), id(fetch), region_key)
    now = time.monotonic()
    with _SAFEZONE_CACHE_LOCK:
        hit = _SAFEZONE_CACHE.get(key)
        if hit and now - hit[0] <= _SAFEZONE_CACHE_TTL:
            return copy.deepcopy(hit[1])
        if hit:
            _SAFEZONE_CACHE.pop(key, None)

    result = _safe_zones_uncached(regions, lat, lon, hazard, mode, fetch, use_online)
    if result.get("status") == "OK":
        with _SAFEZONE_CACHE_LOCK:
            if len(_SAFEZONE_CACHE) >= _SAFEZONE_CACHE_MAX:
                oldest = min(_SAFEZONE_CACHE, key=lambda k: _SAFEZONE_CACHE[k][0])
                _SAFEZONE_CACHE.pop(oldest, None)
            _SAFEZONE_CACHE[key] = (time.monotonic(), copy.deepcopy(result))
    return result


def emergency_number(cc):
    return EMERGENCY_NUMBERS.get((cc or "").upper(), DEFAULT_EMERGENCY)


# --------------------------------------------------------------------------- IP location / geocoding
def ip_location(fetch=fetch_json):
    errs = []
    for url, parse in IP_SERVICES:
        try:
            r = parse(fetch(url, timeout=6))
            if r and r[0] is not None and r[1] is not None:
                la, lo = float(r[0]), float(r[1])
                if -90 <= la <= 90 and -180 <= lo <= 180:
                    return {"status": "APPROXIMATE_IP_LOCATION", "lat": la, "lon": lo, "city": r[2], "region": r[3], "country": r[4],
                            "country_code": (r[5] or "").upper(), "accuracy_m": 25000,
                            "note": "Approximate location from your internet connection (typically city-level, often 5–50 km off). Use GPS or pick the exact spot on the map for routing."}
        except Exception as e:  # noqa: BLE001
            errs.append(str(e)[:80])
    return {"status": "IP_LOCATION_UNAVAILABLE", "errors": errs}


def geocode(q, fetch=fetch_json):
    q = re.sub(r"\s+", " ", q or "").strip()[:200]
    if not q:
        return {"results": []}
    j = fetch("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "jsonv2", "limit": 6, "addressdetails": 1}), timeout=8)
    return {"results": [{"name": x.get("display_name"), "lat": float(x["lat"]), "lon": float(x["lon"]),
                         "country_code": ((x.get("address") or {}).get("country_code") or "").upper()} for x in j]}
