# X-Bot

X-Bot 是一个 Python 多平台 AI Bot，当前采用 `Core Manager + API Service` 架构。

- `x-bot`：唯一用户可见的 Core Manager，负责平台接入、对话入口、任务治理、技能执行、心跳、记忆、模型路由与开发工具链
- `x-bot-api`：FastAPI + SPA，提供 Web/API 能力

运行时状态统一落在 `data/` 下，主体仍是文件系统优先；需要聚合查询的部分使用 `data/bot_data.db` 做 SQLite 存储。

![logo](logo.png)

## 当前能力

- 多平台接入：Telegram、Discord、钉钉 Stream、微信 iLink（MVP），以及独立 Web/API 服务
- 多模态交互：文本、图片、视频、语音、文档输入
- Skill 体系：技能位于 `skills/`，通过 `SKILL.md` 描述 SOP、参数契约和可导出的 direct tool
- 任务治理：真实任务具备 task/session/heartbeat 闭环，普通闲聊不写入 `task_inbox`
- 模型配置：统一使用 `config/models.json`，支持在聊天内通过 `/model` 查看和切换
- LLM 用量统计：通过 `/usage` 查看按天 + 会话 + 模型聚合的 token 使用；数据持久化到 `data/bot_data.db`
- Manager 开发链路：仓库类任务优先使用 `repo_workspace`、`codex_session`、`git_ops`、`gh_cli`

## 架构概览

### 1. Core Manager

Manager 是当前系统的统一入口，负责：

- 接收平台消息和命令
- 组装提示词、SOUL、上下文和工具面
- 路由请求、缩圈 skill、维护 task/session/heartbeat
- 执行普通用户请求
- 在必要时启动同进程内的受控 `subagent`
- 统一接收 `subagent` 结果并决定继续、等待、降级或最终交付

### 2. API Service

`x-bot-api` 负责：

- `/api/v1/*` 路由
- Web 认证、绑定、记账等 API 能力
- 前端静态资源与 SPA fallback

### 3. Skills

Skill 是一等运行时扩展，位于：

- `skills/builtin/`
- `skills/learned/`

标准调用路径：

1. 模型调用 `load_skill`
2. 读取 `SKILL.md`
3. 按 SOP 使用 `bash` 执行 `scripts/execute.py`

如果 skill 在 frontmatter 中声明了 `tool_exports`，还可以被动态注入为 direct tool。

## 目录结构

```text
.
├── src/
│   ├── api/          # FastAPI + SPA
│   ├── core/         # 编排、提示词、工具装配、状态访问
│   ├── handlers/     # 命令和消息入口
│   ├── manager/      # manager 侧开发/规划/闭环服务
│   ├── platforms/    # Telegram / Discord / DingTalk 适配层
│   ├── services/     # AI、下载、搜索等外部服务集成
│   └── shared/       # 跨模块通用契约与共享类型
├── skills/           # builtin + learned skills
├── data/             # 运行时状态与持久化数据
├── config/           # 结构化运行配置
├── tests/            # pytest 测试
├── docker-compose.yml
├── README.md
└── DEVELOPMENT.md
```

## 快速开始

### 1. 准备配置

```bash
cp .env.example .env
cp config/models.example.json config/models.json
```

`.env` 里至少按需填写：

- `TELEGRAM_BOT_TOKEN`
- `DISCORD_BOT_TOKEN`
- `DINGTALK_CLIENT_ID`
- `DINGTALK_CLIENT_SECRET`
- `WEIXIN_ENABLE`
- `ADMIN_USER_IDS`
- `SEARXNG_URL`

如需自定义模型配置文件位置，可设置：

```bash
MODELS_CONFIG_PATH="/absolute/path/to/models.json"
```

### 2. 配置模型

模型配置统一使用 `config/models.json`，主要包含三部分：

1. 当前角色模型
   - `model.primary`
   - `model.routing`
   - `model.vision`
   - `model.image_generation`
   - `model.voice`
2. 角色模型池
   - `models.primary`
   - `models.routing`
   - `models.vision`
   - `models.image_generation`
   - `models.voice`
3. provider 连接信息
   - `providers.<provider>.baseUrl`
   - `providers.<provider>.apiKey`
   - `providers.<provider>.api`
   - `providers.<provider>.models[]`

其中：

- `vision` 用于看图、看视频、识别表情包等多模态理解
- `image_generation` 用于文生图
- 旧键 `model.image` 仍保留兼容，但新配置应优先使用 `model.vision`

### 3. 安装依赖

```bash
uv sync
```

### 4. 启动

本地直接运行 Manager：

```bash
uv run python src/main.py
```

本地运行 API：

```bash
uv run uvicorn api.main:app --host 0.0.0.0 --port 8764
```

Docker 方式：

```bash
docker compose up --build -d
docker compose logs -f x-bot
docker compose logs -f x-bot-api
```

## 聊天内管理命令

当前默认注册的常用命令包括：

- `/start`
- `/new`
- `/help`
- `/chatlog`
- `/compact`
- `/skills`
- `/reload_skills`
- `/stop`
- `/heartbeat`
- `/task`
- `/acc`
- `/model`
- `/usage`

Telegram 额外保留：

- `/feature`
- `/teach`

### `/model`

`/model` 用于查看和切换当前模型配置，支持文本命令和按钮菜单。

常用形式：

- `/model`
- `/model show`
- `/model list`
- `/model list <role>`
- `/model use <provider/model>`
- `/model use <role> <provider/model>`

支持角色：

- `primary`
- `routing`
- `vision`
- `image_generation`
- `voice`

在 Telegram 等支持按钮的平台上，`/model` 会优先展示可点击菜单，适合手机端切换。

### `/usage`

`/usage` 用于查看 LLM 用量统计。统计口径：

- 按 `天 + 会话 + 模型` 聚合
- 所有通过 `get_client_for_model(...)`、`openai_async_client`、`openai_client` 发起的 OpenAI 兼容调用都会记账
- 上游返回 `usage` 时使用真实 token
- 上游未返回 `usage` 时，输入/输出 token 使用本地估算
- 缓存命中与缓存写入只统计上游实际返回值

常用形式：

- `/usage`
- `/usage today`
- `/usage reset`

统计数据写入：

- `data/bot_data.db`

当前覆盖的接口包括：

- `chat.completions.create`
- `responses.create`
- `embeddings.create`
- `audio.transcriptions.create`
- `audio.speech.create`
- `images.generate`
- `images.edit`
- `images.variations`

## 运行时目录

- `data/`：聊天、任务、记忆、心跳、审计、SQLite 聚合数据等运行时状态
- `data/bot_data.db`：Web/API 与 LLM 用量等聚合型 SQLite 数据
- `downloads/`：媒体下载产物
- `skills/`：技能源码与 learned skills
- `config/`：结构化运行配置，当前主要包括 `models.json` 和 `deployment_targets.yaml`

## 当前维护原则

- 文档以当前实现为准，不保留未落地的旧架构描述
- 普通用户执行统一走 Core Manager，不重新引入独立 Worker 执行面
- 代码类改动默认走 manager 原子工具链：`repo_workspace`、`codex_session`、`git_ops`、`gh_cli`
- 新增可直接暴露给模型的 skill tool，优先通过 `SKILL.md` 的 `tool_exports` 声明，而不是改核心硬编码
- 聚合统计优先使用有界表或按日分片，不再依赖单个无限增长的 `events.jsonl`

## 开发文档

- 架构与边界约束：[DEVELOPMENT.md](DEVELOPMENT.md)
- Web 搜索配置：[docs/web_search_config.md](docs/web_search_config.md)
