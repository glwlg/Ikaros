<script setup lang="ts">
import { ref, watch } from 'vue'
import { X, Calculator, AlertTriangle, ArrowRight, CheckCircle2 } from 'lucide-vue-next'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import { simulateOrder, type TradeAccount, type TradePosition, type SimulationResult } from '@/api/trade'

const props = defineProps<{
  visible: boolean
  account: TradeAccount | null
  position?: TradePosition | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'apply', result: { stock_code: string; stock_name: string; price: number; quantity: number }): void
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

const mode = ref<'amount' | 'quantity'>('amount')
const stockCode = ref('')
const stockName = ref('')
const price = ref<number | ''>('')
const targetAmount = ref<number | ''>(5000)
const quantity = ref<number | ''>(100)
const loading = ref(false)
const error = ref('')
const result = ref<SimulationResult | null>(null)

watch(
  () => [props.visible, props.position],
  () => {
    if (props.visible) {
      result.value = null
      error.value = ''
      if (props.position) {
        stockCode.value = props.position.stock_code
        stockName.value = props.position.stock_name
        price.value = props.position.current_price > 0 ? props.position.current_price : props.position.cost_price
      } else {
        stockCode.value = ''
        stockName.value = ''
        price.value = ''
      }
      handleRunSimulate()
    }
  },
  { immediate: true }
)

const handleRunSimulate = async () => {
  if (!props.account || !stockCode.value.trim() || !price.value || Number(price.value) <= 0) return
  loading.value = true
  error.value = ''
  try {
    const res = await simulateOrder({
      account_id: props.account.id,
      stock_code: stockCode.value.trim(),
      stock_name: stockName.value.trim() || stockCode.value.trim(),
      price: Number(price.value),
      target_amount: mode.value === 'amount' && targetAmount.value ? Number(targetAmount.value) : undefined,
      quantity: mode.value === 'quantity' && quantity.value ? Number(quantity.value) : undefined,
    })
    result.value = res.data
  } catch (err: any) {
    error.value = err?.response?.data?.detail || '试算失败'
  } finally {
    loading.value = false
  }
}

const handleApplyToOrder = () => {
  if (!result.value) return
  emit('apply', {
    stock_code: result.value.stock_code,
    stock_name: result.value.stock_name,
    price: result.value.price,
    quantity: result.value.simulated_quantity,
  })
}
</script>

