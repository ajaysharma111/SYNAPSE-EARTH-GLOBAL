from pathlib import Path
from urllib.request import Request, urlopen
import json, hashlib, sys

URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_admin_0_countries.geojson"
ROOT = Path(__file__).resolve().parent.parent
out = ROOT / "data" / "world_countries.geojson"
tmp = out.with_suffix(".geojson.download")

def main():
    out.parent.mkdir(parents=True, exist_ok=True)
    print("SYNAPSE EARTH: downloading world country boundaries…", flush=True)
    req = Request(URL, headers={"User-Agent": "SYNAPSE-EARTH/1.0 world-map-installer"})
    try:
        with urlopen(req, timeout=120) as response, tmp.open("wb") as f:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk: break
                f.write(chunk)
                print(f"Downloaded {f.tell()/1024:.0f} KB", end="\\r", flush=True)
        raw = tmp.read_bytes()
        geo = json.loads(raw)
        if geo.get("type") != "FeatureCollection" or len(geo.get("features", [])) < 100:
            raise ValueError("The downloaded file is not a valid world country FeatureCollection.")
        tmp.replace(out)
        print(f"\\nSUCCESS: installed {len(geo['features'])} country features.")
        print(f"File: {out}")
        print(f"Size: {out.stat().st_size:,} bytes")
        print(f"SHA256: {hashlib.sha256(out.read_bytes()).hexdigest()}")
        print("Note: this is a country-boundary overview, not street or road data.")
    except Exception as e:
        try: tmp.unlink(missing_ok=True)
        except Exception: pass
        print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
        print("Check internet access, then run this command again.", file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__": main()
