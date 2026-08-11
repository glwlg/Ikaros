---
api_version: v3
name: ikaros_handbook
description: Ikaros 自身操作手册。当需要了解、查询或修改 Ikaros 自身的配置（模型、渠道、记忆、定时任务、技能、服务运行状态、日志排障）时必须先加载本手册，确保改配置快速且准确。
triggers:
- ikaros 配置
- 自身配置
- 修改配置
- 模型配置
- 操作手册
- 重启服务
- 查看日志
- 定时任务
- 投递失败
- 后台管理
- ikaros handbook
platform_handlers: false
permissions:
  filesystem: workspace
  shell: true
  network: limited
---

# Ikaros 操作手册

本手册是 Ikaros 了解和维护自身的权威参考。涉及自身配置的查询或修改时，先按本手册定位真源，再动手。

## 1. 定位速览

Ikaros 是多平台 Agent Runtime：Agents SDK 是唯一聊天执行内核；Runtime v2（`~/.ikaros/data/runtime.db`）是中心状态（Session/Turn/Event/Task/Artifact/Delivery/SchedulerJob）；skill、channel、memory、plugin 全部从 `extension/` 加载。仓库根即代码本体，运行状态默认写入 `~/.ikaros/`，不写回仓库。

## 2. 配置真源地图

| 配置 | 路径 | 管什么 | 生效方式 |
|---|---|---|---|
| 模型配置 | `~/.ikaros/config/models.json`（可用 `MODELS_CONFIG_PATH` 覆盖） | providers、角色绑定、模型池、选择策略 | **热加载**（按文件 mtime），改完即生效，无需重启 |
| 运行配置 | `~/.ikaros/data/kernel/runtime-config.json` | 平台开关、功能开关、CORS、注册开关、技能禁用列表 | 立即生效 |
| 环境变量 | 仓库根 `.env` | 各平台 Token/凭证、`ADMIN_USER_IDS`、`SEARXNG_URL` 等 | **需重启**对应服务 |
| 记忆配置 | `~/.ikaros/config/memory.json` | 记忆 provider（同时只激活一个） | 重启后生效 |
| 核心人设 | `~/.ikaros/data/SOUL.MD` | Ikaros 核心 SOUL 文档 | 立即生效（带版本历史） |
| 中心状态 | `~/.ikaros/data/runtime.db` | 会话/任务/事件/产物/投递回执/定时任务 | 不手改 |
| 聚合数据 | `~/.ikaros/data/bot_data.db` | Web/API、记账、用量等 | 不手改 |

原则：**优先通过 Web 后台或 Admin API 改配置**（有校验、有审计、有版本快照）；直接编辑文件时先读全文、保留不认识的字段（未知字段会被原样保留）、改完用 `python -m json.tool` 校验 JSON 合法性。

## 3. 修改配置的标准路径

### 3.1 Web 后台（推荐引导用户操作）

API 服务默认监听 `8764`，SPA 由 FastAPI 直接托管：

- `/admin/runtime`：运行配置（渠道凭证、平台开关、功能开关、SOUL、记忆 provider）
- `/admin/models`：模型配置（providers、角色绑定、模型池、思考程度、连接测试）
- `/admin/skills`：技能管理（启停、新建、导入、删除 learned 技能）
- `/admin/users`：用户管理
- `/admin/diagnostics`：运行时诊断

### 3.2 Admin API（需要 admin 认证）

统一前缀 `/api/v1/admin`：

- `GET /runtime` / `PATCH /runtime`：读写运行配置；渠道凭证改动会写入 `.env`，响应带 `restart_required: true`，**必须重启才生效**
- `POST /runtime/generate-doc`：生成运行配置文档
- `GET /models` / `PATCH /models`：读写 models.json（写入时做角色兼容性校验，全文档替换但保留未知字段）
- `POST /models/latency-check`：实测某个 provider/model 连通性与延迟
- `POST /models/fetch-provider-models`：从 provider 的 `/models` 拉模型清单（含输入能力、reasoning、思考档位、上下文窗口，未上报的字段保持手动配置）
- `GET /diagnostics`：运行时聚合诊断
- `GET /audit`：管理操作审计日志

技能管理（`/api/v1/skills`）：`GET ""` 列表、`GET /{name}/detail` 详情、`PATCH /{name}/enabled` 启停、`POST ""` 新建、`POST /import` 导入 .md/.zip、`DELETE /{name}` 删除 learned 技能（删除前自动打 zip 快照到 `~/.ikaros/data/kernel/skill-backups/`）。GET 需 operator，写操作需 admin。