<template>
  <div v-if="props.visible" class="modal-backdrop" @click.self="emit('close')">
    <LiquidGlass :radius="20" :optics="panelOptics" class="modal-panel">
      <header class="modal-head">
        <div class="head-title">
          <Calculator :size="18" />
          <h3>调仓与加仓试算器</h3>
        </div>
        <button type="button" class="close-btn" @click="emit('close')"><X :size="16" /></button>
      </header>

      <div class="modal-body">
        <div class="field-row">
          <div class="field-group">
            <label>标的代码</label>
            <input v-model="stockCode" type="text" placeholder="如 sh600519" @change="handleRunSimulate" />
          </div>
          <div class="field-group">
            <label>标的名称</label>
            <input v-model="stockName" type="text" placeholder="如 贵州茅台" />
          </div>
        </div>

        <div class="field-row">
          <div class="field-group">
            <label>参考股价 (元)</label>
            <input v-model.number="price" type="number" step="0.01" @input="handleRunSimulate" />
          </div>
          <div class="field-group">
            <label>试算模式</label>
            <div class="mode-pill-group">
              <button
                type="button"
                class="mode-btn"
                :class="{ 'is-active': mode === 'amount' }"
                @click="mode = 'amount'; handleRunSimulate()"
              >
                按金额加仓
              </button>
              <button
                type="button"
                class="mode-btn"
                :class="{ 'is-active': mode === 'quantity' }"
                @click="mode = 'quantity'; handleRunSimulate()"
              >
                按手数加仓
              </button>
            </div>
          </div>
        </div>

        <div class="field-group">
          <label v-if="mode === 'amount'">计划买入金额 (元)</label>
          <label v-else>计划买入股数 (股)</label>
          <input
            v-if="mode === 'amount'"
            v-model.number="targetAmount"
            type="number"
            step="500"
            placeholder="如 5000"
            @input="handleRunSimulate"
          />
          <input
            v-else
            v-model.number="quantity"
            type="number"
            step="100"
            placeholder="100的整数倍"
            @input="handleRunSimulate"
          />
        </div>

        <!-- 试算结果预演 -->
        <div v-if="result" class="result-box">
          <div class="result-grid">
            <div class="result-metric">
              <span class="label">最优整手折算</span>
              <strong class="val">{{ result.simulated_lots }} 手 ({{ result.simulated_quantity }} 股)</strong>
            </div>
            <div class="result-metric">
              <span class="label">预留手续费</span>
              <strong class="val">¥ {{ result.fees.total_fee.toFixed(2) }}</strong>
            </div>
            <div class="result-metric">
              <span class="label">实际所需资金</span>
              <strong class="val highlight">¥ {{ result.total_required.toFixed(2) }}</strong>
            </div>
            <div class="result-metric">
              <span class="label">新摊薄成本</span>
              <strong class="val">¥ {{ result.diluted_cost_price.toFixed(4) }}</strong>
            </div>
            <div class="result-metric">
              <span class="label">调仓后市值</span>
              <strong class="val">¥ {{ result.new_stock_market_value.toFixed(2) }}</strong>
            </div>
            <div class="result-metric">
              <span class="label">账户仓位权重</span>
              <strong class="val">{{ result.position_ratio_percent }}%</strong>
            </div>
          </div>

          <div v-if="result.is_sufficient" class="status-notice is-ok">
            <CheckCircle2 :size="15" />
            <span>账户可用现金充足（当前可用 ¥ {{ result.current_cash.toFixed(2) }}）</span>
          </div>

          <div v-else class="status-notice is-shortage">
            <AlertTriangle :size="15" />
            <div class="shortage-copy">
              <p>可用现金不足，差额 <strong>¥ {{ result.cash_shortage.toFixed(2) }}</strong></p>
              <div v-if="result.transfer_suggestions && result.transfer_suggestions.length" class="suggestions">
                <small>可从其他账户调拨资金：</small>
                <ul>
                  <li v-for="sug in result.transfer_suggestions" :key="sug.account_id">
                    {{ sug.name }}：可用现金 ¥ {{ sug.available_cash.toFixed(2) }}
                    <span v-if="sug.can_cover_fully" class="badge-full">可全额覆盖</span>
                  </li>
                </ul>
              </div>
            </div>
          </div>
        </div>

        <div v-if="error" class="status-notice is-shortage">
          {{ error }}
        </div>
      </div>

      <footer class="modal-foot">
        <button type="button" class="btn-secondary" @click="emit('close')">关闭</button>
        <button
          v-if="result"
          type="button"
          class="btn-primary"
          @click="handleApplyToOrder"
        >
          带入记账交割单
          <ArrowRight :size="14" />
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
  width: min(540px, 100%);
  overflow: hidden;
}

.modal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--ikaros-line);
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
  display: grid;
  gap: 12px;
  padding: 18px 20px;
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

.mode-pill-group {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  background: rgba(0, 0, 0, 0.04);
  padding: 3px;
  border-radius: 10px;
}

.mode-btn {
  border: 0;
  background: transparent;
  padding: 6px 8px;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ikaros-muted);
  cursor: pointer;
}

.mode-btn.is-active {
  background: #fff;
  color: var(--ikaros-ink);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.result-box {
  display: grid;
  gap: 10px;
  padding: 14px;
  border-radius: 14px;
  background: rgba(0, 0, 0, 0.02);
  border: 1px solid var(--ikaros-line);
}

.result-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.result-metric {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.result-metric .label {
  font-size: 10px;
  color: var(--ikaros-muted);
}

.result-metric .val {
  font-size: 13px;
  color: var(--ikaros-ink);
}

.result-metric .val.highlight {
  color: var(--ikaros-pink);
  font-size: 14px;
}

.status-notice {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 10px;
  font-size: 12px;
}

.status-notice.is-ok {
  background: rgba(22, 163, 74, 0.08);
  color: #16a34a;
}

.status-notice.is-shortage {
  background: rgba(220, 38, 38, 0.08);
  color: #dc2626;
}

.shortage-copy p {
  margin: 0 0 6px 0;
}

.suggestions ul {
  margin: 4px 0 0 16px;
  padding: 0;
}

.badge-full {
  display: inline-block;
  margin-left: 6px;
  padding: 1px 6px;
  border-radius: 99px;
  background: rgba(22, 163, 74, 0.15);
  color: #16a34a;
  font-size: 10px;
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
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  border-radius: 10px;
  border: 0;
  background: var(--ikaros-pink);
  color: #fff;
  font-weight: 600;
  cursor: pointer;
}
</style>
