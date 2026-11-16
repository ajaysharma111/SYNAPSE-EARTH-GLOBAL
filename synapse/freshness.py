"""Live "is this place still usable?" check for a shelter/hospital record.

Map data is a snapshot: OSM can list a shelter that has closed or been damaged. This module asks Tavily for recent
news/web evidence about one place and has a model (through the Bifrost gateway) judge it. Keys stay on the server.
Everything degrades honestly: with no model configured it returns the sources only, never an invented status."""
import json, os, re, threading, time, urllib.request, urllib.error

_CACHE = {}
_LOCK = threading.Lock()
_HITS = {}
TTL = 1800

JUDGE = ("You check whether a emergency shelter, hospital or assembly point is still usable, using ONLY the numbered web "
         "results. Return ONLY JSON: {\"status\":\"open|closed|damaged|unknown\",\"confidence\":0..1,\"reason\":\"one sentence\","
         "\"evidence\":[result numbers]}. If the results do not mention this place or are unrelated, status is unknown.")


def settings(env=os.environ):
    models = [m.strip() for m in env.get("BIFROST_MODELS", env.get("BIFROST_MODEL", "")).split(",") if m.strip()]
    return {"tavily_key": env.get("TAVILY_API_KEY", ""), "bifrost_url": env.get("BIFROST_URL", "").rstrip("/"),
            "bifrost_key": env.get("BIFROST_API_KEY", ""), "models": models}


def enabled(cfg=None):
    return bool((cfg or settings())["tavily_key"])


def _post(url, payload, headers, timeout=25):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read(5_000_000))


def rate_ok(ip, limit=20, window=60, now=None):
    now = now or time.time()
    with _LOCK:
        hits = [t for t in _HITS.get(ip, []) if now - t < window]
        if len(hits) >= limit:
            _HITS[ip] = hits
            return False
        hits.append(now); _HITS[ip] = hits
        return True


def verify_place(name, near="", cfg=None, post=_post, now=None):
    cfg = cfg or settings()
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:120]
    if not name:
        raise ValueError("name is required")
    if not cfg["tavily_key"]:
        return {"configured": False, "status": "unknown", "summary": "Live checking is not configured on this server (TAVILY_API_KEY)."}
    key = (name.lower(), near.lower()); now = now or time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < TTL:
            return hit[1]
    q = '"%s" %s closed OR open OR damaged OR flooded OR evacuation' % (name, near)
    r = post("https://api.tavily.com/search", {"query": q[:380], "search_depth": "basic", "max_results": 5, "topic": "news", "time_range": "month"},
             {"Authorization": "Bearer " + cfg["tavily_key"]})
    res = [{"title": x.get("title", ""), "url": x.get("url", ""), "content": (x.get("content") or "")[:500], "date": x.get("published_date")} for x in (r.get("results") or [])]
    out = {"configured": True, "status": "unknown", "confidence": 0, "summary": "", "sources": [], "judged_by_model": False}
    if not res:
        out["summary"] = "No news or web pages from the last month mention this place. Its status is unknown; confirm by phone or with local authorities."
    elif cfg["bifrost_url"] and cfg["models"]:
        ev = "\n".join("[%d] %s (%s): %s" % (i + 1, x["title"][:90], x["date"] or "undated", x["content"][:300]) for i, x in enumerate(res))
        for model in cfg["models"]:
            try:
                h = {"Authorization": "Bearer " + cfg["bifrost_key"]} if cfg["bifrost_key"] else {}
                j = post(cfg["bifrost_url"] + "/v1/chat/completions", {"model": model, "temperature": 0, "max_tokens": 300, "messages": [
                    {"role": "system", "content": JUDGE}, {"role": "user", "content": "Place: %s %s\n\nResults:\n%s" % (name, near, ev)}]}, h, 40)
                v = json.loads(re.search(r"\{.*\}", j["choices"][0]["message"]["content"], re.S).group(0))
                used = sorted({int(n) for n in (v.get("evidence") or []) if str(n).isdigit() and 1 <= int(n) <= len(res)})
                st = str(v.get("status", "unknown")).lower()
                if st not in ("open", "closed", "damaged") or not used:
                    st, used = "unknown", used
                out.update(status=st, confidence=round(min(max(float(v.get("confidence", 0)), 0), 1), 2) if st != "unknown" else 0,
                           summary=str(v.get("reason") or "")[:300], sources=[res[i - 1] for i in used], judged_by_model=True)
                break
            except Exception:
                continue
    if not out["judged_by_model"]:
        out["summary"] = out["summary"] or "Recent sources are listed below, but no AI judge is configured, so no status is claimed. Read them yourself."
        out["sources"] = res[:4]
    out["sources"] = [{"title": s["title"], "url": s["url"], "date": s.get("date")} for s in out["sources"]]
    out["disclaimer"] = "News search is not a live status feed. Always confirm with local authorities."
    with _LOCK:
        _CACHE[key] = (now, out)
        if len(_CACHE) > 300:
            _CACHE.pop(next(iter(_CACHE)))
    return out
