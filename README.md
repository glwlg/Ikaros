# Ikaros

Ikaros 是一个面向个人长期使用的多平台 Agent Runtime。它把 Telegram、微信、Web、定时任务、skill、记忆和产物投递收束到 Agents SDK 驱动的统一运行时里，目标是让日常对话、工具执行、后台任务和系统维护都能留下可追踪的闭环。

![logo](logo.jpg)

## 当前定位

- **个人主执行者**：用户始终在和 Ikaros 对话；subagent、skill、kernel 都是内部执行机制。
- **多渠道入口**：Telegram、微信 iLink、Discord、钉钉 Stream 和 Web/API 共用同一套会话与任务模型。
- **Runtime v2 中心状态**：会话、轮次、事件、任务、产物和投递回执统一写入 `runtime.db`，便于恢复、排障和质量分析。
- **Agents SDK 主执行内核**：使用 OpenAI Agents SDK 负责 Agent、工具调用、流式执行和任务收口。
- **Extension Runtime**：skill、channel、memory、plugin 都通过扩展层注册，避免继续把业务入口写进 core。
- **统一产物投递**：图片、视频、音频、文档等结果先登记为 artifact，再由平台 adapter 投递并写入 delivery receipt。

## 架构概览

```text
User / Scheduler / Web
        │
        ▼
Channel Adapter / API Endpoint
        │
        ▼
Ikaros Core
  ├─ Runtime v2: Session / Turn / Event / Task / Artifact / Delivery
  ├─ Agents SDK Runtime
  ├─ Extension Runtime: skills / channels / memories / plugins
  ├─ Scheduler Runtime
  └─ Delivery Helpers
        │
        ▼
Telegram / Weixin / Web / Files / External Services
```

### Ikaros Core

Core 是唯一的主执行面，负责：

- 接收平台消息、Web 事件、定时任务触发和控制命令
- 组装身份、SOUL、用户配置、记忆种子和本轮输入
- 维护 Runtime v2 的 session、turn、task 和事件流
- 通过 Agents SDK 执行本轮工作
- 调用 extension runtime 暴露的 skill、channel、memory、plugin
- 将文本和文件产物交给统一 delivery helper 投递

普通闲聊也会有 session 和 turn，但只有需要生命周期管理的工作才会创建 task。

### Runtime v2

Runtime v2 是当前运行时的中心模型，默认数据库为：

```text
~/.ikaros/data/runtime.db
```

核心对象：

- `Session`：长期会话容器，类型包括 `channel_chat`、`scheduled_task`、`web_workspace`、`system`
- `Turn`：一次用户输入、系统触发或定时任务触发
- `Event`：append-only 事件流，记录 Agent/tool 输出、文本增量、等待用户、失败、完成等
- `Task`：需要状态管理的工作，状态固定为 `queued`、`running`、`waiting_user`、`waiting_external`、`succeeded`、`failed`、`cancelled`、`expired`
- `Artifact`：图片、视频、音频、文档等文件产物
- `Delivery`：每个平台的投递回执，用于定位“已生成但没发出去”的问题
- `SchedulerJob`：定时任务与 scheduled task session 的绑定

非法状态跳转会被拒绝，例如 terminal turn 不能重新回到 `running`。

### Agents SDK Runtime

Agents SDK 是 Ikaros 唯一的聊天执行运行时，负责 Agent、工具调用、流式输出和 Runtime v2 事件收口。长任务进度和图片、视频、文件等中间产物由 Agent 通过 `send_message` 主动投递。

### Extension Runtime

四类扩展统一从 `extension/` 加载：

```text
extension/
├── channels/    # Telegram / Weixin / Discord / DingTalk 等平台接入
├── memories/    # 长期记忆 provider；同一时间只能激活一个
├── plugins/     # 控制面命令、菜单、通用运行时能力
└── skills/      # builtin + learned skills
```

注册面由 `src/core/extension_runtime.py` 和 `src/core/extension_base.py` 提供：

- `register_adapter(...)`
- `register_command(...)`
- `register_callback(...)`
- `register_job(...)`
- `on_startup(...)`
- `on_shutdown(...)`
- `activate_memory_provider(...)`

skill 的真源是 `extension/skills/**/SKILL.md`。如果 skill 需要动态命令、回调或 job，可以在脚本中定义扩展类注册。

### Channel 与 Delivery

channel adapter 只负责平台接入、渲染和投递，不负责猜测 kernel 输出语义。

当前统一规则：

- 文本输出写入 Runtime v2 event，并由平台按能力发送或编辑
- 文件输出先登记为 artifact，再按 kind 调用 `reply_photo`、`reply_video`、`reply_audio` 或 `reply_document`
- 每个平台投递结果都会写 delivery receipt
- 投递失败会写 `delivery_failed` 事件，Web trace 和 diagnostics 可直接定位

Web 会话 API 也消费同一套 Runtime v2 事件：

- `GET /api/v1/web-chat/sessions`
- `GET /api/v1/web-chat/sessions/{session_id}/messages`
- `GET /api/v1/web-chat/sessions/{session_id}/stream`
- `GET /api/v1/web-chat/sessions/{session_id}/deliveries`
- `GET /api/v1/web-chat/sessions/{session_id}/trace`

### Scheduler v2

定时任务会绑定独立 `scheduled_task` session。每次触发时创建一个 system turn，执行结果、artifact 和报告都进入同一条 Runtime v2 trace。

当前原则：

