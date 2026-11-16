import unittest
from synapse import freshness as f

CFG = {"tavily_key": "k", "bifrost_url": "http://gw", "bifrost_key": "", "models": ["openai/x", "anthropic/y"]}
RES = {"results": [{"title": "Shelter closed after flood", "url": "https://n/1", "content": "The Town Hall shelter closed.", "published_date": "2026-11-10"}]}

def fake_post(judge):
    def post(url, payload, headers, timeout=25):
        if "tavily" in url:
            assert headers["Authorization"] == "Bearer k" and payload["topic"] == "news"; return RES
        return judge(payload)
    return post

class Freshness(unittest.TestCase):
    def setUp(self): f._CACHE.clear(); f._HITS.clear()
    def test_unconfigured_is_honest(self):
        r = f.verify_place("Town Hall", cfg={**CFG, "tavily_key": ""}); self.assertFalse(r["configured"]); self.assertEqual(r["status"], "unknown")
    def test_model_verdict_with_valid_evidence(self):
        j = lambda p: {"choices": [{"message": {"content": '{"status":"closed","confidence":0.8,"reason":"News says closed","evidence":[1]}'}}]}
        r = f.verify_place("Town Hall", "Pune", CFG, fake_post(j)); self.assertEqual(r["status"], "closed"); self.assertEqual(r["sources"][0]["url"], "https://n/1")
    def test_verdict_without_real_evidence_is_unknown(self):
        j = lambda p: {"choices": [{"message": {"content": '{"status":"open","confidence":1,"reason":"x","evidence":[7]}'}}]}
        self.assertEqual(f.verify_place("Hall A", "", CFG, fake_post(j))["status"], "unknown")
    def test_falls_back_to_second_model(self):
        calls = []
        def j(p):
            calls.append(p["model"])
            if p["model"] == "openai/x": raise RuntimeError("down")
            return {"choices": [{"message": {"content": '{"status":"damaged","confidence":0.6,"reason":"r","evidence":[1]}'}}]}
        self.assertEqual(f.verify_place("Hall B", "", CFG, fake_post(j))["status"], "damaged"); self.assertEqual(calls, ["openai/x", "anthropic/y"])
    def test_no_model_lists_sources_without_claiming_status(self):
        r = f.verify_place("Hall C", "", {**CFG, "bifrost_url": ""}, fake_post(lambda p: {})); self.assertEqual(r["status"], "unknown"); self.assertTrue(r["sources"])
    def test_cache_and_rate_limit(self):
        n = []; j = lambda p: n.append(1) or {"choices": [{"message": {"content": "{}"}}]}
        f.verify_place("Hall D", "", CFG, fake_post(j)); f.verify_place("Hall D", "", CFG, fake_post(j)); self.assertEqual(len(n), 1)  # second call served from cache
        self.assertTrue(all(f.rate_ok("1.1.1.1", 3, 60, 100) for _ in range(3))); self.assertFalse(f.rate_ok("1.1.1.1", 3, 60, 101))
if __name__ == "__main__": unittest.main()
