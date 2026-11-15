import json, math, heapq, zipfile, io, hashlib, time
from pathlib import Path

SCHEMA="synapse-region-v1"
def haversine(a,b):
    r=6371000
    p1,p2=math.radians(a["lat"]),math.radians(b["lat"])
    dp=math.radians(b["lat"]-a["lat"]); dl=math.radians(b["lon"]-a["lon"])
    x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(x))
def validate(pkg):
    m=pkg.get("manifest",{})
    if m.get("schema")!=SCHEMA: raise ValueError("Unsupported region package schema")
    nodes=pkg.get("nodes",[]); edges=pkg.get("edges",[])
    ids={n["id"] for n in nodes}
    if len(ids)!=len(nodes): raise ValueError("Duplicate node IDs")
    for n in nodes:
        if not (-90<=float(n["lat"])<=90 and -180<=float(n["lon"])<=180): raise ValueError("Invalid coordinates")
    for e in edges:
        if e["from"] not in ids or e["to"] not in ids: raise ValueError("Edge references missing node")
        if float(e["distance_m"])<0: raise ValueError("Negative edge distance")
    return pkg
def save_package(pkg,path):
    validate(pkg); raw=json.dumps(pkg,separators=(",",":"),ensure_ascii=False).encode()
    digest=hashlib.sha256(raw).hexdigest()
    with zipfile.ZipFile(path,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("region.json",raw);z.writestr("SHA256",digest)
    return digest
def load_package(path):
    with zipfile.ZipFile(path) as z:
        raw=z.read("region.json"); expected=z.read("SHA256").decode().strip()
    if hashlib.sha256(raw).hexdigest()!=expected: raise ValueError("Package checksum mismatch")
    return validate(json.loads(raw))
def activate_package(path,data_dir):
    pkg=load_package(path); dest=Path(data_dir);dest.mkdir(parents=True,exist_ok=True)
    target=dest/(pkg["manifest"]["region_id"]+".json")
    tmp=target.with_suffix(".tmp");tmp.write_text(json.dumps(pkg,ensure_ascii=False));tmp.replace(target)
    return target
_SKIP={"world_countries.geojson","global_region_catalog.json"}
_CACHE={}
def _load_checked(path):
    st=path.stat(); key=str(path); hit=_CACHE.get(key)
    if hit and hit[0]==st.st_mtime_ns: return hit[1]
    pkg=validate(json.loads(path.read_text()))
    if len(_CACHE)>=3: _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key]=(st.st_mtime_ns,pkg); return pkg
def load_regions(data_dir):
    """List installed packages from small .manifest sidecars (created on first sight), not by parsing every package."""
    out=[]
    for p in Path(data_dir).glob("*.json"):
        if p.name in _SKIP: continue
        mp=p.with_suffix(".manifest")
        try:
            if mp.exists() and mp.stat().st_mtime_ns>=p.stat().st_mtime_ns: m=json.loads(mp.read_text())
            else:
                m=json.loads(p.read_text())["manifest"];mp.write_text(json.dumps(m))
            out.append({**m,"nodes_count":p.stat().st_size})
        except Exception: pass
    return sorted(out,key=lambda x:x.get("name",""))
def get_region(data_dir,rid):
    d=Path(data_dir);direct=d/(str(rid)+".json")
    if direct.is_file() and direct.name not in _SKIP:
        try:
            pkg=_load_checked(direct)
            if pkg["manifest"]["region_id"]==rid:return pkg
        except Exception: pass
    for p in d.glob("*.json"):
        if p.name in _SKIP: continue
        try:
            pkg=_load_checked(p)
            if pkg["manifest"]["region_id"]==rid:return pkg
        except Exception: continue
    raise FileNotFoundError(rid)
# Small bounded caches keep repeated shelter-route requests fast without
# retaining every regional graph indefinitely.
_GRAPH_CACHE={}
_SNAP_CACHE={}

def _graph_for(pkg):
    """Build adjacency once per loaded package; reuse it for subsequent routes."""
    key=id(pkg)
    hit=_GRAPH_CACHE.get(key)
    if hit is not None and hit[0] is pkg:
        return hit[1],hit[2]
    nodes={n["id"]:n for n in pkg["nodes"]}
    adj={}
    for e in pkg["edges"]:
        a,b=e["from"],e["to"]
        w=float(e["distance_m"])
        adj.setdefault(a,[]).append((b,w,e))
        if not e.get("oneway",False):
            adj.setdefault(b,[]).append((a,w,e))
    if len(_GRAPH_CACHE)>=3:
        _GRAPH_CACHE.pop(next(iter(_GRAPH_CACHE)))
    _GRAPH_CACHE[key]=(pkg,adj,nodes)
    return adj,nodes

