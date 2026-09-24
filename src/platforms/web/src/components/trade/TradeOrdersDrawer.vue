<script setup lang="ts">
import { ref, watch } from 'vue'
import { X, History, Loader2, ArrowDownRight, ArrowUpRight } from 'lucide-vue-next'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import { getTradeOrders, type TradeOrder } from '@/api/trade'

const props = defineProps<{
  visible: boolean
  accountId?: number | null
  accountName?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const panelOptics = {
  mapSize: 256,
  strength: 0.08,
  depth: 0.8,
  dispersion: 0.5,
  frost: 4,
  saturate: 1.2,
  specular: 1.2,
  glow: 0.25,
  sheen: 0.9,
  curvature: 0.4,
  bend: 0.65,
}

const loading = ref(false)
const orders = ref<TradeOrder[]>([])

const loadOrders = async () => {
  loading.value = true
  try {
    const res = await getTradeOrders({
      account_id: props.accountId || undefined,
      limit: 50,
    })
    orders.value = res.data || []
  } catch (err) {
    console.error('加载交易流水失败', err)
  } finally {
    loading.value = false
  }
}

watch(
  () => props.visible,
  (val) => {
    if (val) {
      loadOrders()
    }
  }
)
</script>

<template>
  <div v-if="props.visible" class="modal-backdrop" @click.self="emit('close')">
    <LiquidGlass :radius="20" :optics="panelOptics" class="modal-panel">
      <header class="modal-head">
        <div class="head-title">
          <History :size="18" />
          <h3>交易历史流水 · {{ props.accountName || '全部账户' }}</h3>
        </div>
        <button type="button" class="close-btn" @click="emit('close')"><X :size="16" /></button>
      </header>

      <div class="modal-body">
        <div v-if="loading" class="loading-state">
          <Loader2 class="is-spinning" :size="20" />
          <span>正在加载流水明细...</span>
        </div>

        <div v-else-if="!orders.length" class="empty-state">
          <span>暂无历史交易交割记录</span>
        </div>

        <div v-else class="orders-list">
          <div v-for="order in orders" :key="order.id" class="order-card">
            <div class="order-header">
              <div class="order-stock">
                <span
                  class="type-badge"
                  :class="order.trade_type === 'buy' ? 'is-buy' : 'is-sell'"
                >
                  <ArrowDownRight v-if="order.trade_type === 'buy'" :size="12" />
                  <ArrowUpRight v-else :size="12" />
                  {{ order.trade_type === 'buy' ? '买入加仓' : '卖出减仓' }}
                </span>
                <strong>{{ order.stock_name }}</strong>
                <small class="stock-code">{{ order.stock_code }}</small>
              </div>
              <time class="order-time">{{ order.transacted_at ? new Date(order.transacted_at).toLocaleDateString() : '--' }}</time>
            </div>

            <div class="order-details">
              <div class="detail-cell">
                <span class="label">成交价</span>
                <strong>¥ {{ order.price.toFixed(2) }}</strong>
              </div>
              <div class="detail-cell">
                <span class="label">成交量</span>
                <strong>{{ order.quantity }} 股</strong>
              </div>
              <div class="detail-cell">
                <span class="label">手续费</span>
                <span>¥ {{ order.total_fee.toFixed(2) }}</span>
              </div>
              <div class="detail-cell">
                <span class="label">{{ order.trade_type === 'buy' ? '扣款额' : '回款额' }}</span>
                <strong class="value-net">¥ {{ order.net_amount.toFixed(2) }}</strong>
              </div>
            </div>

            <div v-if="order.trade_type === 'sell'" class="pnl-summary">
              <span>该笔已实现盈亏：</span>
              <strong :class="order.realized_pnl >= 0 ? 'is-up' : 'is-down'">
                {{ order.realized_pnl >= 0 ? '+' : '' }}¥ {{ order.realized_pnl.toFixed(2) }}
              </strong>
            </div>

            <div v-if="order.notes" class="order-notes">
              备注：{{ order.notes }}
            </div>
          </div>
        </div>
      </div>

      <footer class="modal-foot">
        <button type="button" class="btn-secondary" @click="emit('close')">关闭</button>
      </footer>
    </LiquidGlass>
  </div>
</template>

<style scoped>
.modal-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(6px);
}

.modal-panel {
  width: min(600px, 100%);
  max-height: 85vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--ikaros-line);
  flex-shrink: 0;
}

.head-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ikaros-ink);
}

.head-title h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
}

.close-btn {
  background: transparent;
  border: 0;
  cursor: pointer;
  color: var(--ikaros-muted);
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
  display: grid;
  gap: 12px;
}

.loading-state,
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 0;
  gap: 10px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.orders-list {
  display: grid;
  gap: 10px;
}

.order-card {
  display: grid;
  gap: 8px;
  padding: 12px 14px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.4);
  border: 1px solid var(--ikaros-line);
}

.order-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.order-stock {
  display: flex;
  align-items: center;
  gap: 8px;
}

.type-badge {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 700;
}

.type-badge.is-buy {
  background: rgba(220, 38, 38, 0.1);
  color: #dc2626;
}

.type-badge.is-sell {
  background: rgba(22, 163, 74, 0.1);
  color: #16a34a;
}

.stock-code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--ikaros-muted);
  font-size: 11px;
}

.order-time {
  font-size: 11px;
  color: var(--ikaros-muted);
}

.order-details {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  padding: 6px 0;
  border-top: 1px dashed var(--ikaros-line);
  font-size: 12px;
}

.detail-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.detail-cell .label {
  font-size: 10px;
  color: var(--ikaros-muted);
}

.pnl-summary {
  font-size: 12px;
  color: var(--ikaros-muted);
}

.pnl-summary strong.is-up {
  color: #dc2626;
}

.pnl-summary strong.is-down {
  color: #16a34a;
}

.order-notes {
  font-size: 11px;
  color: var(--ikaros-muted);
  font-style: italic;
}

.modal-foot {
  display: flex;
  justify-content: flex-end;
  padding: 12px 20px;
  border-top: 1px solid var(--ikaros-line);
  flex-shrink: 0;
}

.btn-secondary {
  padding: 6px 16px;
  border-radius: 8px;
  border: 1px solid var(--ikaros-line);
  background: transparent;
  color: var(--ikaros-muted);
  font-weight: 600;
  cursor: pointer;
}

.is-spinning {
  animation: spin 850ms linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
