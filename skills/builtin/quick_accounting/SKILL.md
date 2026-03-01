---
api_version: v3
name: quick_accounting
description: "智能记账工具。当用户发送支付截图（如微信支付、支付宝截图）或发送一段包含消费/收入的文本时，请自动识别金额、分类、账户、时间和商家等信息并调用本工具来记账。支持支出、收入和转账。**提取信息后请务必调用本工具写入数据库**。"
triggers:
- 记账
- 消费
- 支付
- 收款
- 转账
- spend
- income
input_schema:
  type: object
  properties:
    type:
      type: string
      description: "记录类型，可选值：支出、收入、转账"
      enum: ["支出", "收入", "转账"]
    amount:
      type: number
      description: "交易金额，必须为正数"
    category:
      type: string
      description: "交易分类，如餐饮、交通、购物、回款等。如果无法判断可以填'未分类'"
    account:
      type: string
      description: "付款或收款账户名称，如：微信、支付宝、工商银行等"
    target_account:
      type: string
      description: "如果是转账，此项为收款账户名称；如果是普通收支则留空"
    payee:
      type: string
      description: "交易方（商家名称或付款人/收款人姓名），如：麦当劳、张三"
    remark:
      type: string
      description: "其他补充备注信息，如购买的具体商品等"
    record_time:
      type: string
      description: "交易时间，格式为 YYYY-MM-DD HH:MM:SS，如果截图或文本没有提供时间则留空"
  required: ["type", "amount", "category", "account"]
permissions:
  filesystem: workspace
  shell: false
  network: none
entrypoint: scripts/execute.py
---

# 记账助手 (Quick Accounting)

你可以作为一个私人财务管家，帮助用户智能分析截图并记账。

## 场景识别
- 当用户发来一张带有金额和商家名称等交易明细的截图（通常是微信、支付宝支付成功或账单详情页面）。
- 当用户发来说“今天中午吃麦当劳花了30块微信支付”之类的话。

## 信息提取策略
1. **类型(`type`)**: 支付给别人是“支出”，收到退款或工资是“收入”，自己卡给自己卡是“转账”。
2. **金额(`amount`)**: 提取关键数字，如果带有 ¥ 符号请去除。
3. **分类(`category`)**: 观察商家名称推测。例如“外卖”、“餐饮”、“交通卡充值”、“便利店”。如果不确定可以填“未分类”。
4. **账户(`account`)**: 这是用户出钱/进钱的地方，比如“微信”、“支付宝”、“招商银行借记卡”、“零钱”。
5. **商家(`payee`)**: 可以直接使用截图上的“收款方”、“交易对方”或“商户单号”前的商店缩写。
6. **时间和备注(`record_time`, `remark`)**: 尽可能提取，补充到字段中。时间应转换为 `YYYY-MM-DD HH:MM:SS` 格式（如 2024-03-01 12:30:00）。
