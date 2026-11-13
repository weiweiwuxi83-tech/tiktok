"""定时采集 + 告警 + HTTP 服务一体入口。

用法：
    python run.py                          # 采集一期后按 config.json 周期循环，并启动 HTTP 服务
    python run.py --once                   # 只采集一期后退出（CI / Actions 用）
    python run.py --once --export-dir web/data   # 采集后额外导出静态 JSON（GitHub Pages 前端用）
"""
import argparse
import json
import os
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime, timezone, timedelta

from collector.sources import make_source
from monitor.alerts import evaluate
from monitor.db import DB
from server import make_server

TZ = timezone(timedelta(hours=8))

def now_str():
    return datetime.now(TZ).isoformat(timespec="seconds")

def send_webhook(url, text):
    if not url:
        return
    try:
        req = urllib.request.Request(
            url, data=json.dumps({"msg_type": "text", "content": {"text": text}}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # 告警推送失败不影响主流程

def collect_all(db, source, config):
    countries = config.get("countries", {})
    labels = config.get("chart_types", {})
    rules = config.get("alerts", {})
    top_n = int(config.get("top_n", 10))
    ts = now_str()
    total_alerts = 0
    for cc in countries:
        for ct in labels:
            entries = source.fetch(cc, ct, top_n)
            sid = db.save_snapshot(cc, ct, ts, entries)
            ids = db.snapshot_ids(cc, ct, limit=5)
            latest = db.snapshot_entries(ids[0]) if ids else []
            prev = db.snapshot_entries(ids[1]) if len(ids) > 1 else []
            older = [db.snapshot_entries(i) for i in ids[2:]]
            fired = evaluate(cc, ct, labels[ct], latest, prev, older, rules, ts)
            for a in fired:
                a["snapshot_id"] = sid
            total_alerts += db.add_alerts(fired)
            for a in fired:
                line = f"[TikTok榜单告警] {countries[cc]} · {labels[ct]} · 「{a['name']}」 {a['detail']}"
                print(line, flush=True)
                send_webhook(config.get("webhook_url", ""), line)
    db.set_meta("last_run", ts)
    print(f"[{ts}] 采集完成：{len(countries) * len(labels)} 个榜单，新增告警 {total_alerts} 条", flush=True)
    return total_alerts

def export_json(db, config, out_dir):
    """把最新榜单与告警导出为静态 JSON（GitHub Pages / 任意静态托管可读）。"""
    countries = config.get("countries", {})
    labels = config.get("chart_types", {})
    os.makedirs(out_dir, exist_ok=True)
    for cc in countries:
        for ct in labels:
            ids = db.snapshot_ids(cc, ct, limit=8)
            payload = {"captured_at": None, "entries": []}
            if ids:
                info = db.snapshot_info(ids[0])
                prev_map = {}
                if len(ids) > 1:
                    prev_map = {e["item_key"]: e["rank"] for e in db.snapshot_entries(ids[1])}
                entries = []
                for e in db.snapshot_entries(ids[0]):
                    sp = [v for v in db.history_values(cc, ct, e["item_key"], limit=7) if v is not None]
                    entries.append({
                        "rank": e["rank"], "name": e["name"], "value": e["value"],
                        "delta": ("NEW" if e["item_key"] not in prev_map
                                  else (prev_map[e["item_key"]] - e["rank"]) if prev_map else 0),
                        "spark": sp,
                    })
                payload = {"captured_at": info["captured_at"], "entries": entries}
            with open(os.path.join(out_dir, f"{cc}_{ct}.json"), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
    alerts = db.recent_alerts(50)
    for a in alerts:
        a["country_name"] = countries.get(a["country"], a["country"])
        a["type_label"] = labels.get(a["chart_type"], a["chart_type"])
    with open(os.path.join(out_dir, "alerts.json"), "w", encoding="utf-8") as f:
        json.dump({"alerts": alerts}, f, ensure_ascii=False)
    print(f"已导出静态 JSON 到 {out_dir}/（{len(countries) * len(labels)} 个榜单 + alerts）", flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="只采集一期后退出")
    ap.add_argument("--export-dir", default="", help="采集后导出静态 JSON 到该目录")
    args = ap.parse_args()

    with open("config.json", encoding="utf-8") as f:
        config = json.load(f)
    db = DB(config.get("db_path", "data/monitor.db"))
    source = make_source(config)

    if args.once:
        collect_all(db, source, config)
        if args.export_dir:
            export_json(db, config, args.export_dir)
        return

    srv = make_server(config, db)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host, port = srv.server_address
    print(f"HTTP 接口已启动: http://{host}:{port}  (前端页面: http://{host}:{port}/)", flush=True)

    interval = max(1, int(config.get("interval_minutes", 60))) * 60
    while True:
        try:
            collect_all(db, source, config)
            db.set_meta("last_error", "")
        except Exception:
            err = traceback.format_exc()
            db.set_meta("last_error", err)
            print(err, file=sys.stderr, flush=True)
        time.sleep(interval)

if __name__ == "__main__":
    main()
