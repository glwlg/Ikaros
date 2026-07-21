<script setup lang="ts">
import { computed } from 'vue'
import { ChevronRight } from 'lucide-vue-next'
import { formatAccountingMoney } from '@/utils/accountingFormat'
import { moneyTypeDotClass, moneyTypeTextClass } from '@/utils/accountingMoney'

const props = defineProps<{
    id: number
    type: string
    amount: number
    category?: string
    payee?: string
    remark?: string
    account?: string
    targetAccount?: string
    recordTime: string
    showChevron?: boolean
    showDate?: boolean
}>()

const title = computed(() =>
    props.category || props.payee || props.remark || '未分类',
)

const subtitle = computed(() => {
    const parts: string[] = []
    if (props.showDate && props.recordTime) {
        const m = props.recordTime.match(/^\d{4}-(\d{2})-(\d{2})/)
        if (m) parts.push(`${m[1]}/${m[2]}`)
        else {
            const d = new Date(props.recordTime)
            if (!Number.isNaN(d.getTime())) {
                parts.push(
                    `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`,
                )
            }
        }
    }
    if (props.payee) parts.push(props.payee)
    if (props.remark && props.remark !== props.category) parts.push(props.remark)
    return parts.join(' · ')
})

const amountText = computed(() => {
    const signed = props.type === '收入'
    return formatAccountingMoney(props.amount, { signed })
})

const accountLabel = computed(() => {
    if (props.type === '转账' && (props.account || props.targetAccount)) {
        return `${props.account || '?'} → ${props.targetAccount || '?'}`
    }
    return props.account || ''
})
</script>

<template>
  <div class="flex items-start justify-between gap-3 px-4 py-3">
    <div class="flex items-start gap-3 min-w-0">
      <div
        :class="['w-2 h-2 mt-2 rounded-full flex-shrink-0', moneyTypeDotClass(type)]"
      />
      <div class="min-w-0">
        <p class="font-medium text-theme-primary text-sm truncate">{{ title }}</p>
        <p v-if="subtitle" class="text-xs text-theme-muted mt-0.5 truncate">{{ subtitle }}</p>
      </div>
    </div>
    <div class="text-right flex-shrink-0">
      <div class="flex items-center justify-end gap-1">
        <p :class="['font-semibold text-sm tabular-nums', moneyTypeTextClass(type)]">
          {{ amountText }}
        </p>
        <ChevronRight v-if="showChevron !== false" class="w-3.5 h-3.5 text-theme-muted" />
      </div>
      <p
        v-if="accountLabel"
        class="text-[10px] text-theme-muted mt-0.5 px-1.5 py-0.5 rounded bg-theme-secondary inline-block max-w-[140px] truncate"
      >
        {{ accountLabel }}
      </p>
    </div>
  </div>
</template>
