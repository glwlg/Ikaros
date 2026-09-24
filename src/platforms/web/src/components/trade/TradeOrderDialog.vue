<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { X, ArrowDownRight, ArrowUpRight, ChevronDown, ChevronUp } from 'lucide-vue-next'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import type { TradeAccount, TradePosition } from '@/api/trade'

const props = defineProps<{
  visible: boolean
  account: TradeAccount | null
  position?: TradePosition | null
  presetTradeType?: 'buy' | 'sell'
  submitting: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', payload: any): void
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

const tradeType = ref<'buy' | 'sell'>('buy')
const stockCode = ref('')
const stockName = ref('')
const price = ref<number | ''>('')
const quantity = ref<number | ''>('')
const notes = ref('')
const showCustomFees = ref(false)
const customCommission = ref<number | ''>('')
const customStampDuty = ref<number | ''>('')
const customTransferFee = ref<number | ''>('')

watch(
  () => [props.visible, props.position, props.presetTradeType],
  () => {
    if (props.visible) {
      tradeType.value = props.presetTradeType || 'buy'
      if (props.position) {
        stockCode.value = props.position.stock_code
        stockName.value = props.position.stock_name
        price.value = props.position.current_price > 0 ? props.position.current_price : props.position.cost_price
        quantity.value = tradeType.value === 'sell' ? props.position.quantity : 100
      } else {
        stockCode.value = ''
        stockName.value = ''
        price.value = ''
        quantity.value = 100
      }
      notes.value = ''
      showCustomFees.value = false
      customCommission.value = ''
      customStampDuty.value = ''
      customTransferFee.value = ''
    }
  },
  { immediate: true }
)

const tradeAmount = computed(() => {
  const p = Number(price.value || 0)
  const q = Number(quantity.value || 0)
  return Math.round(p * q * 100) / 100
})

const estimatedFees = computed(() => {
  if (!props.account || tradeAmount.value <= 0) {
    return { commission: 0, stampDuty: 0, transferFee: 0, totalFee: 0 }
  }
  const amt = tradeAmount.value
  const acc = props.account
  const comm = customCommission.value !== '' ? Number(customCommission.value) : Math.max(acc.min_commission, Math.round(amt * acc.commission_rate * 100) / 100)
  const stamp = customStampDuty.value !== '' ? Number(customStampDuty.value) : (tradeType.value === 'sell' ? Math.round(amt * acc.stamp_duty_rate * 100) / 100 : 0)
  const trans = customTransferFee.value !== '' ? Number(customTransferFee.value) : Math.round(amt * acc.transfer_fee_rate * 100) / 100
  const total = Math.round((comm + stamp + trans) * 100) / 100
  return { commission: comm, stampDuty: stamp, transferFee: trans, totalFee: total }
})

const netCashImpact = computed(() => {
  if (tradeAmount.value <= 0) return 0
  if (tradeType.value === 'buy') {
    return Math.round((tradeAmount.value + estimatedFees.value.totalFee) * 100) / 100
  } else {
    return Math.round((tradeAmount.value - estimatedFees.value.totalFee) * 100) / 100
  }
})

const canSubmit = computed(() => {
  if (!stockCode.value.trim() || !price.value || !quantity.value) return false
  if (Number(price.value) <= 0 || Number(quantity.value) <= 0) return false
  if (tradeType.value === 'buy' && props.account) {
    if (props.account.cash_balance < netCashImpact.value) return false
  }
  if (tradeType.value === 'sell' && props.position) {
    if (props.position.quantity < Number(quantity.value)) return false
  }
  return true
})

const handleSubmit = () => {
  if (!canSubmit.value || !props.account) return
  emit('save', {
    account_id: props.account.id,
    stock_code: stockCode.value.trim(),
    stock_name: stockName.value.trim() || stockCode.value.trim(),
    trade_type: tradeType.value,
    price: Number(price.value),
    quantity: Number(quantity.value),
    custom_commission: customCommission.value !== '' ? Number(customCommission.value) : undefined,
    custom_stamp_duty: customStampDuty.value !== '' ? Number(customStampDuty.value) : undefined,
    custom_transfer_fee: customTransferFee.value !== '' ? Number(customTransferFee.value) : undefined,
    notes: notes.value.trim() || undefined,
  })
}
</script>

<template>
  <div v-if="props.visible" class="modal-backdrop" @click.self="emit('close')">
    <LiquidGlass :radius="20" :optics="panelOptics" class="modal-panel">
      <header class="modal-head">
        <h3>交易记账 · {{ props.account?.name }}</h3>
        <button type="button" class="close-btn" @click="emit('close')"><X :size="16" /></button>
      </header>

      <div class="modal-body">
        <div class="type-switch">
          <button
            type="button"
            class="type-btn buy-btn"
            :class="{ 'is-active': tradeType === 'buy' }"
            @click="tradeType = 'buy'"
          >
            <ArrowDownRight :size="15" />
            <span>买入 (加仓)</span>
          </button>
          <button
            type="button"
            class="type-btn sell-btn"
            :class="{ 'is-active': tradeType === 'sell' }"
            @click="tradeType = 'sell'"
          >
            <ArrowUpRight :size="15" />
            <span>卖出 (减仓)</span>
          </button>
        </div>

        <div class="field-row">
          <div class="field-group">
            <label>标的代码</label>
            <input v-model="stockCode" type="text" placeholder="如 sh600519" :disabled="!!props.position" />
          </div>
          <div class="field-group">
            <label>标的名称</label>
            <input v-model="stockName" type="text" placeholder="如 贵州茅台" :disabled="!!props.position" />
          </div>
        </div>

        <div class="field-row">
          <div class="field-group">
            <label>成交单价 (元)</label>
            <input v-model.number="price" type="number" step="0.01" placeholder="成交单价" />
          </div>
          <div class="field-group">
            <label>成交数量 (股)</label>
            <input v-model.number="quantity" type="number" step="100" placeholder="100的整数倍" />
          </div>
        </div>

        <div class="calc-summary">
          <div class="calc-item">
            <span>成交总额</span>
            <strong>¥ {{ tradeAmount.toFixed(2) }}</strong>
          </div>
          <div class="calc-item">
            <span>预估手续费</span>
            <span>¥ {{ estimatedFees.totalFee.toFixed(2) }}</span>
          </div>
          <div class="calc-item highlight">
            <span>{{ tradeType === 'buy' ? '实际扣款金额' : '实际净回款' }}</span>
            <strong>¥ {{ netCashImpact.toFixed(2) }}</strong>
          </div>
        </div>

        <div v-if="tradeType === 'buy' && props.account && props.account.cash_balance < netCashImpact" class="alert-box is-error">
          可用现金不足：当前可用 ¥ {{ props.account.cash_balance.toFixed(2) }}，尚缺 ¥ {{ (netCashImpact - props.account.cash_balance).toFixed(2) }}
        </div>

        <div v-if="tradeType === 'sell' && props.position && props.position.quantity < Number(quantity)" class="alert-box is-error">
          当前可用持仓不足：现有 {{ props.position.quantity }} 股，拟卖出 {{ quantity }} 股
        </div>

        <div class="fee-toggle" @click="showCustomFees = !showCustomFees">
          <span>手续费明细与手动调整</span>
          <ChevronDown v-if="!showCustomFees" :size="14" />
          <ChevronUp v-else :size="14" />
        </div>

        <div v-if="showCustomFees" class="custom-fees-panel">
          <div class="fee-inputs">
            <div class="field-group">
              <label>佣金 (元)</label>
              <input v-model.number="customCommission" type="number" step="0.1" :placeholder="estimatedFees.commission.toFixed(2)" />
            </div>
            <div class="field-group">
              <label>印花税 (元)</label>
              <input v-model.number="customStampDuty" type="number" step="0.1" :placeholder="estimatedFees.stampDuty.toFixed(2)" />
            </div>
            <div class="field-group">
              <label>过户费 (元)</label>
              <input v-model.number="customTransferFee" type="number" step="0.01" :placeholder="estimatedFees.transferFee.toFixed(2)" />
            </div>
          </div>
        </div>

        <div class="field-group">
          <label>交易备注</label>
          <input v-model="notes" type="text" placeholder="如：回踩 20 日均线加仓" />
        </div>
      </div>

      <footer class="modal-foot">
        <button type="button" class="btn-secondary" @click="emit('close')">取消</button>
        <button type="button" class="btn-primary" :disabled="props.submitting || !canSubmit" @click="handleSubmit">
          {{ props.submitting ? '提交记账...' : '确认交割记账' }}
        </button>
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
  width: min(500px, 100%);
  overflow: hidden;
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--ikaros-line);
}

