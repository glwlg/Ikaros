<script setup lang="ts">
import { ref, watch } from 'vue'
import { X } from 'lucide-vue-next'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import type { TradeAccount } from '@/api/trade'

const props = defineProps<{
  visible: boolean
  account?: TradeAccount | null
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

const form = ref({
  name: '',
  broker: '通用券商',
  initial_cash: 0,
  commission_rate: 0.00025,
  min_commission: 5.0,
  stamp_duty_rate: 0.0005,
  transfer_fee_rate: 0.00001,
  notes: '',
})

watch(
  () => props.account,
  (val) => {
    if (val) {
      form.value = {
        name: val.name,
        broker: val.broker,
        initial_cash: val.cash_balance,
        commission_rate: val.commission_rate,
        min_commission: val.min_commission,
        stamp_duty_rate: val.stamp_duty_rate,
        transfer_fee_rate: val.transfer_fee_rate,
        notes: val.notes || '',
      }
    } else {
      form.value = {
        name: '',
        broker: '通用券商',
        initial_cash: 0,
        commission_rate: 0.00025,
        min_commission: 5.0,
        stamp_duty_rate: 0.0005,
        transfer_fee_rate: 0.00001,
        notes: '',
      }
    }
  },
  { immediate: true }
)

const handleSubmit = () => {
  if (!form.value.name.trim()) return
  emit('save', {
    ...form.value,
    cash_balance: Number(form.value.initial_cash),
  })
}
</script>

<template>
  <div v-if="props.visible" class="modal-backdrop" @click.self="emit('close')">
    <LiquidGlass :radius="20" :optics="panelOptics" class="modal-panel">
      <header class="modal-head">
        <h3>{{ props.account ? '编辑账户' : '新建交易账户' }}</h3>
        <button type="button" class="close-btn" @click="emit('close')"><X :size="16" /></button>
      </header>

      <div class="modal-body">
        <div class="field-group">
          <label>账户名称</label>
          <input v-model="form.name" type="text" placeholder="如：招商证券防守账户" />
        </div>

        <div class="field-row">
          <div class="field-group">
            <label>券商类型</label>
            <input v-model="form.broker" type="text" placeholder="如：招商证券 / 中信证券" />
          </div>
          <div class="field-group">
            <label>{{ props.account ? '可用现金 (元)' : '初始可用现金 (元)' }}</label>
            <input v-model.number="form.initial_cash" type="number" min="0" step="100" />
          </div>
        </div>

        <div class="field-row">
          <div class="field-group">
            <label>佣金费率 (如 0.00025 为万2.5)</label>
            <input v-model.number="form.commission_rate" type="number" step="0.00005" />
          </div>
          <div class="field-group">
            <label>最低佣金 (元)</label>
            <input v-model.number="form.min_commission" type="number" step="1" />
          </div>
        </div>

        <div class="field-row">
          <div class="field-group">
            <label>印花税率 (默认 0.0005 仅卖出)</label>
            <input v-model.number="form.stamp_duty_rate" type="number" step="0.0001" />
          </div>
          <div class="field-group">
            <label>过户费率 (默认 0.00001)</label>
            <input v-model.number="form.transfer_fee_rate" type="number" step="0.00001" />
          </div>
        </div>

        <div class="field-group">
          <label>备注说明</label>
          <input v-model="form.notes" type="text" placeholder="如：核心白马长线持仓配置" />
        </div>
      </div>

      <footer class="modal-foot">
        <button type="button" class="btn-secondary" @click="emit('close')">取消</button>
        <button type="button" class="btn-primary" :disabled="props.submitting || !form.name.trim()" @click="handleSubmit">
          {{ props.submitting ? '保存中...' : '保存' }}
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
  width: min(520px, 100%);
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

.field-group {
  display: grid;
  gap: 6px;
}

.field-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
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

.field-group input:focus {
  border-color: var(--ikaros-pink);
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
