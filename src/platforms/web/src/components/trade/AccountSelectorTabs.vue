<script setup lang="ts">
import { Plus, Building2, Layers } from 'lucide-vue-next'
import type { TradeAccount } from '@/api/trade'

const props = defineProps<{
  accounts: TradeAccount[]
  selectedAccountId: number | null
}>()

const emit = defineEmits<{
  (e: 'select', accountId: number | null): void
  (e: 'create'): void
}>()
</script>

<template>
  <div class="account-tabs-wrapper">
    <div class="account-tabs">
      <button
        type="button"
        class="tab-item"
        :class="{ 'is-active': props.selectedAccountId === null }"
        @click="emit('select', null)"
      >
        <Layers :size="14" />
        <span>全景资产</span>
      </button>

      <button
        v-for="acc in props.accounts"
        :key="acc.id"
        type="button"
        class="tab-item"
        :class="{ 'is-active': props.selectedAccountId === acc.id }"
        @click="emit('select', acc.id)"
      >
        <Building2 :size="14" />
        <span>{{ acc.name }}</span>
        <small class="tab-badge">{{ acc.positions_count }}</small>
      </button>

      <button
        type="button"
        class="tab-add-btn"
        @click="emit('create')"
      >
        <Plus :size="13" />
        <span>添加账户</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
.account-tabs-wrapper {
  display: flex;
  align-items: center;
  overflow-x: auto;
  padding-bottom: 2px;
}

.account-tabs {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(255, 255, 255, 0.4);
  padding: 4px;
  border-radius: 14px;
  border: 1px solid var(--ikaros-line);
}

.tab-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 10px;
  border: 0;
  background: transparent;
  color: var(--ikaros-muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 160ms ease;
  white-space: nowrap;
}

.tab-item:hover {
  color: var(--ikaros-ink);
}

.tab-item.is-active {
  background: #fff;
  color: var(--ikaros-ink);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.tab-badge {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 99px;
  background: rgba(0, 0, 0, 0.05);
}

.tab-add-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border-radius: 10px;
  border: 1px dashed var(--ikaros-line);
  background: transparent;
  color: var(--ikaros-pink);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 160ms ease;
  white-space: nowrap;
}

.tab-add-btn:hover {
  border-color: var(--ikaros-pink);
  background: rgba(232, 93, 142, 0.06);
}
</style>
