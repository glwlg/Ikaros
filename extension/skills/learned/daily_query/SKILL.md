---
api_version: v3
name: daily_query
description: 提供日常基础查询能力，支持天气、时间、加密货币价格和法币汇率。
triggers:
- 天气
- weather
- 气温
- condition
- time
- 时间
input_schema:
  type: object
  properties:
    query_type:
      type: string
      enum: ["weather", "time", "crypto", "currency"]
    location:
      type: string
    symbol:
      type: string
  required:
    - query_type
tool_exports:
  - name: daily_query
    description: 查询天气、时间、加密货币价格和法币汇率。
    prompt_hint: 用户询问天气、时间、币价或汇率时，直接调用 `daily_query`。
    parameters:
      type: object
      properties:
        query_type:
          type: string
          enum: ["weather", "time", "crypto", "currency"]
          description: 查询类型。
        location:
          type: string
          description: 天气地点，例如无锡、无锡滨湖区、Tokyo。
        symbol:
          type: string
          description: 币种或法币代码，例如 BTC、ETH、USD。
      required:
        - query_type
platform_handlers: true
permissions:
  filesystem: workspace
  shell: true
  network: limited
entrypoint: scripts/execute.py
---

# Daily Query

这是日常基础查询 skill。能直接给结果时，优先用它，不要为了天气或时间之类的问题走复杂网页搜索。

## Commands

- 天气：`python scripts/execute.py weather [location]`
- 加密货币：`python scripts/execute.py crypto [symbol]`
- 汇率：`python scripts/execute.py currency [symbol]`
- 时间：`python scripts/execute.py time`

## Examples

- `python scripts/execute.py weather 无锡`
- `python scripts/execute.py crypto BTC`
- `python scripts/execute.py currency USD`
- `python scripts/execute.py time`