定时任务（`/api/v1/scheduler`）：`GET ""` 列表、`POST ""` 新建、`PUT /{task_id}` 编辑、`PUT /{task_id}/status` 启停、`DELETE /{task_id}` 删除。

### 3.3 直接改文件

- `models.json`：可手改，热加载；结构见第 4 节
- `.env`：手改后必须重启对应服务
- `runtime-config.json`：可手改但建议走 API（有审计）
- `runtime.db` / `bot_data.db`：只读排障，不要手改

## 4. 模型配置（models.json）详解

顶层结构：

```json
{
  "mode": "merge",
  "model": { "primary": "provider/model-id", "routing": "..." },
  "models": { "primary": { "provider/model-id": {} } },
  "selection": { "primary": { "strategy": "priority" } },
  "providers": { "provider 名": { "baseUrl": "...", "apiKey": "...", "headers": {}, "api": "openai-completions", "models": [ ... ] } }
}
```

- **角色**：`primary`（主对话）、`routing`（路由/轻量任务）、`vision`（看图）、`image_generation`（生图）、`voice`（语音）
- **model**：角色的当前默认绑定，值为 `<provider>/<model-id>`
- **models**：角色的候选模型池；值为对象时 key 是模型、value 是该模型的池内元数据
- **selection**：池选择策略，`priority`（按顺序）/ `round_robin` / `least_usage`（按今日最低用量）
- **provider.models[]** 每个模型支持的关键字段：
  - `id`、`name`、`reasoning`（布尔）
  - `reasoningEffort`（当前思考档位）、`reasoningEfforts`（可选档位列表）；**只有 `reasoning: true` 时档位才会随请求发送**
  - `input`：`text`/`image`/`voice`；`output`：`text`/`image`/`voice`/`video`
  - 角色兼容性由输入输出能力决定：primary/routing 要 `text` 输入，vision 要 `image` 输入，image_generation 要 `image` 输出，voice 要 `voice` 输入
  - `cost`（input/output/cacheRead/cacheWrite）、`limits`（dailyTokens/dailyImages）、`contextWindow`、`maxTokens`
- 修改绑定前先确认模型在该角色的能力要求内，否则校验会拒绝

## 5. 服务运维

两个服务目标：

- **Ikaros Core**：`src/main.py`，Bot 通道 + 调度器 + 运行时
- **Ikaros API**：FastAPI + Web SPA，端口 `8764`

常用命令：

```bash
# systemd（默认 --user 安装，服务名 ikaros）
systemctl --user status ikaros
systemctl --user restart ikaros
journalctl --user -u ikaros -n 200 --no-pager
# 不确定装了哪些单元时
systemctl --user list-units '*ikaros*'

# 健康检查
curl -s http://localhost:8764/api/v1/health

# 测试与构建（仓库根）
.venv/bin/python -m pytest tests -q
./scripts/build_web.sh --install
```

启动顺序（排障时对照）：基础存储 → scheduler 加载 job → extension runtime → 激活唯一 memory provider → 扫描 `extension/skills/**/SKILL.md` → 注册 channel/skill/plugin → 动态 skill scheduler → 清理过期任务 → startup hooks → adapters/heartbeat/subagent supervisor。

## 6. 排障速查

- **消息没发出去 / 文件没投递**：查 Runtime v2 的 delivery receipt 和 `delivery_failed` 事件；Web trace API：`GET /api/v1/web-chat/sessions/{id}/trace`、`/deliveries`。只有投递回执能证明「已发送」
- **定时任务没触发**：每个 job 绑定独立 `scheduled_task` session，触发即产生 system turn；先看 `/api/v1/scheduler` 列表确认启用状态，再看对应 session 的 trace
- **模型调不通**：用 `POST /api/v1/admin/models/latency-check` 实测；检查 provider 的 baseUrl/apiKey/headers 与模型能力配置
- **技能没生效**：`/admin/skills` 确认未禁用；技能真源是 `extension/skills/**/SKILL.md`，改动后注册表按 mtime 自动刷新
- **彻底重置 Runtime v2（保留记账数据）**：`python scripts/runtime_v2_reset.py`（先 dry-run，确认后加 `--yes`）

## 7. 目录速查

```text
src/api/             FastAPI + SPA API（endpoints/services/auth）
src/core/            Runtime v2、kernel、scheduler、delivery、extension runtime
src/platforms/web/   Web 前端（Vue 3 + Vite）
extension/channels/  Telegram / Weixin / Discord / DingTalk
extension/memories/  记忆 provider
extension/skills/    builtin/（随仓库）+ learned/（运行时习得）
scripts/             部署/构建/重置脚本
DEPLOYMENT.md        完整部署文档
```
