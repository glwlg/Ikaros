---
api_version: v3
name: teslamate
description: "TeslaMate 只读车况助手。查询 TeslaMate PostgreSQL 数据库里的车辆电量、最新车况、行程、充电记录和近期统计。"
triggers:
- teslamate
- TeslaMate
- 特斯拉
- 电量
- 车况
- 行程
- 开车
- 驾驶
- 车程
- 轨迹
- 去了哪里
- 最近去哪
- 行驶记录
- 充电
allowed_roles:
- ikaros
policy_groups:
- management
- integration
platform_handlers: false
tool_exports:
- name: teslamate_query
  description: Query TeslaMate for vehicle battery/status, recent drives, charges, and summary statistics.
  prompt_hint: 用户询问 TeslaMate、特斯拉车辆电量、车况、最近行程、开车去了哪里、驾驶轨迹、行驶记录、充电记录、近期里程或用车统计时，调用 `teslamate_query`。这是只读查询，不会写入 TeslaMate 数据库。
  policy_groups:
  - integration
  parameters:
    type: object
    properties:
      action:
        type: string
        description: status | drives | charges | summary
      car_id:
        type: integer
        description: Optional TeslaMate cars.id filter
      car_name:
        type: string
        description: Optional car name, VIN, or model fuzzy filter
      limit:
        type: integer
        description: Max rows for drives/charges, 1-20
      days:
        type: integer
        description: Summary window in days, 1-365
input_schema:
  type: object
  properties:
    action:
      type: string
      enum: ["status", "drives", "charges", "summary"]
    car_id:
      type: integer
    car_name:
      type: string
    limit:
      type: integer
    days:
      type: integer
permissions:
  filesystem: workspace
  shell: true
  network: limited
entrypoint: scripts/execute.py
---

# TeslaMate

通过 TeslaMate 的 PostgreSQL 数据库做只读查询，支持车辆电量、最近行程、充电记录和近期统计。

## 配置

优先设置完整连接串：

```bash
export TESLAMATE_DATABASE_URL="postgresql://teslamate:password@127.0.0.1:5432/teslamate"
```

也可以拆成环境变量：

```bash
export TESLAMATE_DB_HOST=127.0.0.1
export TESLAMATE_DB_PORT=5432
export TESLAMATE_DB_NAME=teslamate
export TESLAMATE_DB_USER=teslamate
export TESLAMATE_DB_PASSWORD=password
```

建议在 TeslaMate PostgreSQL 中单独建一个只读账号给 Ikaros 使用。

## Commands

- `python scripts/execute.py status`
- `python scripts/execute.py drives --limit 5`
- `python scripts/execute.py charges --limit 5`
- `python scripts/execute.py summary --days 30`
- `python scripts/execute.py status --car-name Model`

## 行为

- `status`：查询车辆最新电量、状态、续航、里程和最后更新时间。
- `drives`：查询最近行程，包含时间、距离、时长、起止地点和电量变化。
- `charges`：查询最近充电记录，包含电量变化、增加电量、耗电、时长、费用和地点。
- `summary`：聚合最近 N 天的里程、驾驶时长、充电次数和充电电量。
