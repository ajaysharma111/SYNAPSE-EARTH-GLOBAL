"""Regional map installer: single installs and a cancellable background batch queue.

Safety rails: only official Geofabrik HTTPS .osm.pbf URLs, per-extract size cap (HEAD check),
free-disk check, one batch at a time, and every failure is recorded per item instead of aborting the batch.
"""
import re, shutil, subprocess, sys, tempfile, threading, time, urllib.request
from pathlib import Path
from .engine import activate_package

UA = "SYNAPSE-EARTH/1.1 (regional map installer)"
RID = re.compile(r"[a-zA-Z0-9_-]{1,120}")


def validate_item(it):
    url = str(it.get("pbf", "")); name = str(it.get("name", "")).strip(); rid = str(it.get("region_id", "")).strip()
    cc = re.sub(r"[^A-Z]", "", str(it.get("country_code") or "XX").upper())[:2] or "XX"; bbox = it.get("bbox")
    if not url.startswith("https://download.geofabrik.de/") or not url.endswith(".osm.pbf"):
        raise ValueError("Only official HTTPS Geofabrik .osm.pbf URLs are accepted.")
    if not name or not RID.fullmatch(rid):
        raise ValueError("A region name and simple region ID are required.")
    if not isinstance(bbox, list) or len(bbox) != 4:
        raise ValueError("A catalogue bounding box is required.")
    return {"pbf": url, "name": name, "region_id": rid, "country_code": cc, "bbox": [float(x) for x in bbox]}


def remote_size(url, timeout=20):
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            n = r.headers.get("Content-Length")
            return int(n) if n else None
    except Exception:  # noqa: BLE001
        return None


def install_one(item, data_dir, max_bytes=3_000_000_000, progress=None, cancelled=lambda: False):
    """Download + import + activate. Returns dict(status, ...). Raises on failure."""
    item = validate_item(item)
    with tempfile.TemporaryDirectory(prefix="synapse-map-") as td:
        pbf = Path(td) / "extract.osm.pbf"; total = 0
        req = urllib.request.Request(item["pbf"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as response, pbf.open("wb") as out:
            while True:
                if cancelled():
                    return {"status": "cancelled"}
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Extract exceeds the %d MB size limit; choose a smaller subregion." % (max_bytes // 1_000_000))
                out.write(chunk)
                if progress:
                    progress(total)
        outdir = Path(td) / "built"; outdir.mkdir()
        cmd = [sys.executable, "-m", "synapse.osm_import", "--pbf", str(pbf), "--name", item["name"], "--country-code", item["country_code"],
               "--region-id", item["region_id"], "--bbox", ",".join(map(str, item["bbox"])), "--out", str(outdir)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        t0 = time.time()
        while proc.poll() is None:
            if cancelled():
                proc.terminate(); return {"status": "cancelled"}
            if time.time() - t0 > 3600:
                proc.kill(); raise RuntimeError("Import timed out after 60 minutes")
            time.sleep(1)
        so, se = proc.communicate()
        if proc.returncode:
            raise RuntimeError(((se or so) or "import failed")[-600:])
        dest = activate_package(outdir / (item["region_id"] + ".synapsepack"), data_dir)
    return {"status": "installed", "file": dest.name, "downloaded_bytes": total, "import_log": (so or "")[-1500:]}


class BatchInstaller:
    def __init__(self, data_dir, on_item=None):
        self.on_item = on_item
        self.data = str(data_dir); self.lock = threading.Lock(); self._cancel = False
        self.state = {"running": False, "items": [], "started": None, "finished": None}

    def status(self):
        with self.lock:
            return {"running": self.state["running"], "started": self.state["started"], "finished": self.state["finished"],
                    "items": [dict(i) for i in self.state["items"]]}

    def cancel(self):
        self._cancel = True

    def start(self, items, max_mb=300, skip_installed=True):
        with self.lock:
            if self.state["running"]:
                raise RuntimeError("A batch install is already running.")
            clean = []
            for it in items[:2000]:
                v = validate_item(it)
                clean.append({**v, "status": "queued", "message": "", "bytes": 0, "size": None})
            if not clean:
                raise ValueError("No regions selected.")
            self._cancel = False
            self.state = {"running": True, "items": clean, "started": time.time(), "finished": None}
        threading.Thread(target=self._run, args=(max(10, min(5000, int(max_mb))) * 1_000_000, skip_installed), daemon=True).start()

    def _set(self, it, **kw):
        with self.lock:
            it.update(kw)
        if self.on_item and it.get("status") in ("installed", "failed", "skipped") and kw.get("status"):
            try:
                self.on_item(dict(it))
            except Exception:  # noqa: BLE001
                pass

    def _run(self, max_bytes, skip_installed):
        try:
            for it in self.state["items"]:
                if self._cancel:
                    self._set(it, status="cancelled"); continue
                if skip_installed and (Path(self.data) / (it["region_id"] + ".json")).exists():
                    self._set(it, status="skipped", message="already installed"); continue
                size = remote_size(it["pbf"])
                self._set(it, size=size)
                if size and size > max_bytes:
                    self._set(it, status="skipped", message="%d MB exceeds the %d MB limit" % (size // 1_000_000, max_bytes // 1_000_000)); continue
                try:
                    free = shutil.disk_usage(self.data).free
                except Exception:  # noqa: BLE001
                    free = None
                if size and free is not None and free < size * 8:
                    self._set(it, status="skipped", message="not enough free disk space (need ≈ %d MB)" % (size * 8 // 1_000_000)); continue
                self._set(it, status="running", message="downloading")
                try:
                    r = install_one(it, self.data, max_bytes, progress=lambda n, it=it: self._set(it, bytes=n), cancelled=lambda: self._cancel)
                    self._set(it, status=r["status"], message="" if r["status"] == "installed" else "cancelled")
                except Exception as e:  # noqa: BLE001
                    self._set(it, status="failed", message=str(e)[:300])
        finally:
            with self.lock:
                self.state["running"] = False; self.state["finished"] = time.time()
