<script setup lang="ts">
import { computed } from 'vue'
import { formatAccountingMoney } from '@/utils/accountingFormat'
import { moneyTypeTextClass } from '@/utils/accountingMoney'

const props = withDefaults(defineProps<{
    amount: number
    type?: string
    signed?: boolean
    abs?: boolean
    /** Override semantic class; empty keeps type-based or none */
    tone?: 'expense' | 'income' | 'transfer' | 'brand' | 'muted' | 'inherit'
}>(), {
    signed: false,
    abs: false,
    tone: undefined,
})

const text = computed(() =>
    formatAccountingMoney(props.amount, {
        signed: props.signed,
        abs: props.abs,
    }),
)

const className = computed(() => {
    if (props.tone === 'inherit') return ''
    if (props.tone === 'expense') return 'text-accounting-expense'
    if (props.tone === 'income') return 'text-accounting-income'
    if (props.tone === 'transfer') return 'text-accounting-transfer'
    if (props.tone === 'brand') return 'text-accounting-brand'
    if (props.tone === 'muted') return 'text-theme-muted'
    if (props.type) return moneyTypeTextClass(props.type)
    return 'text-theme-primary'
})
</script>

<template>
  <span :class="['tabular-nums', className]"><slot>{{ text }}</slot></span>
</template>