.modal-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--ikaros-ink);
}

.close-btn {
  background: transparent;
  border: 0;
  cursor: pointer;
  color: var(--ikaros-muted);
}

.modal-body {
  display: grid;
  gap: 12px;
  padding: 18px 20px;
}

.type-switch {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  background: rgba(0, 0, 0, 0.04);
  padding: 4px;
  border-radius: 12px;
}

.type-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--ikaros-muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.type-btn.buy-btn.is-active {
  background: #dc2626;
  color: #fff;
}

.type-btn.sell-btn.is-active {
  background: #16a34a;
  color: #fff;
}

.field-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.field-group {
  display: grid;
  gap: 5px;
}

.field-group label {
  font-size: 11px;
  font-weight: 600;
  color: var(--ikaros-muted);
}

.field-group input {
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid var(--ikaros-line);
  background: rgba(255, 255, 255, 0.5);
  font-size: 13px;
  color: var(--ikaros-ink);
  outline: none;
}

.calc-summary {
  display: grid;
  gap: 6px;
  padding: 10px 14px;
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.03);
  font-size: 12px;
}

.calc-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: var(--ikaros-muted);
}

.calc-item.highlight {
  border-top: 1px dashed var(--ikaros-line);
  padding-top: 6px;
  margin-top: 2px;
  font-size: 13px;
  color: var(--ikaros-ink);
}

.calc-item.highlight strong {
  color: var(--ikaros-pink);
  font-size: 15px;
}

.alert-box.is-error {
  padding: 8px 12px;
  border-radius: 8px;
  background: rgba(220, 38, 38, 0.08);
  color: #dc2626;
  font-size: 12px;
}

.fee-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--ikaros-muted);
  cursor: pointer;
  user-select: none;
}

.custom-fees-panel {
  padding: 10px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.02);
  border: 1px solid var(--ikaros-line);
}

.fee-inputs {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 8px;
}

.modal-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--ikaros-line);
}

.btn-secondary {
  padding: 8px 16px;
  border-radius: 10px;
  border: 1px solid var(--ikaros-line);
  background: transparent;
  color: var(--ikaros-muted);
  font-weight: 600;
  cursor: pointer;
}

.btn-primary {
  padding: 8px 20px;
  border-radius: 10px;
  border: 0;
  background: var(--ikaros-pink);
  color: #fff;
  font-weight: 600;
  cursor: pointer;
}

.btn-primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