- job 配置收敛到 Runtime v2 `scheduler_jobs`
- scheduler 启动时加载一次，配置变更时显式 reload
- reconcile 只做兜底校验，避免 watcher/reload/reconcile 多套机制互相打架
- Web 工作台可以看到 scheduled task session
- 定时任务报告可以通过会话入口继续校准，后续触发复用同一上下文

## 目录结构

```text
.
├── src/
│   ├── api/              # FastAPI + SPA API
│   ├── core/             # Runtime v2、kernel、scheduler、delivery、extension runtime
│   ├── handlers/         # 平台无关命令和消息处理
│   ├── ikaros/           # Ikaros 开发、规划和闭环服务
│   ├── platforms/web/    # Web 前端
│   ├── services/         # 外部服务集成
│   └── shared/           # 共享契约和类型
├── extension/
│   ├── channels/
│   ├── memories/
│   ├── plugins/
│   └── skills/
├── docs/
│   └── runtime_v2_test_ledger.md
├── tests/
├── scripts/
│   └── runtime_v2_reset.py
├── config/
├── DEPLOYMENT.md
├── DEVELOPMENT.md
└── README.md
```

## 运行时数据

默认路径：

- `~/.ikaros/data/runtime.db`：Runtime v2 中心状态
- `~/.ikaros/data/bot_data.db`：Web/API、记账、用量等聚合数据
- `~/.ikaros/config/models.json`：模型配置
- `~/.ikaros/config/memory.json`：记忆 provider 配置
- `downloads/`：媒体下载等文件产物
- `.env`：本地环境变量，不提交

旧的仓库内 `data/` 和 `config/` 只保留模板、历史或迁移用途；新运行状态默认不写回仓库。

如果要重置 Runtime v2 状态，同时保留记账关键数据，可以先 dry-run：

```bash
python scripts/runtime_v2_reset.py
```

确认后执行：

```bash
python scripts/runtime_v2_reset.py --yes
```

该脚本会备份 `.env`、`bot_data.db`、记账 active state 和旧 `runtime.db`，然后重新初始化 Runtime v2。

## 启动顺序

`src/main.py` 当前启动链路：

1. 初始化基础数据库和状态存储
2. 启动 scheduler，加载持久化 job
3. 初始化 extension runtime
4. 激活唯一 memory extension，并初始化长期记忆
5. 扫描 `extension/skills/**/SKILL.md`
6. 注册 channel、skill、plugin extensions
7. 启动动态 skill scheduler
8. 清理 Runtime v2 过期工作
9. 运行 extension startup hooks
10. 启动 adapters、heartbeat worker 和 subagent supervisor

约束：

- 用户侧业务入口优先通过 extension runtime 注入
- 不要把新的 channel、skill、plugin 注册逻辑写回 `src/main.py`
- Core 只保留平台无关的运行时能力和状态边界

## 管理命令

常用聊天内命令：

- `/start`
- `/new`
- `/help`
- `/chatlog`
- `/compact`
- `/stop`
- `/heartbeat`
- `/task`
- `/model`
- `/usage`
- `/skills`
- `/reload_skills`
- `/acc`
- `/credential`
- `/wxbind`

平台特有：

- Telegram 保留 `/feature`
- Telegram skill 管理流包含 `/teach`
- `/wxbind` 由 Weixin channel extension 注册，可在管理员链路中使用

## Web/API

部署后访问 Web：

- 健康检查：`GET /api/v1/health`
- 管理初始化：`/login`
- 运行配置：`/admin/runtime`
- 模型配置：`/admin/models`
- 诊断信息：`GET /api/v1/admin/diagnostics`
- 会话工作台：Web chat sessions API 与前端工作台共享 Runtime v2 session

部署、systemd、Docker、前端构建和平台接入说明见 [DEPLOYMENT.md](DEPLOYMENT.md)。

## 开发与测试

Runtime v2 的回归证据统一记录在 [docs/runtime_v2_test_ledger.md](docs/runtime_v2_test_ledger.md)。新增运行时行为时，应补一条能证明真实路径的测试，而不是只做静态检查。

常用验证：

```bash
uv run python -m pytest tests/core/test_runtime_v2.py
uv run python -m pytest tests/core/test_web_chat_api_runtime_v2.py
uv run python -m pytest tests/core/test_scheduler_runtime_reload.py
uv run python -m pytest tests/core/test_admin_diagnostics_runtime_v2.py
```

轻量检查：

```bash
git diff --check
python -m py_compile src/core/runtime_v2.py src/core/agents/assistant.py src/core/scheduler.py
```

## 当前维护原则

- README 只描述当前实现和近期开启的运行边界，不保留未落地的旧架构叙述。
- Runtime v2 是新的中心状态层；旧 `task_inbox`、heartbeat active task 等只作为兼容桥存在，不继续扩展为主路径。
- channel 不解析模型文本来猜附件；文件统一走 artifact + delivery receipt。
- Agents SDK 是唯一聊天运行时；coding backend 仍由 coding session skill 按需选择。
- scheduler 的配置、运行和会话要收敛，避免 watcher、reload、reconcile 各自维护一套事实。
- 新增核心运行时能力必须补测试，并更新 `docs/runtime_v2_test_ledger.md`。

## 相关文档

- 架构与开发边界：[DEVELOPMENT.md](DEVELOPMENT.md)
- 部署与运维：[DEPLOYMENT.md](DEPLOYMENT.md)
- Runtime v2 测试台账：[docs/runtime_v2_test_ledger.md](docs/runtime_v2_test_ledger.md)