_SPATIAL_CACHE={}
_SPATIAL_CELL_DEG=0.01

def _spatial_index(pkg):
    """Build a small geographic grid once so nearest-road-node lookup avoids scanning every node."""
    key=id(pkg)
    hit=_SPATIAL_CACHE.get(key)
    if hit is not None and hit[0] is pkg:return hit[1]
    cell=_SPATIAL_CELL_DEG; grid={}
    for node in pkg["nodes"]:
        cell_key=(math.floor(float(node["lat"])/cell),math.floor(float(node["lon"])/cell))
        grid.setdefault(cell_key,[]).append(node)
    index={"grid":grid,"cell":cell}
    if len(_SPATIAL_CACHE)>=3:_SPATIAL_CACHE.pop(next(iter(_SPATIAL_CACHE)))
    _SPATIAL_CACHE[key]=(pkg,index)
    return index

def nearest_node(pkg,lat,lon):
    lat,lon=float(lat),float(lon)
    key=(id(pkg),lat,lon)
    hit=_SNAP_CACHE.get(key)
    if hit is not None and hit[0] is pkg:return hit[1],hit[2]
    if not pkg["nodes"]:raise ValueError("This region has no routable road nodes")
    index=_spatial_index(pkg);grid=index["grid"];cell=index["cell"]
    row,col=math.floor(lat/cell),math.floor(lon/cell)
    best=None;bd=float("inf");point={"lat":lat,"lon":lon}
    max_ring=max((abs(k[0]-row)+abs(k[1]-col) for k in grid),default=0)
    # Visit the closest grid cells first. Once the unvisited rectangle is
    # farther away than the best exact haversine distance, no unseen node
    # can improve the answer.
    for ring in range(max_ring+1):
        for dr in range(-ring,ring+1):
            dc=ring-abs(dr)
            cols=(col,) if dc==0 else (col-dc,col+dc)
            for cc in cols:
                for node in grid.get((row+dr,cc),()):
                    d=haversine(point,node)
                    if d<bd:best,bd=node,d
        south=(row-ring)*cell;north=(row+ring+1)*cell
        west=(col-ring)*cell;east=(col+ring+1)*cell
        dy=max(south-lat,0.0,lat-north)*111195.0
        # cos(latitude)<=1 makes this longitude bound conservative.
        dx=max(west-lon,0.0,lon-east)*111195.0
        if best is not None and math.hypot(dx,dy)>bd:break
    if best is None:raise ValueError("This region has no routable road nodes")
    if len(_SNAP_CACHE)>=256:_SNAP_CACHE.pop(next(iter(_SNAP_CACHE)))
    _SNAP_CACHE[key]=(pkg,best,bd)
    return best,bd

