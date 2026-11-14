"""Build an offline road/place/facility package from a Geofabrik OSM PBF.
Requires pyosmium. For large country extracts, use a state/province extract or bbox-filtered PBF.
"""
import argparse, datetime, json, re
from pathlib import Path
from .engine import save_package, haversine, SCHEMA

HIGHWAYS={"motorway","trunk","primary","secondary","tertiary","unclassified","residential","living_street","service","road","motorway_link","trunk_link","primary_link","secondary_link","tertiary_link"}
FACILITY_KEYS={"amenity","healthcare","emergency","shelter"}
def slug(s): return re.sub(r"[^a-z0-9]+","-",s.lower()).strip("-")[:60] or "region"
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--pbf",required=True,help="Path to downloaded .osm.pbf extract")
    ap.add_argument("--name",required=True);ap.add_argument("--country-code",default="XX")
    ap.add_argument("--region-id",default="");ap.add_argument("--out",default="./regions")
    ap.add_argument("--bbox",default="",help="Optional min_lon,min_lat,max_lon,max_lat")
    a=ap.parse_args()
    try: import osmium
    except ImportError: raise SystemExit("Install pyosmium: python3 -m pip install osmium")
    bbox=tuple(map(float,a.bbox.split(","))) if a.bbox else None
    if bbox and (len(bbox)!=4 or bbox[0]>=bbox[2] or bbox[1]>=bbox[3]):raise SystemExit("Invalid bbox")
    nodes={};edges=[];places=[];facilities=[]
    class Handler(osmium.SimpleHandler):
        def way(self,w):
            hw=w.tags.get("highway")
            if hw not in HIGHWAYS:return
            if w.tags.get("access") in ("no","private") or w.tags.get("motor_vehicle")=="no":return
            coords=[]
            try:
                for n in w.nodes:
                    if not n.location.valid():continue
                    lon,lat=n.location.lon,n.location.lat
                    if bbox and not (bbox[0]<=lon<=bbox[2] and bbox[1]<=lat<=bbox[3]):continue
                    nid=str(n.ref);nodes[nid]={"id":nid,"lat":lat,"lon":lon};coords.append(nid)
            except Exception:return
            oneway=w.tags.get("oneway") in ("yes","1","true")
            for u,v in zip(coords,coords[1:]):
                nu,nv=nodes[u],nodes[v]
                d=haversine(nu,nv)
                if d>0:edges.append({"from":u,"to":v,"distance_m":round(d,2),"oneway":oneway,"way_id":str(w.id),"name":w.tags.get("name",""),"highway":hw})
    class NodeHandler(osmium.SimpleHandler):
        def node(self,n):
            if not n.location.valid():return
            lon,lat=n.location.lon,n.location.lat
            if bbox and not (bbox[0]<=lon<=bbox[2] and bbox[1]<=lat<=bbox[3]):return
            t=n.tags
            place=t.get("place")
            if place in ("city","town","village","hamlet","isolated_dwelling","suburb","neighbourhood"):
                places.append({"id":str(n.id),"name":t.get("name", "Unnamed place"),"place_type":place,"lat":lat,"lon":lon,"name_local":t.get("name:local","")})
            kind=next((t.get(k) for k in FACILITY_KEYS if t.get(k)),None)
            if kind:
                facilities.append({"id":str(n.id),"name":t.get("name","Unnamed facility"),"type":kind,
                    "lat":lat,"lon":lon,"emergency":t.get("emergency",""),"shelter":t.get("shelter",""),
                    "amenity":t.get("amenity",""),"healthcare":t.get("healthcare",""),
                    "social_facility":t.get("social_facility","")})
    print("Reading road network…")
    Handler().apply_file(a.pbf,locations=True)
    print("Reading settlements and facilities…")
    NodeHandler().apply_file(a.pbf,locations=True)
    # keep only nodes participating in a road segment
    used={e["from"] for e in edges}|{e["to"] for e in edges}
    nodes=[v for k,v in nodes.items() if k in used]
    rid=a.region_id or slug(a.name)+"-"+a.country_code.lower()
    if bbox:
        package_bbox=list(bbox)
    elif nodes:
        package_bbox=[min(n["lon"] for n in nodes),min(n["lat"] for n in nodes),max(n["lon"] for n in nodes),max(n["lat"] for n in nodes)]
    else:
        raise SystemExit("No road nodes were imported; check the PBF extract and bounding box.")
    pkg={"manifest":{"schema":SCHEMA,"region_id":rid,"name":a.name,"country_code":a.country_code.upper(),"generated_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"source":"OpenStreetMap via user-supplied Geofabrik PBF","license":"ODbL-1.0","bbox":package_bbox,"road_nodes":len(nodes),"road_segments":len(edges),"places":len(places),"facilities":len(facilities),"limitations":["OSM completeness varies by location","Only selected highway classes are imported","Turn restrictions and complex access/bridge/tunnel semantics are not fully modelled","Facility operational status is not verified","Hazard overlays are not included"]},
         "nodes":nodes,"edges":edges,"places":places,"facilities":facilities}
    Path(a.out).mkdir(parents=True,exist_ok=True);out=Path(a.out)/(rid+".synapsepack")
    digest=save_package(pkg,out)
    print(json.dumps({"package":str(out),"sha256":digest,"nodes":len(nodes),"edges":len(edges),"places":len(places),"facilities":len(facilities)},indent=2))
if __name__=="__main__":main()
