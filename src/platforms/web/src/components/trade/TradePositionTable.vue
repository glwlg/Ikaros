<script setup lang="ts">
import { Calculator, ArrowDownRight, ArrowUpRight, TrendingUp } from 'lucide-vue-next'
import type { TradePosition } from '@/api/trade'

const props = defineProps<{
  positions: TradePosition[]
  loading: boolean
}>()

const emit = defineEmits<{
  (e: 'buy', position: TradePosition): void
  (e: 'sell', position: TradePosition): void
  (e: 'simulate', position: TradePosition): void
}>()

const pnlClass = (val: number) => {
  if (val > 0) return 'is-up'
  if (val < 0) return 'is-down'
  return ''
}
</script>

<template>
  <div class="position-table-wrap">
    <div v-if="props.loading" class="table-loading">正在加载持仓...</div>
    <div v-else-if="!props.positions.length" class="table-empty">
      <TrendingUp :size="32" />
      <p>当前账户暂无持仓标的</p>
    </div>
    <table v-else class="trade-table">
      <thead>
        <tr>
          <th>标的代码 / 名称</th>
          <th class="is-num">现价</th>
          <th class="is-num">涨跌幅</th>
          <th class="is-num">持仓量</th>
          <th class="is-num">成本均价</th>
          <th class="is-num">持仓市值</th>
          <th class="is-num">浮动盈亏</th>
          <th class="is-num">当日盈亏</th>
          <th class="is-num">仓位权重</th>
          <th class="is-actions">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="pos in props.positions" :key="pos.id">
          <td>
            <div class="stock-info">
              <strong>{{ pos.stock_name }}</strong>
              <small class="code">{{ pos.stock_code }}</small>
            </div>
          </td>
          <td class="is-num">
            <strong :class="pnlClass(pos.change)">
              {{ pos.current_price > 0 ? pos.current_price.toFixed(2) : '--' }}
            </strong>
          </td>
          <td class="is-num">
            <span class="badge-percent" :class="pnlClass(pos.percent)">
              {{ pos.percent > 0 ? '+' : '' }}{{ pos.percent.toFixed(2) }}%
            </span>
          </td>
          <td class="is-num">{{ pos.quantity }} 股</td>
          <td class="is-num">¥ {{ pos.cost_price.toFixed(4) }}</td>
          <td class="is-num">¥ {{ pos.market_value.toFixed(2) }}</td>
          <td class="is-num" :class="pnlClass(pos.unrealized_pnl)">
            <strong>{{ pos.unrealized_pnl > 0 ? '+' : '' }}¥ {{ pos.unrealized_pnl.toFixed(2) }}</strong>
            <div class="sub-ratio">({{ pos.unrealized_pnl_percent > 0 ? '+' : '' }}{{ pos.unrealized_pnl_percent }}%)</div>
          </td>
          <td class="is-num" :class="pnlClass(pos.today_pnl)">
            {{ pos.today_pnl > 0 ? '+' : '' }}¥ {{ pos.today_pnl.toFixed(2) }}
          </td>
          <td class="is-num">{{ pos.weight_percent ?? 0 }}%</td>
          <td class="is-actions">
            <div class="actions-row">
              <button type="button" class="action-btn is-buy" title="加仓记账" @click="emit('buy', pos)">
                <ArrowDownRight :size="13" />
                买入
              </button>
              <button type="button" class="action-btn is-sell" title="减仓记账" @click="emit('sell', pos)">
                <ArrowUpRight :size="13" />
                卖出
              </button>
              <button type="button" class="action-btn is-sim" title="调仓试算" @click="emit('simulate', pos)">
                <Calculator :size="13" />
                试算
              </button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.position-table-wrap {
  width: 100%;
  overflow-x: auto;
}

.table-loading,
.table-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  gap: 10px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.trade-table {
  width: 100%;
  min-width: 900px;
  font-size: 13px;
  border-collapse: collapse;
}

.trade-table th {
  padding: 10px 14px;
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 600;
  text-align: left;
  border-bottom: 1px solid var(--ikaros-line);
  white-space: nowrap;
}

.trade-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--ikaros-line);
  color: var(--ikaros-ink);
  white-space: nowrap;
}

.trade-table th.is-num,
.trade-table td.is-num {
  text-align: right;
}

.trade-table th.is-actions,
.trade-table td.is-actions {
  text-align: center;
}

.stock-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.stock-info strong {
  font-size: 13px;
  font-weight: 700;
}

.stock-info .code {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  color: var(--ikaros-muted);
}

.badge-percent {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
}

.badge-percent.is-up {
  background: rgba(220, 38, 38, 0.08);
  color: #dc2626;
}

.badge-percent.is-down {
  background: rgba(22, 163, 74, 0.08);
  color: #16a34a;
}

.is-up {
  color: #dc2626;
}

.is-down {
  color: #16a34a;
}

.sub-ratio {
  font-size: 11px;
  font-weight: 500;
}

.actions-row {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--ikaros-line);
  background: transparent;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  transition: all 140ms ease;
}

.action-btn.is-buy:hover {
  border-color: #dc2626;
  color: #dc2626;
  background: rgba(220, 38, 38, 0.05);
}

.action-btn.is-sell:hover {
  border-color: #16a34a;
  color: #16a34a;
  background: rgba(22, 163, 74, 0.05);
}

.action-btn.is-sim:hover {
  border-color: var(--ikaros-pink);
  color: var(--ikaros-pink);
  background: rgba(232, 93, 142, 0.05);
}
</style>
