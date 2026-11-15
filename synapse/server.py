import argparse,json,hashlib,hmac,urllib.request,urllib.parse,subprocess,sys,tempfile,os,re
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlparse,unquote
from .engine import load_regions,get_region,activate_package,run_agents,shortest_path,save_package,haversine
from .auth import AuthStore,AuthError
from . import online
from . import prefetch as prefetch_mod
from .catalog import get_catalog
from .engine import _graph_for
import threading,time
from .installer import BatchInstaller,install_one,validate_item
import mimetypes
UI_DIR=Path(__file__).resolve().parent.parent/"ui"
class App(BaseHTTPRequestHandler):
    data="data"
    def log_message(self,*a): pass
    def sendj(self,code,obj,cache=None):
        b=json.dumps(obj,ensure_ascii=False).encode();self.send_response(code);self.send_header("Content-Type","application/json; charset=utf-8");self.send_header("Content-Length",str(len(b)));self.send_header("Cache-Control",cache or "no-store");self.end_headers();self.wfile.write(b)
    def cookies(self):
        from http.cookies import SimpleCookie
        c=SimpleCookie()
        try:c.load(self.headers.get("Cookie",""))
        except Exception:pass
        return {k:v.value for k,v in c.items()}
    def set_session_cookie(self,token):
        secure="; Secure" if self.headers.get("X-Forwarded-Proto","").lower()=="https" else ""
        self.send_header("Set-Cookie",f"synapse_session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200{secure}")
    def send_auth(self, result, status=200):
        b=json.dumps({k:v for k,v in result.items() if k!="token"}).encode()
        self.send_response(status);self.send_header("Content-Type","application/json; charset=utf-8")
        self.send_header("Content-Length",str(len(b)));self.send_header("Cache-Control","no-store")
        self.set_session_cookie(result["token"]);self.end_headers();self.wfile.write(b)
    def qs(self):
        from urllib.parse import parse_qs
        return parse_qs(urlparse(self.path).query)
    def latlon(self,q,a="lat",b="lon"):
        lat=float(q[a][0]);lon=float(q[b][0])
        if not (-90<=lat<=90 and -180<=lon<=180):raise ValueError("out of range")
        return lat,lon
    def installed_regions(self,lat=None,lon=None):
        out=[]
        for meta in load_regions(self.data):
            bb=meta.get("bbox")
            if lat is not None and not (bb and bb[0]<=lon<=bb[2] and bb[1]<=lat<=bb[3]):continue
            try:out.append((get_region(self.data,meta["region_id"]),meta))
            except Exception:continue
        return out
    def send_static(self,rel):
        f=(UI_DIR/rel).resolve()
        if UI_DIR.resolve() not in f.parents or not f.is_file():return self.sendj(404,{"error":"not found"})
        b=f.read_bytes();ct=mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        if ct.startswith("text/") or ct in("application/javascript",):ct+="; charset=utf-8"
        self.send_response(200);self.send_header("Content-Type",ct);self.send_header("Content-Length",str(len(b)));self.send_header("Cache-Control","public, max-age=86400");self.end_headers();self.wfile.write(b)
    def do_GET(self):
        path=unquote(urlparse(self.path).path)
        if path.startswith("/vendor/"):return self.send_static(path[1:])
        if path=="/sw.js":
            b=(Path(__file__).parent.parent/"ui"/"sw.js").read_bytes();self.send_response(200);self.send_header("Content-Type","text/javascript; charset=utf-8");self.send_header("Content-Length",str(len(b)));self.send_header("Cache-Control","no-cache");self.end_headers();self.wfile.write(b);return
        if path=="/api/location/ip":return self.sendj(200,online.ip_location())
        if path=="/api/geocode":
            try:return self.sendj(200,online.geocode(self.qs().get("q",[""])[0]))
            except Exception as e:return self.sendj(503,{"error":"Online place search unavailable: "+str(e)[:150],"results":[]})
        if path=="/api/search/places":
            # Search only locally installed regional packages; this endpoint never uses the network.
            q=self.qs().get("q",[""])[0].strip().casefold()
            if len(q)<2:return self.sendj(200,{"source":"installed_offline_data","results":[]})
            matches=[];seen=set()
            for meta in load_regions(self.data):
                try:
                    rp=get_region(self.data,meta["region_id"])
                    for place in rp.get("places",[]):
                        name=str(place.get("name") or "").strip()
                        if q not in name.casefold():continue
                        key=(name.casefold(),round(float(place["lat"]),5),round(float(place["lon"]),5))
                        if key in seen:continue
                        seen.add(key)
                        matches.append({"name":name,"place_type":place.get("place_type","settlement"),
                            "lat":float(place["lat"]),"lon":float(place["lon"]),
                            "region":rp.get("manifest",{}).get("name",meta.get("name","Installed region")),
                            "country_code":rp.get("manifest",{}).get("country_code")})
                except Exception:continue
            matches.sort(key=lambda x:(not x["name"].casefold().startswith(q),x["name"].casefold()))
            return self.sendj(200,{"source":"installed_offline_data","count":len(matches),"results":matches[:50]})
        if path=="/api/safezones":
            try:
                q=self.qs();lat,lon=self.latlon(q)
            except Exception:return self.sendj(400,{"error":"Valid lat and lon query parameters are required."})
            res=online.safe_zones(self.installed_regions(lat,lon),lat,lon,q.get("hazard",["Flood"])[0],q.get("mode",["foot"])[0],use_online=q.get("online",["1"])[0]!="0",radius_m=float(q.get("radius_m",["30000"])[0] or 30000))
            cc=q.get("cc",[""])[0];res["emergency_number"]=online.emergency_number(cc)
            return self.sendj(200,res)
        if path=="/api/emergency-number":return self.sendj(200,{"number":online.emergency_number(self.qs().get("cc",[""])[0])})
        if path=="/api/health":return self.sendj(200,{"status":"local","offline_capable":True,"authentication":"enabled","guest_mode":True})
        if path=="/api/auth/me":
            s=self.auth.current(self.cookies().get("synapse_session"))
            return self.sendj(200,{"authenticated":bool(s),"user":s["user"] if s else None,"csrf":s["csrf"] if s else None})
        if path=="/api/catalog":
            # Cached on disk for 7 days (Geofabrik's index is several MB); only refreshed when stale or missing.
            try:return self.sendj(200,get_catalog(self.data))
            except Exception as e:
                return self.sendj(503,{"error":str(e),"hint":"Connect to the internet once to download and cache the worldwide extract catalogue. Installed packages continue working offline."})
        if path=="/api/config":
            return self.sendj(200,{"allow_install":App.allow_install,"prefetch_scope":App.prefetch_scope,"persistent_data":App.persistent,
                "data_dir_note":"Regional maps are stored on the server once and reused; visitors' browsers only fetch small map tiles for the area on screen."})
        if path.startswith("/api/region-info/"):
            try:
                pkg=get_region(self.data,path.rsplit("/",1)[1]);m=pkg["manifest"]
                return self.sendj(200,{"manifest":m,"counts":{"nodes":len(pkg["nodes"]),"edges":len(pkg["edges"]),"places":len(pkg.get("places",[])),"facilities":len(pkg.get("facilities",[]))}},cache="public, max-age=300")
            except Exception as e:return self.sendj(404,{"error":str(e)})
        if path.startswith("/api/region-roads/"):
            # Only the roads/places inside the visible map box are sent (never the whole regional package).
            try:
                q=self.qs();w,so,e,n=[float(x) for x in q["bbox"][0].split(",")];cap=min(int(q.get("max",["9000"])[0]),20000)
                pkg=get_region(self.data,path.rsplit("/",1)[1]);_,nodes=_graph_for(pkg);lines=[]
                for ed in pkg["edges"]:
                    a_=nodes.get(ed["from"]);b_=nodes.get(ed["to"])
                    if not a_ or not b_:continue
                    if (a_["lon"]<w and b_["lon"]<w) or (a_["lon"]>e and b_["lon"]>e) or (a_["lat"]<so and b_["lat"]<so) or (a_["lat"]>n and b_["lat"]>n):continue
                    lines.append([round(a_["lat"],5),round(a_["lon"],5),round(b_["lat"],5),round(b_["lon"],5)])
                    if len(lines)>=cap:break
                places=[{"name":p_["name"],"place_type":p_.get("place_type",""),"lat":p_["lat"],"lon":p_["lon"]} for p_ in pkg.get("places",[]) if w<=p_["lon"]<=e and so<=p_["lat"]<=n][:300]
                return self.sendj(200,{"lines":lines,"places":places,"truncated":len(lines)>=cap},cache="public, max-age=3600")
            except Exception as ex:return self.sendj(400,{"error":"bbox=west,south,east,north is required ("+str(ex)[:80]+")"})
        if path=="/api/location/reverse":
            try:
                from urllib.parse import parse_qs
                q=parse_qs(urlparse(self.path).query);lat=float(q["lat"][0]);lon=float(q["lon"][0])
                if not (-90<=lat<=90 and -180<=lon<=180):raise ValueError()
            except Exception:return self.sendj(400,{"error":"Valid lat and lon query parameters are required."})
            candidates=[]
            for meta in load_regions(self.data):
                try:
                    bb=meta.get("bbox")
                    if not bb or not (bb[0]<=lon<=bb[2] and bb[1]<=lat<=bb[3]):continue
                    rp=get_region(self.data,meta["region_id"])
                    candidates.append((rp,meta))
                except Exception:continue
            best=None
            for rp,meta in candidates:
                for p in rp.get("places",[]):
                    d=haversine({"lat":lat,"lon":lon},p)
                    if best is None or d<best[0]:best=(d,p,rp,meta)
            if best:
                d,p,rp,meta=best
                return self.sendj(200,{"status":"MATCHED_TO_INSTALLED_REGION","latitude":lat,"longitude":lon,
                  "country_code":rp["manifest"].get("country_code"),"region":rp["manifest"].get("name"),"region_id":rp["manifest"].get("region_id"),
                  "place":p["name"],"place_type":p.get("place_type"),"distance_to_place_m":round(d),
                  "note":"Nearest settlement in installed OpenStreetMap package; not an authoritative address."})
            # Online fallback is explicitly labelled and only attempted when local packages have no match.
            try:
                query=urllib.parse.urlencode({"format":"jsonv2","lat":lat,"lon":lon,"zoom":10,"addressdetails":1})
                req=urllib.request.Request("https://nominatim.openstreetmap.org/reverse?"+query,headers={"User-Agent":"SYNAPSE-EARTH/1.0 (disaster-response prototype)"})
                with urllib.request.urlopen(req,timeout=7) as r: geo=json.loads(r.read())
                addr=geo.get("address",{})
                place=addr.get("city") or addr.get("town") or addr.get("village") or addr.get("municipality") or addr.get("suburb") or addr.get("county")
                return self.sendj(200,{"status":"ONLINE_REVERSE_GEOCODE","latitude":lat,"longitude":lon,
                  "place":place,"district":addr.get("county"),"state":addr.get("state"),"country":addr.get("country"),
                  "country_code":(addr.get("country_code") or "").upper(),"display_name":geo.get("display_name"),
                  "note":"City/administrative name resolved using online OpenStreetMap Nominatim. This result is not stored for offline use."})
            except Exception:
                return self.sendj(200,{"status":"GPS_ONLY_NO_LOCAL_GEOCODER","latitude":lat,"longitude":lon,
                  "country_code":None,"place":None,"note":"GPS coordinates captured. No installed offline settlement match and online reverse geocoding was unavailable."})
        if path=="/api/location/nearby":
            try:
                from urllib.parse import parse_qs
                q=parse_qs(urlparse(self.path).query)
                lat=float(q["lat"][0]);lon=float(q["lon"][0]);radius=max(100,min(100000,float(q.get("radius_m",["10000"])[0])))
                if not (-90<=lat<=90 and -180<=lon<=180):raise ValueError()
            except Exception:return self.sendj(400,{"error":"Valid lat/lon and optional radius_m are required."})
            matching=[];covered=False
            for meta in load_regions(self.data):
                try:
                    bb=meta.get("bbox")
                    if not bb or not (bb[0]<=lon<=bb[2] and bb[1]<=lat<=bb[3]):continue
                    rp=get_region(self.data,meta["region_id"])
                    covered=True
                    for f in rp.get("facilities",[]):
                        d=haversine({"lat":lat,"lon":lon},f)
                        if d<=radius:
                            matching.append({**f,"distance_m":round(d),"region_id":meta["region_id"]})
                except Exception:continue
            matching.sort(key=lambda x:x["distance_m"])
            return self.sendj(200,{"coverage":"FACILITY_DATA_AVAILABLE" if covered else "NO_INSTALLED_REGIONAL_COVERAGE",
                "latitude":lat,"longitude":lon,"radius_m":radius,"facility_records":len(matching),
                "facilities":matching[:100],
                "facility_note":"Mapped OSM facilities only. This list is not exhaustive and does not confirm that a facility is open, staffed, reachable or safe."})
        if path=="/api/evacuation":
            try:
                from urllib.parse import parse_qs
                q=parse_qs(urlparse(self.path).query)
                lat=float(q["lat"][0]);lon=float(q["lon"][0])
                radius=max(500,min(50000,float(q.get("radius_m",["15000"])[0])))
                if not (-90<=lat<=90 and -180<=lon<=180):raise ValueError()
            except Exception:return self.sendj(400,{"error":"Valid GPS latitude and longitude are required."})
            candidates=[]
            for meta in load_regions(self.data):
                try:
                    bb=meta.get("bbox")
                    if not bb or not (bb[0]<=lon<=bb[2] and bb[1]<=lat<=bb[3]):continue
                    rp=get_region(self.data,meta["region_id"])
                    for f in rp.get("facilities",[]):
                        typ=str(f.get("type","")).lower()
                        emergency=str(f.get("emergency","")).lower()
                        shelter=str(f.get("shelter","")).lower()
                        amenity=str(f.get("amenity","")).lower()
                        # Only explicitly tagged shelter/assembly-point records qualify as shelter candidates.
                        is_shelter=(typ in ("shelter","emergency_shelter") or
                            emergency in ("shelter","assembly_point","emergency_shelter") or
                            shelter not in ("","no","false","0") or
                            amenity in ("shelter","evacuation_centre","evacuation_center"))
                        if not is_shelter:continue
                        d=haversine({"lat":lat,"lon":lon},f)
                        if d<=radius:candidates.append((d,f,rp,meta))
                except Exception:continue
            if not candidates:
                return self.sendj(200,{"status":"NO_MAPPED_SHELTER_CANDIDATES","latitude":lat,"longitude":lon,
                    "radius_m":radius,"destinations":[],"message":"No explicitly mapped shelter or emergency assembly-point records were found inside installed regional coverage. Nearby hospitals/clinics are not automatically treated as safe shelters. Install the correct local extract or verify a shelter with emergency authorities."})
            candidates.sort(key=lambda x:x[0])
            results=[];route_errors=[]
            for d,f,rp,meta in candidates[:8]:
                route=shortest_path(rp,lat,lon,float(f["lat"]),float(f["lon"]))
                if route.get("status")=="CANDIDATE_ROUTE":
                    results.append({"name":f.get("name") or "Unnamed mapped shelter","type":f.get("type"),
                        "emergency":f.get("emergency"),"latitude":f["lat"],"longitude":f["lon"],
                        "straight_line_m":round(d),"region_id":meta["region_id"],"route":route,
                        "verification":"OSM-tagged shelter candidate; operating status, hazard exposure and safety are unverified."})
                else:route_errors.append({"name":f.get("name"),"status":route.get("status"),"message":route.get("message")})
            return self.sendj(200,{"status":"ROUTES_FOUND" if results else "SHELTERS_FOUND_NO_ROAD_ROUTE",
                "latitude":lat,"longitude":lon,"radius_m":radius,"destinations":results,
                "route_errors":route_errors,"message":"Choose a candidate only after confirming it is open, reachable and safe with local emergency authorities." if results else "Mapped shelter records exist, but no connected road route could be calculated in the installed graph."})
        if path=="/api/regions/jobs":return self.sendj(200,App.batch.status())
        if path=="/api/regions":return self.sendj(200,{"regions":load_regions(self.data)})
        if path=="/api/world":
            p=Path(self.data)/"world_countries.geojson"
            # First launch: install the small Natural Earth country overview automatically
            # when online. Once saved, the map is served locally and works offline.
            try:
                valid=False
                if p.exists():
                    try:
                        existing=json.loads(p.read_text())
                        valid=existing.get("type")=="FeatureCollection" and len(existing.get("features",[]))>=100
                    except Exception:
                        valid=False
                if not valid:
                    url="https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"
                    req=urllib.request.Request(url,headers={"User-Agent":"SYNAPSE-EARTH/1.0 (world overview installer)"})
                    with urllib.request.urlopen(req,timeout=45) as response:
                        raw=response.read(25_000_000)
                    geo=json.loads(raw)
                    if geo.get("type")!="FeatureCollection" or len(geo.get("features",[]))<100:
                        raise ValueError("Downloaded country boundary file failed validation")
                    p.parent.mkdir(parents=True,exist_ok=True)
                    tmp=p.with_suffix(".geojson.tmp");tmp.write_bytes(raw);tmp.replace(p)
                b=p.read_bytes();etag='"'+hashlib.sha1(b).hexdigest()[:16]+'"'
                if self.headers.get("If-None-Match")==etag:
                    self.send_response(304);self.send_header("ETag",etag);self.send_header("Cache-Control","public, max-age=604800");self.end_headers();return
                self.send_response(200);self.send_header("Content-Type","application/geo+json");self.send_header("Content-Length",str(len(b)));self.send_header("ETag",etag);self.send_header("Cache-Control","public, max-age=604800");self.end_headers();self.wfile.write(b);return
            except Exception as e:
                return self.sendj(503,{"error":"World overview unavailable: "+str(e),"hint":"Run python3 scripts/download_world_map.py from the project root while online. The downloader now validates and atomically installs the file."})
        if path.startswith("/api/region/"):
            try:return self.sendj(200,get_region(self.data,path.rsplit("/",1)[1]))
            except Exception as e:return self.sendj(404,{"error":str(e)})
        if path.startswith("/sync/"):
            rid=path.rsplit("/",1)[1]
            try:
                pkg=get_region(self.data,rid);tmp=Path(self.data)/(rid+".synapsepack");save_package(pkg,tmp);b=tmp.read_bytes();tmp.unlink(missing_ok=True)
                self.send_response(200);self.send_header("Content-Type","application/zip");self.send_header("Content-Length",str(len(b)));self.send_header("X-SHA256",hashlib.sha256(b).hexdigest());self.end_headers();self.wfile.write(b);return
            except Exception as e:return self.sendj(404,{"error":str(e)})
        if path=="/" or path=="/index.html":
            b=(Path(__file__).parent.parent/"ui"/"index.html").read_bytes();self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.send_header("Content-Length",str(len(b)));self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(b);return
        return self.sendj(404,{"error":"not found"})
    def do_POST(self):
        path=unquote(urlparse(self.path).path)
        try:
            n=int(self.headers.get("Content-Length","0"))
            if n>250_000_000:return self.sendj(413,{"error":"payload too large"})
            raw=self.rfile.read(n)
            if path=="/api/auth/signup":
                body=json.loads(raw);res=self.auth.signup(body.get("email"),body.get("password"),body.get("display_name"))
                return self.send_auth(res,201)
            if path=="/api/auth/login":
                body=json.loads(raw);res=self.auth.login(body.get("email"),body.get("password"),self.client_address[0])
                return self.send_auth(res)
            if path=="/api/auth/logout":
                s=self.auth.current(self.cookies().get("synapse_session"))
                if s and not hmac.compare_digest(self.headers.get("X-CSRF-Token",""),s["csrf"]):
                    return self.sendj(403,{"error":"CSRF validation failed."})
                self.auth.logout(self.cookies().get("synapse_session"))
                self.send_response(200);self.send_header("Set-Cookie","synapse_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0")
                self.send_header("Content-Type","application/json");self.end_headers();self.wfile.write(b'{"status":"logged_out"}');return
            if path=="/api/agents":
                body=json.loads(raw)
                if body.get("region_id"):pkg=get_region(self.data,body["region_id"])
                else:pkg={"manifest":{"name":str(body.get("location") or "No regional package installed")[:120],"source":"none"},"nodes":[],"edges":[],"places":[],"facilities":[]}
                return self.sendj(200,run_agents(pkg,body.get("incident",{}),body.get("context")))
            if path=="/api/route":
                body=json.loads(raw);pkg=get_region(self.data,body["region_id"])
                return self.sendj(200,shortest_path(pkg,float(body["start_lat"]),float(body["start_lon"]),float(body["end_lat"]),float(body["end_lon"]),body.get("closed_way_ids",[])))
            if path in ("/api/regions/install","/api/regions/install-batch","/api/regions/install-cancel","/api/activate") and not App.allow_install:
                return self.sendj(403,{"error":"Installing regional maps from the web page is disabled on this server. The site operator pre-installs maps once (see README_FIX_v17: scripts/prefetch_regions.py or SYNAPSE_PREFETCH). Set SYNAPSE_ALLOW_INSTALL=1 to enable."})
            if path=="/api/regions/install":
                r=install_one(json.loads(raw),self.data)
                return self.sendj(200,{"status":"installed","region_id":json.loads(raw).get("region_id"),"file":r.get("file"),"downloaded_bytes":r.get("downloaded_bytes"),"import_log":r.get("import_log")})
            if path=="/api/regions/install-batch":
                body=json.loads(raw)
                App.batch.start(body.get("items") or [],body.get("max_mb",300),bool(body.get("skip_installed",True)))
                return self.sendj(200,App.batch.status())
            if path=="/api/regions/install-cancel":
                App.batch.cancel();return self.sendj(200,App.batch.status())
            if path=="/api/activate":
                tmp=Path(self.data)/"incoming.synapsepack";tmp.write_bytes(raw)
                try:dest=activate_package(tmp,self.data)
                finally:tmp.unlink(missing_ok=True)
                return self.sendj(200,{"status":"activated","file":dest.name})
            return self.sendj(404,{"error":"not found"})
        except AuthError as e:return self.sendj(e.status,{"error":str(e)})
        except Exception as e:return self.sendj(400,{"error":str(e)})
