<script setup lang="ts">
import { ref } from 'vue'
import { X, ArrowDownRight, ArrowUpRight } from 'lucide-vue-next'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import type { TradeAccount } from '@/api/trade'

const props = defineProps<{
  visible: boolean
  account: TradeAccount | null
  submitting: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'save', payload: { flow_type: 'deposit' | 'withdraw'; amount: number; notes: string }): void
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

const flowType = ref<'deposit' | 'withdraw'>('deposit')
const amount = ref<number | ''>('')
const notes = ref('')

const handleSubmit = () => {
  if (!amount.value || amount.value <= 0) return
  emit('save', {
    flow_type: flowType.value,
    amount: Number(amount.value),
    notes: notes.value.trim(),
  })
}
</script>

<template>
  <div v-if="props.visible" class="modal-backdrop" @click.self="emit('close')">
    <LiquidGlass :radius="20" :optics="panelOptics" class="modal-panel">
      <header class="modal-head">
        <h3>银证转账 · {{ props.account?.name }}</h3>
        <button type="button" class="close-btn" @click="emit('close')"><X :size="16" /></button>
      </header>

      <div class="modal-body">
        <div class="direction-tabs">
          <button
            type="button"
            class="dir-btn"
            :class="{ 'is-active': flowType === 'deposit' }"
            @click="flowType = 'deposit'"
          >
            <ArrowDownRight :size="15" />
            <span>转入资金 (入金)</span>
          </button>
          <button
            type="button"
            class="dir-btn"
            :class="{ 'is-active': flowType === 'withdraw' }"
            @click="flowType = 'withdraw'"
          >
            <ArrowUpRight :size="15" />
            <span>转出资金 (出金)</span>
          </button>
        </div>

        <div class="field-group">
          <label>当前账户可用现金</label>
          <div class="current-cash-display">¥ {{ props.account?.cash_balance.toFixed(2) }}</div>
        </div>

        <div class="field-group">
          <label>变动金额 (元)</label>
          <input v-model.number="amount" type="number" min="1" step="100" placeholder="请输入转账金额" />
        </div>

        <div class="field-group">
          <label>备注说明</label>
          <input v-model="notes" type="text" placeholder="如：工资定投结余转入" />
        </div>
      </div>

      <footer class="modal-foot">
        <button type="button" class="btn-secondary" @click="emit('close')">取消</button>
        <button
          type="button"
          class="btn-primary"
          :disabled="props.submitting || !amount || amount <= 0 || (flowType === 'withdraw' && (props.account?.cash_balance ?? 0) < amount)"
          @click="handleSubmit"
        >
          {{ props.submitting ? '处理中...' : '确认转账' }}
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
  width: min(440px, 100%);
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
  gap: 14px;
  padding: 18px 20px;
}

.direction-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  background: rgba(0, 0, 0, 0.04);
  padding: 4px;
  border-radius: 12px;
}

.dir-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 8px 12px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--ikaros-muted);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.dir-btn.is-active {
  background: #fff;
  color: var(--ikaros-ink);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
}

.current-cash-display {
  font-size: 18px;
  font-weight: 700;
  color: var(--ikaros-ink);
  padding: 6px 0;
}

.field-group {
  display: grid;
  gap: 6px;
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
