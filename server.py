"""HTTP 接口 + 静态页面服务（仅标准库）。

GET /api/health                健康检查
GET /api/charts?country=ID&type=videos   最新榜单（含较上期排名变动 delta 与近 7 期 spark 数据）
GET /api/alerts?limit=20       最近告警
GET / 或 /index.html           前端页面（web/ 目录）
"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")

class Handler(BaseHTTPRequestHandler):
    db = None
    config = None
    protocol_version = "HTTP/1.1"

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        if path in ("/", ""):
            path = "/index.html"
        full = os.path.normpath(os.path.join(WEB_DIR, path.lstrip("/")))
        if not full.startswith(WEB_DIR) or not os.path.isfile(full):
            self._json({"error": "not found"}, 404)
            return
        with open(full, "rb") as f:
            body = f.read()
        ctype = "text/html; charset=utf-8" if full.endswith(".html") else "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/api/health":
            self._json({
                "ok": True,
                "source": self.config.get("source"),
                "interval_minutes": self.config.get("interval_minutes"),
                "last_run": self.db.get_meta("last_run"),
                "last_error": self.db.get_meta("last_error"),
            })
        elif u.path == "/api/charts":
            country = q.get("country", [""])[0]
            ctype = q.get("type", [""])[0]
            ids = self.db.snapshot_ids(country, ctype, limit=8)
            if not ids:
                self._json({"captured_at": None, "entries": []})
                return
            sid = ids[0]
            info = self.db.snapshot_info(sid)
            latest = self.db.snapshot_entries(sid)
            prev_map = {}
            if len(ids) > 1:
                prev_map = {e["item_key"]: e["rank"] for e in self.db.snapshot_entries(ids[1])}
            entries = []
            for e in latest:
                sp = self.db.history_values(country, ctype, e["item_key"], limit=7)
                entries.append({
                    "rank": e["rank"], "name": e["name"], "value": e["value"],
                    "extra": e["extra"],
                    "delta": ("NEW" if e["item_key"] not in prev_map
                              else (prev_map[e["item_key"]] - e["rank"]) if prev_map else 0),
                    "spark": [v for v in sp if v is not None],
                })
            self._json({"captured_at": info["captured_at"], "entries": entries})
        elif u.path == "/api/alerts":
            limit = int(q.get("limit", ["20"])[0] or 20)
            alerts = self.db.recent_alerts(min(limit, 100))
            countries = self.config.get("countries", {})
            labels = self.config.get("chart_types", {})
            for a in alerts:
                a["country_name"] = countries.get(a["country"], a["country"])
                a["type_label"] = labels.get(a["chart_type"], a["chart_type"])
            self._json({"alerts": alerts})
        else:
            self._file(u.path)

    def log_message(self, *args):
        pass

def make_server(config, db):
    Handler.db = db
    Handler.config = config
    return ThreadingHTTPServer(
        (config.get("listen_host", "0.0.0.0"), int(config.get("listen_port", 8000))),
        Handler)
