"""榜单数据源适配器：mock（内置演示数据）/ echotik / fastmoss（HTTP JSON API）。

echotik / fastmoss 的具体 endpoint 与字段映射随账号套餐不同，
请在 config.json 的 sources.<name>.endpoints / mapping 中按实际接口文档调整。
mapping.list 为列表的 JSON 点路径，rank/key/name/value 为条目字段名。
"""
import json
import os
import random
import urllib.request

class SourceError(Exception):
    pass

def _dig(obj, dotted):
    for part in (dotted or "").split("."):
        if not part:
            continue
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj

class BaseSource:
    name = "base"
    def fetch(self, country, chart_type, top_n):
        raise NotImplementedError

class MockSource(BaseSource):
    """内置演示数据：每期做 ±6% 数值抖动、10% 概率相邻换位、10% 概率引入池中新条目。"""
    name = "mock"
    def __init__(self, path=None):
        if path is None:
            path = os.path.join(os.path.dirname(__file__), "mock_data.json")
        with open(path, encoding="utf-8") as f:
            self.data = json.load(f)
        self.rnd = random.Random()

    def fetch(self, country, chart_type, top_n):
        block = self.data.get(country, {})
        items = [list(x) for x in block.get(chart_type, [])]
        pool = block.get("_pool", {}).get(chart_type, [])
        # 偶尔引入一个新条目（触发 NEW_IN_TOP10 告警演示）
        if pool and self.rnd.random() < 0.10:
            items[-1] = list(self.rnd.choice(pool))
        # 偶尔交换相邻两名（触发 SURGE 告警演示）
        if len(items) > 1 and self.rnd.random() < 0.12:
            i = self.rnd.randrange(len(items) - 1)
            items[i], items[i + 1] = items[i + 1], items[i]
        entries = []
        for rank, (name, base) in enumerate(items[:top_n], 1):
            entries.append({
                "rank": rank,
                "key": f"{chart_type}:{country}:{name}",
                "name": name,
                "value": round(base * self.rnd.uniform(0.94, 1.06), 2),
                "extra": {"source": "mock"},
            })
        return entries

class ApiSource(BaseSource):
    """通用 JSON API 源（EchoTik / FastMoss 等），配置驱动。"""
    name = "api"
    def __init__(self, cfg):
        self.base_url = cfg.get("base_url", "").rstrip("/")
        self.token = os.environ.get(cfg.get("token_env", ""), "")
        self.timeout = float(cfg.get("timeout_seconds", 30))
        self.endpoints = cfg.get("endpoints", {})
        self.mapping = cfg.get("mapping", {})

    def fetch(self, country, chart_type, top_n):
        tpl = self.endpoints.get(chart_type)
        if not tpl:
            raise SourceError(f"未配置 {chart_type} 的 endpoint")
        url = self.base_url + tpl.format(country=country)
        req = urllib.request.Request(url)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("User-Agent", "tiktok-sea-monitor/1.0")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise SourceError(f"请求失败 {url}: {e}")
        rows = _dig(payload, self.mapping.get("list", ""))
        if not isinstance(rows, list):
            raise SourceError(f"响应中找不到列表: {self.mapping.get('list')}")
        entries = []
        for i, row in enumerate(rows[:top_n]):
            if not isinstance(row, dict):
                continue
            entries.append({
                "rank": int(row.get(self.mapping.get("rank", "rank"), i + 1) or i + 1),
                "key": str(row.get(self.mapping.get("key", "id"), "")),
                "name": str(row.get(self.mapping.get("name", "name"), "")),
                "value": row.get(self.mapping.get("value", "value")),
                "extra": {"raw": row},
            })
        entries.sort(key=lambda e: e["rank"])
        return entries

def make_source(config):
    src = config.get("source", "mock")
    if src == "mock":
        return MockSource()
    if src in config.get("sources", {}):
        s = ApiSource(config["sources"][src])
        s.name = src
        return s
    raise SourceError(f"未知数据源: {src}")
