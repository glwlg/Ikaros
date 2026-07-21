<script setup lang="ts">
import { computed } from 'vue'
import { budgetProgressPercent, ringDashOffset } from '@/utils/accountingMoney'
import { formatAccountingMoney } from '@/utils/accountingFormat'

const props = withDefaults(defineProps<{
    spent: number
    total: number
    size?: number
    stroke?: number
    centerLabel?: string
}>(), {
    size: 96,
    stroke: 8,
    centerLabel: '剩余',
})

const radius = computed(() => (props.size - props.stroke) / 2)
const circumference = computed(() => 2 * Math.PI * radius.value)
const percent = computed(() => budgetProgressPercent(props.spent, props.total))
const offset = computed(() => ringDashOffset(percent.value, circumference.value))
const remaining = computed(() => props.total - props.spent)
const over = computed(() => props.total > 0 && remaining.value < 0)
const trackColor = computed(() => 'var(--color-border-secondary)')
const progressColor = computed(() =>
    over.value || percent.value >= 90
        ? 'var(--color-accounting-expense)'
        : 'var(--color-accounting-brand)',
)
</script>

<template>
  <div
    class="relative inline-flex items-center justify-center"
    :style="{ width: `${size}px`, height: `${size}px` }"
  >
    <svg :width="size" :height="size" class="rotate-[-90deg]">
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        :stroke="trackColor"
        :stroke-width="stroke"
      />
      <circle
        :cx="size / 2"
        :cy="size / 2"
        :r="radius"
        fill="none"
        :stroke="progressColor"
        :stroke-width="stroke"
        stroke-linecap="round"
        :stroke-dasharray="circumference"
        :stroke-dashoffset="offset"
        class="transition-[stroke-dashoffset] duration-500"
      />
    </svg>
    <div class="absolute inset-0 flex flex-col items-center justify-center text-center px-2">
      <p class="text-[10px] text-theme-muted">{{ centerLabel }}</p>
      <p
        v-if="total > 0"
        :class="['text-sm font-bold tabular-nums', over ? 'text-accounting-expense' : 'text-theme-primary']"
      >
        {{ formatAccountingMoney(remaining) }}
      </p>
      <p v-else class="text-xs font-medium text-accounting-brand">点击添加</p>
      <p v-if="total > 0" class="text-[10px] text-theme-muted">
        总额{{ formatAccountingMoney(total) }}
      </p>
    </div>
  </div>
</template>
