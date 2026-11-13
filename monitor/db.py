import os
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  country TEXT NOT NULL,
  chart_type TEXT NOT NULL,
  captured_at TEXT NOT NULL,
  UNIQUE(country, chart_type, captured_at)
);
CREATE INDEX IF NOT EXISTS idx_snap_lookup ON snapshots(country, chart_type, captured_at DESC);
CREATE TABLE IF NOT EXISTS entries(
  snapshot_id INTEGER NOT NULL,
  rank INTEGER NOT NULL,
  item_key TEXT NOT NULL,
  name TEXT NOT NULL,
  value REAL,
  extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_entries_snap ON entries(snapshot_id);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  country TEXT NOT NULL,
  chart_type TEXT NOT NULL,
  rule TEXT NOT NULL,
  item_key TEXT NOT NULL,
  name TEXT NOT NULL,
  detail TEXT NOT NULL,
  snapshot_id INTEGER,
  created_at TEXT NOT NULL,
  UNIQUE(snapshot_id, rule, item_key)
);
CREATE INDEX IF NOT EXISTS idx_alerts_time ON alerts(id DESC);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""

class DB:
    def __init__(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.lock = threading.Lock()

    def set_meta(self, key, value):
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))
            self.conn.commit()

    def get_meta(self, key):
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def save_snapshot(self, country, ctype, captured_at, entries):
        """entries: list of dict(rank, key, name, value, extra)"""
        with self.lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO snapshots(country,chart_type,captured_at) VALUES(?,?,?)",
                (country, ctype, captured_at))
            sid = self.conn.execute(
                "SELECT id FROM snapshots WHERE country=? AND chart_type=? AND captured_at=?",
                (country, ctype, captured_at)).fetchone()["id"]
            self.conn.executemany(
                "INSERT INTO entries(snapshot_id,rank,item_key,name,value,extra) VALUES(?,?,?,?,?,?)",
                [(sid, e["rank"], e["key"], e["name"], e.get("value"),
                  json_dumps(e.get("extra"))) for e in entries])
            self.conn.commit()
            return sid

    def snapshot_ids(self, country, ctype, limit):
        return [r["id"] for r in self.conn.execute(
            "SELECT id FROM snapshots WHERE country=? AND chart_type=? ORDER BY captured_at DESC LIMIT ?",
            (country, ctype, limit))]

    def snapshot_info(self, sid):
        return self.conn.execute("SELECT * FROM snapshots WHERE id=?", (sid,)).fetchone()

    def snapshot_entries(self, sid):
        return [dict(r) for r in self.conn.execute(
            "SELECT rank,item_key,name,value,extra FROM entries WHERE snapshot_id=? ORDER BY rank",
            (sid,))]

    def add_alerts(self, alerts):
        """alerts: list of dict(country,chart_type,rule,item_key,name,detail,snapshot_id,created_at)"""
        with self.lock:
            cur = self.conn.executemany(
                "INSERT OR IGNORE INTO alerts(country,chart_type,rule,item_key,name,detail,snapshot_id,created_at)"
                " VALUES(:country,:chart_type,:rule,:item_key,:name,:detail,:snapshot_id,:created_at)", alerts)
            self.conn.commit()
            return cur.rowcount

    def recent_alerts(self, limit=20):
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))]

    def history_values(self, country, ctype, item_key, limit=7):
        return [r["value"] for r in self.conn.execute(
            "SELECT e.value FROM snapshots s JOIN entries e ON e.snapshot_id=s.id"
            " WHERE s.country=? AND s.chart_type=? AND e.item_key=?"
            " ORDER BY s.captured_at DESC LIMIT ?", (country, ctype, item_key, limit))][::-1]

import json as _json
def json_dumps(obj):
    return _json.dumps(obj, ensure_ascii=False) if obj is not None else None
