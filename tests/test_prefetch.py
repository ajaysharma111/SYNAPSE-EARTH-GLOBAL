import json, tempfile, threading, time, unittest, urllib.request, urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from synapse import catalog, prefetch
from synapse.server import App
from synapse.installer import BatchInstaller
from synapse.engine import save_package, activate_package
from tests.test_engine import sample

def feat(path, name, cc=None, parent=None, box=(0, 0, 1, 1)):
    p = {"name": name, "urls": {"pbf": "https://download.geofabrik.de/%s-latest.osm.pbf" % path}}
    if cc: p["iso3166-1:alpha2"] = [cc]
    if parent: p["parent"] = parent
    x0, y0, x1, y1 = box
    return {"properties": p, "geometry": {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}}
INDEX = {"features": [feat("asia", "Asia"), feat("asia/india", "India", "IN", "asia"), feat("asia/india/west", "West Zone", None, "india"),
                      feat("asia/india/south", "South Zone", None, "india"), feat("europe/monaco", "Monaco", "MC", "europe")]}

class CatalogTests(unittest.TestCase):
    def test_catalog_cached_not_redownloaded(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []
            fetch = lambda: calls.append(1) or INDEX
            c1 = catalog.get_catalog(d, fetch=fetch); c2 = catalog.get_catalog(d, fetch=fetch); c3 = catalog.get_catalog(d, fetch=fetch)
            self.assertEqual(len(calls), 1); self.assertTrue(c3["cached"])
            india = [r for r in c1["regions"] if r["id"] == "asia-india-west"][0]
            self.assertEqual(india["country"], "IN"); self.assertTrue(india["leaf"])      # code inherited, list normalised
            self.assertFalse([r for r in c1["regions"] if r["id"] == "asia-india"][0]["leaf"])
    def test_stale_cache_refreshes_but_survives_offline(self):
        with tempfile.TemporaryDirectory() as d:
            catalog.get_catalog(d, fetch=lambda: INDEX)
            def down(): raise OSError("offline")
            c = catalog.get_catalog(d, max_age_s=-1, fetch=down)       # stale + offline -> serve cache
            self.assertTrue(c["cached"]); self.assertEqual(c["count"], 5)

class PrefetchTests(unittest.TestCase):
    def test_select_country_skips_installed_and_recent_failures(self):
        with tempfile.TemporaryDirectory() as d:
            cat = catalog.get_catalog(d, fetch=lambda: INDEX)
            self.assertEqual({i["region_id"] for i in prefetch.select(cat, "IN", d, 300)}, {"asia-india-west", "asia-india-south"})
            (Path(d) / "asia-india-west.json").write_text("{}")                       # already installed
            prefetch.record(d, {"region_id": "asia-india-south", "name": "South Zone", "status": "failed", "message": "x"})
            self.assertEqual(prefetch.select(cat, "IN", d, 300), [])
            self.assertEqual({i["region_id"] for i in prefetch.select(cat, "all", d, 300)}, {"europe-monaco"})
            self.assertEqual([i["region_id"] for i in prefetch.select(cat, "id:europe-monaco", d, 300)], ["europe-monaco"])

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(); d = cls.tmp.name
        pkg = sample(); pkg["manifest"].update({"region_id": "t1", "bbox": [-1, -1, 1, 1]})
        save_package(pkg, Path(d) / "t1.synapsepack"); activate_package(Path(d) / "t1.synapsepack", d)
        App.data = d; App.allow_install = False; App.prefetch_scope = "IN"; App.persistent = False; App.batch = BatchInstaller(d)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), App); cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
    @classmethod
    def tearDownClass(cls): cls.srv.shutdown(); cls.tmp.cleanup()
    def get(self, path): return json.loads(urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, path)).read())
    def test_public_host_blocks_web_installs(self):
        self.assertFalse(self.get("/api/config")["allow_install"])
        req = urllib.request.Request("http://127.0.0.1:%d/api/regions/install-batch" % self.port, data=b'{"items":[]}', method="POST")
        with self.assertRaises(urllib.error.HTTPError) as cm: urllib.request.urlopen(req)
        self.assertEqual(cm.exception.code, 403)
    def test_light_region_endpoints(self):
        info = self.get("/api/region-info/t1"); self.assertGreater(info["counts"]["edges"], 0)
        r = self.get("/api/region-roads/t1?bbox=-1,-1,1,1"); self.assertTrue(r["lines"]); self.assertEqual(len(r["lines"][0]), 4)
        self.assertEqual(self.get("/api/region-roads/t1?bbox=50,50,51,51")["lines"], [])
        resp = urllib.request.urlopen("http://127.0.0.1:%d/api/region-roads/t1?bbox=-1,-1,1,1" % self.port)
        self.assertIn("max-age", resp.headers["Cache-Control"])
if __name__ == "__main__": unittest.main()

class WideSearchTests(unittest.TestCase):
    def test_offline_radius_widens(self):
        from synapse import online
        pkg = {"manifest": {"bbox": [-1, -1, 1, 1], "region_id": "r"}, "facilities": [{"id": 1, "lat": 0.5, "lon": 0.0, "name": "Far Camp", "type": "shelter", "tags": {"amenity": "shelter"}}]}
        near = online.offline_candidates([(pkg, {"region_id": "r"})], 0.0, 0.0, 30000)
        wide = online.offline_candidates([(pkg, {"region_id": "r"})], 0.0, 0.0, 120000)
        self.assertEqual(len(near), 0); self.assertEqual(len(wide), 1)