def shortest_path(pkg,start_lat,start_lon,end_lat,end_lon,closed_way_ids=None):
    if not pkg["nodes"] or not pkg["edges"]:
        return {"status":"NO_ROAD_DATA","message":"No road graph is installed for this region."}
    # Reject invalid coordinates before snapping them to the graph.
    try:
        start_lat,start_lon=float(start_lat),float(start_lon)
        end_lat,end_lon=float(end_lat),float(end_lon)
    except (TypeError,ValueError):
        return {"status":"INVALID_COORDINATES","message":"Start and destination must be valid latitude/longitude values."}
    if not (-90<=start_lat<=90 and -180<=start_lon<=180 and
            -90<=end_lat<=90 and -180<=end_lon<=180):
        return {"status":"INVALID_COORDINATES","message":"Latitude must be between -90 and 90 and longitude between -180 and 180."}
    start,sd=nearest_node(pkg,start_lat,start_lon)
    end,ed=nearest_node(pkg,end_lat,end_lon)
    # A route is not meaningful when either endpoint is snapped far away from
    # the installed graph. Keep the distances in the response for diagnostics.
    max_snap_m=1500
    if sd>max_snap_m or ed>max_snap_m:
        return {"status":"SNAP_TOO_FAR","snap_start_m":round(sd),"snap_end_m":round(ed),
                "max_snap_m":max_snap_m,
                "message":"A start or destination point is too far from the installed road graph. No offline road route was returned."}
    # If both endpoints collapse onto one graph node, do not report a zero-metre
    # road route for two distinct real-world locations.
    if start["id"]==end["id"] and haversine({"lat":start_lat,"lon":start_lon},{"lat":end_lat,"lon":end_lon})>25:
        return {"status":"SAME_NODE_SNAP","snap_start_m":round(sd),"snap_end_m":round(ed),
                "message":"Both endpoints snap to the same road node but are distinct locations. The installed graph cannot provide a meaningful route between them."}
    adj,nodes=_graph_for(pkg)
    closed=set(str(x) for x in (closed_way_ids or []))

    # A* uses straight-line distance as an admissible lower-bound heuristic.
    # OSM edge lengths are physical road distances, so this never overestimates
    # the remaining path length and preserves shortest-path correctness.
    def heuristic(node_id):
        return haversine(nodes[node_id],end)

    q=[(heuristic(start["id"]),0.0,start["id"])]
    dist={start["id"]:0.0};prev={}
    while q:
        _,d,u=heapq.heappop(q)
        if d!=dist.get(u):
            continue
        if u==end["id"]:
            break
        for v,w,e in adj.get(u,()):
            if str(e.get("way_id","")) in closed:
                continue
            nd=d+w
            if nd<dist.get(v,float("inf")):
                dist[v]=nd;prev[v]=(u,e)
                heapq.heappush(q,(nd+heuristic(v),nd,v))
    if end["id"] not in dist:
        return {"status":"NO_CONNECTED_ROUTE","message":"No connected route exists in the installed graph. No route was invented."}
    ids=[end["id"]];ways=[];cur=end["id"]
    while cur!=start["id"]:
        cur0,e=prev[cur];ways.append(e);cur=cur0;ids.append(cur)
    ids.reverse();ways.reverse()
    return {"status":"CANDIDATE_ROUTE","distance_m":round(dist[end["id"]]),"snap_start_m":round(sd),"snap_end_m":round(ed),
            "node_ids":ids,"coordinates":[[nodes[i]["lon"],nodes[i]["lat"]] for i in ids],
            "road_names":list(dict.fromkeys(e.get("name","unnamed road") for e in ways))[:20],
            "warning":"Candidate route only. Road closures, hazard exposure, access restrictions and emergency authority approval must be verified."}

def run_agents(pkg,incident,context=None):
    m=pkg["manifest"];nodes=len(pkg["nodes"]);edges=len(pkg["edges"]);places=pkg.get("places",[]);fac=pkg.get("facilities",[])
    severity=max(1,min(5,int(incident.get("severity",3))))
    kind=str(incident.get("type","Unknown"))
    cov={"agent":"Coverage Agent","status":"complete","region":m.get("name"),"source":m.get("source"),"updated":m.get("generated_at"),"road_nodes":nodes,"road_segments":edges,"place_records":len(places),"coverage":"ROAD_GRAPH_AVAILABLE" if edges else "NO_ROAD_GRAPH","limitations":m.get("limitations",[])}
    haz={"agent":"Hazard Agent","status":"complete","scenario":kind,"severity":severity,"method":"Operator-provided scenario; offline mode does not claim live hazard detection","assumptions":["No live weather, seismic, fire perimeter or flood sensor feed is assumed","Severity is an operator input, not a measured probability"]}
    infra={"agent":"Infrastructure Agent","status":"complete","facility_records":len(fac),"facility_types":dict((k,sum(1 for f in fac if f.get("type")==k)) for k in sorted(set(f.get("type","unknown") for f in fac))),"verification":"OSM mapped objects are not confirmation of operational status, capacity or safety"}
    route={"agent":"Route Agent","status":"not_run","reason":"Start and destination coordinates required; graph availability alone does not imply a safe route"}
    ctx=context if isinstance(context,dict) else {}
    zones=[z for z in (ctx.get("safe_zones") or []) if isinstance(z,dict)][:5]
    if zones:
        route={"agent":"Route Agent","status":"complete","candidates":[{"name":str(z.get("name"))[:80],"type":z.get("tier_label"),"route_km":round((z.get("distance_m") or 0)/1000,2),"route_source":z.get("route_source")} for z in zones],"reason":"Candidate routes only; hazard exposure and closures are not modelled"}
    coord={"agent":"Response Coordinator","status":"complete","actions":["Confirm incident location and time with local authorities","Check current road closures, bridges, underpasses and hazard perimeter","Verify shelters, hospitals and facility capacity","Use only candidate routes reviewed by a trained human","Record decisions and source timestamps"],"human_approval_required":True}
    return {"agents":[cov,haz,infra,route,coord],"summary":{"decision_support_only":True,"human_approval_required":True,"route_safety_certified":False}}