App.allow_install=True;App.prefetch_scope="";App.persistent=False
def _truthy(v):return str(v).strip().lower() in ("1","true","yes","on")
def main():
    env=os.environ
    p=argparse.ArgumentParser()
    p.add_argument("--data",default=env.get("SYNAPSE_DATA","./data"))
    p.add_argument("--host",default=env.get("HOST") or ("0.0.0.0" if env.get("PORT") else "127.0.0.1"))
    p.add_argument("--port",type=int,default=int(env.get("PORT","8080")))
    p.add_argument("--prefetch",default=env.get("SYNAPSE_PREFETCH",""),help="all | IN,US | id:asia-india-western-zone  (downloaded once in the background)")
    p.add_argument("--prefetch-max-mb",type=int,default=int(env.get("SYNAPSE_PREFETCH_MAX_MB","300")))
    a=p.parse_args()
    Path(a.data).mkdir(parents=True,exist_ok=True);App.data=a.data
    # Installing from the web page is allowed on a local machine, but NOT on a public host unless the operator opts in:
    # otherwise any visitor could make the server download and process multi-hundred-MB map files.
    local=a.host in ("127.0.0.1","localhost","::1")
    App.allow_install=_truthy(env["SYNAPSE_ALLOW_INSTALL"]) if "SYNAPSE_ALLOW_INSTALL" in env else local
    App.persistent=_truthy(env.get("SYNAPSE_PERSISTENT","0"))
    App.prefetch_scope=a.prefetch
    # Auto-activate checksum-validated packages generated into ./regions.
    package_dir=Path("./regions")
    if package_dir.is_dir():
        for package_file in sorted(package_dir.glob("*.synapsepack")):
            try:
                activated=activate_package(package_file,a.data)
                print(f"Activated existing regional package: {activated.name}")
            except Exception as exc:
                print(f"Skipped invalid regional package {package_file.name}: {exc}")
    App.batch=BatchInstaller(a.data,on_item=lambda it:prefetch_mod.record(a.data,it))
    App.auth=AuthStore(Path(a.data)/"accounts.sqlite3")
    if a.prefetch:
        def _bg():
            try:
                items=prefetch_mod.plan(a.data,a.prefetch,a.prefetch_max_mb)
                print(f"[prefetch] scope={a.prefetch!r}: {len(items)} extract(s) still to download (already-installed ones are skipped).",flush=True)
                if items:App.batch.start(items,a.prefetch_max_mb,True)
            except Exception as exc:print("[prefetch] could not start:",exc,flush=True)
        threading.Thread(target=_bg,daemon=True).start()
    print(f"SYNAPSE EARTH server: http://{a.host}:{a.port}  (web installs {'enabled' if App.allow_install else 'disabled'})",flush=True)
    ThreadingHTTPServer((a.host,a.port),App).serve_forever()
if __name__=="__main__":main()
