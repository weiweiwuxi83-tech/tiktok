# TikTok 东南亚榜单监听台（采集后端 + 前端）

覆盖 印度尼西亚 / 泰国 / 越南 / 菲律宾 / 马来西亚 / 新加坡 的 热门视频、创作者、热门音乐、话题标签、带货直播 五类榜单：
**定时采集 → SQLite 存储 → 排名变动比对 → 告警（可推送到飞书等 Webhook）→ HTTP 接口供前端轮询**。

纯 Python 标准库实现（Python ≥ 3.9），无第三方依赖。

## 快速开始

```bash
cd tiktok-sea-monitor
python run.py
```

- 首次启动立即采集一期，之后按 `config.json` 的 `interval_minutes`（默认 60 分钟）循环
- 前端页面：http://localhost:8000/
- 健康检查：http://localhost:8000/api/health

默认 `source = "mock"`，使用内置演示数据，无需任何 API Key 即可跑通全链路（榜单入库、告警规则、Webhook、前端轮询）。

## 接入真实数据源（EchoTik / FastMoss）

1. 在 config.json 中把 `source` 改为 `"echotik"` 或 `"fastmoss"`；
2. 将对应 token 放入环境变量（默认读 `ECHOTIK_TOKEN` / `FASTMOSS_TOKEN`，名称可在 config.json 改）：
   ```bash
   export ECHOTIK_TOKEN="你的token"
   ```
3. **按你账号套餐的实际接口文档**，修改 config.json 里 `sources.<name>.endpoints`（URL 模板，`{country}` 会替换为国家码）和 `mapping`（列表的点路径与字段名）。

> 注意：EchoTik / FastMoss 的 endpoint 与字段随套餐和版本不同，仓库里的路径仅为占位示例；
> 直接抓取 TikTok 网页/App 接口违反其服务条款且有封号风险，建议始终使用第三方数据服务。

## HTTP 接口

| 接口 | 说明 |
|---|---|
| `GET /api/charts?country=ID&type=videos` | 最新一期榜单；每条含 `rank/name/value/delta`（较上期名次变化，`"NEW"` 表示新上榜）和 `spark`（近 7 期数值） |
| `GET /api/alerts?limit=20` | 最近告警，含 `country_name/type_label/rule/detail` |
| `GET /api/health` | 数据源、采集周期、上次采集时间、最近错误 |

国家码：ID / TH / VN / PH / MY / SG；榜单类型：videos / creators / songs / tags / lives。

## 告警规则（config.json 的 alerts 段）

| 规则 | 触发条件 | 默认 |
|---|---|---|
| NEW_IN_TOP10 | 上一期不在 TOP10、本期进入 | 开 |
| SURGE | 同一条目单期名次上升 ≥ N | N = 5 |
| DROPOUT | 之前连续 M 期在榜、本期跌出 | M = 3 |

同一快照内同一规则同一条目只告警一次（数据库唯一约束去重）。
`webhook_url` 配置后，告警会以 `{"msg_type":"text","content":{"text":"..."}}` 格式 POST（飞书自定义机器人直接可用；其他系统请自行在 run.py 的 `send_webhook` 调整格式）。

## 部署建议（Linux + systemd）

```bash
# 1. 拷贝项目到服务器
# 2. 写入服务：systemd 单元示例见 deploy/tiktok-monitor.service
sudo cp deploy/tiktok-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now tiktok-monitor
# 3. 反向代理（可选）：用 nginx/caddy 把 80/443 转发到 8000 端口，即可公网访问前端
```

```ini
# deploy/tiktok-monitor.service
[Unit]
Description=TikTok SEA ranking monitor
After=network.target

[Service]
WorkingDirectory=/opt/tiktok-sea-monitor
ExecStart=/usr/bin/python3 run.py
Restart=always
RestartSec=10
Environment=ECHOTIK_TOKEN=
Environment=FASTMOSS_TOKEN=

[Install]
WantedBy=multi-user.target
```

## 目录结构

```
tiktok-sea-monitor/
├── run.py              # 入口：采集循环 + HTTP 服务
├── server.py           # HTTP 接口与静态页面服务
├── config.json         # 全部配置（数据源/周期/告警/端口）
├── collector/
│   ├── sources.py      # mock / EchoTik / FastMoss 适配器
│   └── mock_data.json  # 内置演示榜单
├── monitor/
│   ├── db.py           # SQLite 存储（快照/条目/告警/元信息）
│   └── alerts.py       # 三条告警规则引擎
└── web/index.html      # 前端监听台（轮询 /api/charts 与 /api/alerts）
```

## 合规提示

榜单数据来自 TikTok，采集与使用请遵守 TikTok 服务条款与当地法律；商业用途建议采购 EchoTik、FastMoss 等授权数据服务。

## 纯 GitHub 部署（Actions 采集 + Pages 展示，零服务器费用）

1. 把项目 push 到一个 GitHub 仓库；
2. **Settings → Secrets and variables → Actions** 添加 `ECHOTIK_TOKEN` / `FASTMOSS_TOKEN`（mock 模式可跳过）；
3. **Actions → collect-rankings → Run workflow** 手动跑一次验证；
4. **Settings → Pages**：Source 选主分支根目录（root）。此后工作流每小时自动采集并把 `web/data/*.json` 提交回仓库；
5. 访问 `https://<你的用户名>.github.io/<仓库名>/web/` 即可看到监听台（前端会优先请求 API，不存在时自动读取静态 JSON）。

限制：GitHub 的 cron 在高峰可能延迟数分钟到几十分钟；数据以 JSON 形式存仓库（公开仓库意味着榜单数据公开，注意合规）；告警推送的 webhook_url 直接写在 config.json 即可（Actions 运行时同样会推送）。
