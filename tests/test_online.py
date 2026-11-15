import unittest
from synapse import online
from synapse.online import classify, safe_zones, pick, dedupe, route_online, ip_location
from tests.test_engine import sample

class ClassifyTests(unittest.TestCase):
    def test_overpass_search_includes_healthcare_tagged_hospitals_and_clinics(self):
        q = online.overpass_query(21.17, 72.83, 25000, 8000)
        self.assertIn('["healthcare"~"^(hospital|clinic)$"]', q)
        self.assertIn('["amenity"~"^(hospital|clinic)$"]', q)

    def test_bus_stop_shelter_is_not_a_shelter(self):
        self.assertIsNone(classify({"highway": "bus_stop", "shelter": "yes"}))
        self.assertIsNone(classify({"amenity": "shelter", "shelter_type": "picnic_shelter"}))
        self.assertIsNone(classify({"amenity": "shelter", "public_transport": "platform"}))
    def test_real_shelters(self):
        self.assertEqual(classify({"emergency": "assembly_point"}), "shelter")
        self.assertEqual(classify({"amenity": "evacuation_centre"}), "shelter")
        self.assertEqual(classify({"amenity": "shelter", "shelter_type": "disaster_shelter"}), "shelter")
    def test_other_tiers(self):
        self.assertEqual(classify({"amenity": "hospital"}), "medical")
        self.assertEqual(classify({"amenity": "community_centre"}), "refuge")
        self.assertIsNone(classify({"amenity": "cafe"}))

OVERPASS={"elements":[
 {"type":"node","id":1,"lat":0.004,"lon":0.004,"tags":{"emergency":"assembly_point","name":"Park Assembly"}},
 {"type":"way","id":2,"center":{"lat":0.02,"lon":0.0},"tags":{"amenity":"hospital","name":"General Hospital"}},
 {"type":"node","id":3,"lat":0.001,"lon":0.001,"tags":{"amenity":"shelter","highway":"bus_stop"}},
]}
def fake_fetch(url, data=None, timeout=0, headers=None):
    if "overpass" in url: return OVERPASS
    if "open-meteo" in url: return {"elevation":[10, 40, 5]}      # user, first, second candidate
    if "routing.openstreetmap.de" in url or "osrm" in url:
        return {"code":"Ok","routes":[{"distance":900,"duration":700,"geometry":{"coordinates":[[0,0],[0.004,0.004]]},
                "legs":[{"steps":[{"name":"Main St","distance":900,"maneuver":{"type":"turn","modifier":"left"}},{"name":"","distance":0,"maneuver":{"type":"arrive"}}]}]}]}
    if "nominatim" in url: return []
    raise AssertionError(url)
def broken_fetch(*a, **k): raise OSError("offline")

