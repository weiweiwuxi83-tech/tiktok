"""告警规则：新进 TOP10 / 单期上升 >=N 名 / 连续 M 期跌出 TOP10"""

def evaluate(country, ctype, label, latest, prev, older, rules, now_str):
    """latest/prev: 最近一次/上一次快照的 entries(list of dict)；older: 更早的快照 entries 列表（新→旧）"""
    alerts = []
    if not latest:
        return alerts
    prev_rank = {e["item_key"]: e["rank"] for e in prev} if prev else {}
    latest_rank = {e["item_key"]: e["rank"] for e in latest}
    name_of = {e["item_key"]: e["name"] for e in (latest or []) + (prev or [])}

    def add(rule, key, detail):
        alerts.append({
            "country": country, "chart_type": ctype, "rule": rule,
            "item_key": key, "name": name_of.get(key, key), "detail": detail,
            "snapshot_id": None, "created_at": now_str,
        })

    if rules.get("new_in_top10", True) and prev:
        for key, rank in latest_rank.items():
            if key not in prev_rank:
                add("NEW_IN_TOP10", key, f"新进 TOP10（当前第 {rank} 名）")

    gain_min = int(rules.get("surge_min_rank_gain", 5))
    for key, rank in latest_rank.items():
        if key in prev_rank and prev_rank[key] - rank >= gain_min:
            add("SURGE", key, f"单期上升 {prev_rank[key] - rank} 名（第 {prev_rank[key]} → {rank}）")

    periods = int(rules.get("dropout_periods", 3))
    older_maps = [{e["item_key"]: e["rank"] for e in snaps} for snaps in (older or [])[:periods - 1]]
    for key, rank in prev_rank.items():
        if key in latest_rank:
            continue
        if len(older_maps) >= periods - 1 and all(key in m for m in older_maps):
            add("DROPOUT", key, f"连续 {periods} 期跌出 TOP10（上期第 {rank} 名）")

    return alerts
