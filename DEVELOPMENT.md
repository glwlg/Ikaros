# X-Bot DEVELOPMENT

更新时间：2026-03-17  
状态：`ACTIVE`

本文描述当前仓库已经落地的运行时边界与开发约束，默认以现有代码为准。

## 1. 当前系统形态

X-Bot 当前是两类进程：

- `x-bot`：唯一用户可见的 Core Manager
- `x-bot-api`：FastAPI + SPA

Manager 运行在宿主机或单容器内，必要时在同进程内启动受控 `subagent` 做并发执行。  
`subagent` 不是独立部署单元，也不是直接对用户交付结果的 agent。

## 2. 职责边界

### 2.1 Core Manager

Manager 负责：

- 平台消息入口和命令入口
- 提示词、SOUL、上下文、工具面组装
- 任务治理、heartbeat、记忆、权限控制
- 直接执行普通任务
- 在需要并发或隔离风险时启动内部 `subagent`
- 统一接收 `subagent` 结果并决定继续、降级、重试、等待用户或最终交付
- 编码会话、仓库工作区、git/gh 发布与本地 rollout

Manager 的基础原语：

- `read`
- `write`
- `edit`
- `bash`
- `load_skill`

Manager 内部控制面工具：

- `spawn_subagent`
- `await_subagents`

Manager 侧常用 direct tool：

- `repo_workspace`
- `codex_session`
- `git_ops`
- `gh_cli`
- `task_tracker`

约束：

- 用户最终只和 Manager 对话
- `subagent` 不能直接向平台发消息
- `subagent` 只能使用 Manager 显式分配的工具与技能
- `subagent` 失败后必须先回 Manager 决策，不能直接把原始失败结果当作最终交付

### 2.2 Internal Subagent

`subagent` 负责：

- 执行一个边界清晰的子任务
- 在受控工具集内完成局部目标
- 返回结构化结果、附件和诊断信息

`subagent` 不负责：

- 直接面向用户回复
- 继续拆分出新的 `subagent`
- 自己决定任务闭环是否成立

### 2.3 API Service

`x-bot-api` 负责：

- `/api/v1/*` 路由
- auth、binding、accounting 等 Web/API 能力
- 前端静态资源和 SPA fallback

## 3. 代码结构

```text
src/
├── api/          # FastAPI + SPA
├── core/         # orchestrator、prompt、tool/runtime、state/task/subagent
├── handlers/     # 用户命令与消息入口
├── manager/      # manager 侧开发/规划/闭环服务
├── platforms/    # Telegram / Discord / DingTalk 适配
├── services/     # LLM、下载、搜索等外部服务
└── shared/       # 通用契约与跨模块共享类型
```

关键入口：

- `src/main.py`：Manager 主程序
- `src/api/main.py`：API 主程序
- `src/core/agent_orchestrator.py`：LLM function-call 编排
- `src/core/orchestrator_runtime_tools.py`：工具装配与执行策略
- `src/core/subagent_supervisor.py`：内部 `subagent` 启动、等待、后台交付
- `src/manager/relay/closure_service.py`：阶段任务闭环、waiting_user/next_stage/final 决策
- `src/manager/dev/workspace_session_service.py`：repo workspace / worktree 管理
- `src/manager/dev/codex_session_service.py`：Manager 编码会话
- `src/manager/dev/git_ops_service.py`：git 状态/提交/push/fork

## 4. 调度模型

### 4.1 Manager-First

- 普通请求默认由 Manager 直接处理
- 当且仅当存在并发收益或风险隔离需求时，Manager 才启动 `subagent`
- `subagent` 运行在同一进程内，由 `SubagentSupervisor` 托管

### 4.2 Tool Scope

- Manager 启动 `subagent` 时必须同时指定 `allowed_tools`
- 若需要 skill，必须同时指定 `allowed_skills`
- runtime tool assembler / dispatcher 会在运行时再做一层显式白名单过滤

### 4.3 后台任务

- 后台任务仍写入 `task_inbox`
- metadata 使用：
  - `executor_type=subagent`
  - `subagent_ids`
  - `tool_scope`
- 后台结果先回 Manager 闭环，再由 Manager 统一推送文本和附件

## 5. Task/Heartbeat 语义

- `completed`：任务真正完成并可交付
- `waiting_user`：当前阻塞，需要用户补充或确认
- `waiting_external`：依赖外部世界变化，不应误判为完成
- `heartbeat`：主动回顾未闭环任务，决定是否提醒、继续或维持等待

约束：

- 不要把某个中间动作完成误写成 `completed`
- heartbeat 自动推进前必须先通知用户
- `/task` 是后台任务的统一可见入口

## 6. Skill 系统

Skill 仍是运行时扩展，放在：

- `skills/builtin/`
- `skills/learned/`

标准调用链：

1. 模型调用 `load_skill`
2. 读取 `SKILL.md`
3. 按 SOP 用 `bash` 执行 `python scripts/execute.py ...`

若 skill frontmatter 声明 `tool_exports`，则可以被动态注入为 direct tool。  
Manager 是否给 `subagent` 分配某个 skill，由 `allowed_skills` 决定。

## 7. 正式开发链路

仓库开发优先走：

- `repo_workspace`
- `codex_session`
- `git_ops`
- `gh_cli`

约束：

- 优先独立 worktree，不要在脏工作区里直接切分支
- 若任务在编码、发布或外部系统交互后仍未闭环，必须保留未完成状态并写清完成条件

## 8. 部署约束

- `docker-compose.yml` 只保留 `x-bot` 与 `x-bot-api`
- 不再存在独立 `worker` 容器
- 推荐把主 bot 作为宿主机长进程运行；Docker 主要承载 API 或可选基础设施

## 9. 反模式

- 不要重新引入独立 worker runtime、dispatch queue 或 result relay 主路径
- 不要让 `subagent` 直接做用户交付闭环
- 不要把 `spawn_subagent` 当成默认执行路径
- 不要绕过 `state_store` / `state_paths` 直接拼运行态文件路径
- 不要把 direct tool 大量重新写死回核心注册表，优先通过 skill metadata 导出

## 10. 常用命令

```bash
uv sync
uv run python src/main.py
uv run pytest
docker compose up --build -d
docker compose logs -f x-bot
```

## 11. 高信号测试

- `tests/core/test_orchestrator_single_loop.py`
- `tests/core/test_runtime_tool_skillization.py`
- `tests/core/test_prompt_composer.py`
- `tests/manager/test_closure_service.py`
- `tests/core/test_start_handlers_stop.py`