class OrchestrationTests(unittest.TestCase):
    def test_online_path(self):
        r=safe_zones([], 0, 0, "Flood", "foot", fetch=fake_fetch)
        self.assertEqual(r["status"], "OK"); self.assertTrue(r["sources"]["online_data"])
        names=[d["name"] for d in r["destinations"]]
        self.assertIn("Park Assembly", names); self.assertIn("General Hospital", names)
        self.assertEqual(len(names), 2)                              # bus stop rejected
        d=r["destinations"][0]
        self.assertEqual(d["route"]["status"], "CANDIDATE_ROUTE"); self.assertEqual(d["tier"], "shelter")
        self.assertEqual(r["user_elevation_m"], 10)
        self.assertTrue(any("higher ground" in n for n in d["notes"]))
        self.assertIn("NOT verified", d["verification"])
    def test_overpass_down_falls_back_to_nominatim(self):
        def f(url, data=None, timeout=0, headers=None):
            if "overpass" in url: raise OSError("504")
            if "nominatim" in url:
                if "hospital" in url: return [{"osm_type":"node","osm_id":7,"lat":"0.01","lon":"0.01","name":"Fallback Hospital","category":"amenity","type":"hospital"},
                                                 {"osm_type":"node","osm_id":8,"lat":"0.0","lon":"0.0","name":"Random cafe","category":"amenity","type":"cafe"}]
                return []
            if "open-meteo" in url: return {"elevation":[1,2]}
            return {"code":"Ok","routes":[{"distance":500,"duration":400,"geometry":{"coordinates":[[0,0],[0.01,0.01]]},"legs":[]}]}
        r=safe_zones([], 0, 0, "Wildfire", "foot", fetch=f)
        self.assertEqual(r["status"],"OK"); self.assertEqual([d["name"] for d in r["destinations"]],["Fallback Hospital"])
    def test_everything_offline_never_invents(self):
        r=safe_zones([], 0, 0, "Flood", "foot", fetch=broken_fetch)
        self.assertEqual(r["status"], "NO_MAPPED_SAFE_ZONES"); self.assertEqual(r["destinations"], [])
    def test_offline_package_routes_without_network(self):
        pkg=sample(); pkg["facilities"]=[{"id":"9","name":"Hall","type":"assembly_point","emergency":"assembly_point","lat":0.01,"lon":0.01,"amenity":"","healthcare":"","shelter":""}]
        r=safe_zones([(pkg,{"region_id":"test"})], 0, 0, "Earthquake", "foot", fetch=broken_fetch)
        self.assertEqual(r["status"], "OK"); d=r["destinations"][0]
        self.assertEqual(d["route"]["source"], "installed offline road graph")
    def test_routing_failure_degrades_to_straight_line(self):
        def f(url, data=None, timeout=0, headers=None):
            if "overpass" in url: return OVERPASS
            raise OSError("no routing")
        r=safe_zones([], 0, 0, "Wildfire", "foot", fetch=f)
        self.assertTrue(all(d["route"]["status"]=="STRAIGHT_LINE_ONLY" for d in r["destinations"]))
        self.assertIn("bearing", r["destinations"][0]["route"])
    def test_offline_snap_failure_is_explained_in_fallback(self):
        pkg=sample()
        candidate={"lat":1.0,"lon":1.0,"_pkg":pkg}
        route=online.route_one(candidate,0,0,"foot",fetch=broken_fetch,allow_online=False)
        self.assertEqual(route["status"],"STRAIGHT_LINE_ONLY")
        self.assertIn("too far from the installed road graph",route["warning"])
    def test_flood_penalises_lower_ground(self):
        c=[{"id":"a","tier":"shelter","straight_line_m":1000,"lat":0,"lon":0,"source":"x"},{"id":"b","tier":"shelter","straight_line_m":1200,"lat":0,"lon":0,"source":"x"}]
        out=pick(c,"Flood",user_elev=20,elev={"a":5,"b":60})
        self.assertEqual(out[0]["id"],"b")
    def test_pick_keeps_all_candidates_instead_of_category_quotas(self):
        c=[{"id":str(i),"tier":"shelter","straight_line_m":100+i,"lat":0,"lon":0,"source":"x"} for i in range(7)]
        c += [{"id":"hospital","tier":"medical","straight_line_m":80,"lat":0,"lon":0,"source":"x"}]
        out=pick(c,"Earthquake")
        self.assertEqual(len(out),8)
        self.assertEqual({x["id"] for x in out},{str(i) for i in range(7)}|{"hospital"})
    def test_ip_location_and_failure(self):
        ok=ip_location(lambda u,**k:{"success":True,"latitude":18.5,"longitude":73.8,"city":"Pune","region":"MH","country":"India","country_code":"in"})
        self.assertEqual(ok["status"],"APPROXIMATE_IP_LOCATION"); self.assertEqual(ok["country_code"],"IN")
        self.assertEqual(ip_location(broken_fetch)["status"],"IP_LOCATION_UNAVAILABLE")
    def test_emergency_number(self):
        self.assertEqual(online.emergency_number("in"),"112"); self.assertIn("112",online.emergency_number("zz"))
if __name__=="__main__": unittest.main()
