---
api_version: v3
name: scheduler_manager
description: 管理周期性定时任务（Cron），支持添加、查看、删除任务。
triggers:
- schedule
- cron
- task
- 定时任务
- 周期任务
- 自动运行
- 周期执行
- 每天
- 每小时
policy_groups:
- automation
platform_handlers: true
input_schema:
  type: object
  properties: {}
permissions:
  filesystem: workspace
  shell: true
  network: limited
entrypoint: scripts/execute.py
---

# Scheduler Manager

这是周期任务调度 skill。通过 `bash` 执行 CLI，不要再描述旧的“内置动作”。

## Commands

- 添加任务：`python scripts/execute.py add --crontab "0 8 * * *" --instruction "查询北京天气" --push true`
- 添加带日期模板的任务：`python scripts/execute.py add --crontab "0 8 * * *" --instruction "写一篇 {{date:%-m月%-d日}} 全球AI快讯" --push true`
- 仅工作日：`python scripts/execute.py add --crontab "0 8 * * *" --instruction "工作日早报" --run-calendar weekdays --push true`
- 仅 A 股交易日：`python scripts/execute.py add --crontab "0 8 * * *" --instruction "交易日任务" --run-calendar trading_days --push true`
- 列出任务：`python scripts/execute.py list`
- 删除任务：`python scripts/execute.py delete <task_id>`

## Rules

- 周期性或自动运行需求都走这里，不走 `reminder`。
- `instruction` 尽量保留用户原始意图，不要过度总结。
- `run_calendar` 支持：`always`（默认）、`weekdays`（周一至周五）、`trading_days`（A 股交易日，排除法定节假日，含调休上班日）。cron 仍可写 `* * *`，非匹配日会在触发时直接跳过。
- `instruction` 支持在触发时渲染日期/时间模板：`{{date}}`/`{{today}}` 输出 `YYYY-MM-DD`，`{{date:%-m月%-d日}}` 输出中文月日，`{{date-1:%Y-%m-%d}}` 表示昨天，`{{date+1:%Y-%m-%d}}` 表示明天，`{{now:%H:%M}}` 输出当前时间。需要标题或正文包含当天日期时，优先把日期写成模板表达式，而不是让执行模型临场猜。
