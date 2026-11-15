import tempfile,unittest
from pathlib import Path
from synapse.engine import *
def sample():
 return {"manifest":{"schema":SCHEMA,"region_id":"test","name":"Test region","country_code":"ZZ","generated_at":"test","source":"synthetic test","bbox":[-0.1,-0.1,0.1,0.1]},
 "nodes":[{"id":"a","lat":0,"lon":0},{"id":"b","lat":0,"lon":0.01},{"id":"c","lat":0.01,"lon":0.01}],
 "edges":[{"from":"a","to":"b","distance_m":1112,"oneway":False,"way_id":"1","name":"A street"},{"from":"b","to":"c","distance_m":1112,"oneway":False,"way_id":"2","name":"B street"}],
 "places":[{"id":"p","name":"Village","place_type":"village","lat":0,"lon":0}],
 "facilities":[]}
class EngineTests(unittest.TestCase):
 def test_package_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x.synapsepack";save_package(sample(),p);self.assertEqual(load_package(p)["manifest"]["region_id"],"test")
 def test_route(self):
  r=shortest_path(sample(),0,0,0.01,0.01);self.assertEqual(r["status"],"CANDIDATE_ROUTE");self.assertEqual(len(r["coordinates"]),3)
 def test_dijkstra_uses_stored_road_distance_not_geographic_heuristic(self):
  p=sample()
  # Deliberately include a direct edge whose stored cost is higher than the
  # two-segment alternative; the returned route must minimise edge weights.
  p["edges"].append({"from":"a","to":"c","distance_m":4000,"oneway":False,"way_id":"3","name":"Long bypass"})
  r=shortest_path(p,0,0,0.01,0.01)
  self.assertEqual(r["status"],"CANDIDATE_ROUTE")
  self.assertEqual(r["distance_m"],2224)
  self.assertEqual(r["road_names"],["A street","B street"])
 def test_route_respects_closed_way(self):
  p=sample();r=shortest_path(p,0,0,0.01,0.01,closed_way_ids=["2"])
  self.assertEqual(r["status"],"NO_CONNECTED_ROUTE")
 def test_graph_cache_reused(self):
  import synapse.engine as engine
  p=sample();a=engine._graph_for(p);b=engine._graph_for(p)
  self.assertIs(a[0],b[0]);self.assertIs(a[1],b[1])
 def test_spatial_nearest_node_matches_full_scan(self):
  import synapse.engine as engine
  p=sample()
  for lat,lon in [(0.0001,0.0002),(0.004,0.009),(0.009,0.009)]:
   actual,distance=engine.nearest_node(p,lat,lon)
   expected=min(p["nodes"],key=lambda n:engine.haversine({"lat":lat,"lon":lon},n))
   self.assertEqual(actual["id"],expected["id"])
   self.assertAlmostEqual(distance,engine.haversine({"lat":lat,"lon":lon},expected),places=6)
 def test_spatial_index_reused(self):
  import synapse.engine as engine
  p=sample();a=engine._spatial_index(p);b=engine._spatial_index(p)
  self.assertIs(a,b)
 def test_spatial_lookup_far_outside_region_terminates_and_is_exact(self):
  import synapse.engine as engine
  p=sample()
  actual,distance=engine.nearest_node(p,45,90)
  expected=min(p["nodes"],key=lambda n:engine.haversine({"lat":45,"lon":90},n))
  self.assertEqual(actual["id"],expected["id"])
  self.assertAlmostEqual(distance,engine.haversine({"lat":45,"lon":90},expected),places=6)
 def test_missing_route(self):
  p=sample();p["edges"]=[];self.assertEqual(shortest_path(p,0,0,0,0.01)["status"],"NO_ROAD_DATA")
 def test_route_rejects_invalid_coordinates(self):
  p=sample()
  self.assertEqual(shortest_path(p,91,0,0,0.01)["status"],"INVALID_COORDINATES")
  self.assertEqual(shortest_path(p,0,"not-a-number",0,0.01)["status"],"INVALID_COORDINATES")
 def test_route_rejects_points_far_from_installed_graph(self):
  p=sample()
  r=shortest_path(p,0,0,1,1)
  self.assertEqual(r["status"],"SNAP_TOO_FAR")
  self.assertGreater(r["snap_end_m"],r["max_snap_m"])
 def test_route_rejects_distinct_points_collapsed_to_same_node(self):
  p=sample()
  r=shortest_path(p,0,0,0,0.0003)
  self.assertEqual(r["status"],"SAME_NODE_SNAP")
 def test_agents(self):
  a=run_agents(sample(),{"type":"Flood","severity":4});self.assertEqual(len(a["agents"]),5);self.assertTrue(a["summary"]["human_approval_required"])
 def test_corrupt_package(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/"x.synapsepack";save_package(sample(),p)
   with zipfile.ZipFile(p,"a") as z:z.writestr("SHA256","bad")
   with self.assertRaises(ValueError):load_package(p)
if __name__=="__main__":unittest.main()
