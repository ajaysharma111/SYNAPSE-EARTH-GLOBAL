"""Download a Geofabrik PBF extract. Use an official country or subdivision URL."""
import argparse,urllib.request,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument("--url",required=True);p.add_argument("--out",default="./downloads");a=p.parse_args()
if not a.url.startswith("https://download.geofabrik.de/") or not a.url.endswith(".osm.pbf"):
    raise SystemExit("Use an HTTPS .osm.pbf URL from https://download.geofabrik.de/")
Path(a.out).mkdir(parents=True,exist_ok=True);dest=Path(a.out)/a.url.rsplit("/",1)[-1]
req=urllib.request.Request(a.url,headers={"User-Agent":"SYNAPSE-EARTH/4.0"})
h=hashlib.sha256();total=0
with urllib.request.urlopen(req,timeout=120) as r,dest.open("wb") as f:
    while True:
        b=r.read(1024*1024)
        if not b:break
        f.write(b);h.update(b);total+=len(b)
print("Downloaded",dest,"bytes",total,"sha256",h.hexdigest())
