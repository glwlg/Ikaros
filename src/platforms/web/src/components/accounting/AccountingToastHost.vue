<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { CheckCircle2, Info, X, XCircle } from 'lucide-vue-next'
import {
    dismissAccountingToast,
    subscribeAccountingToast,
    type AccountingToastItem,
} from '@/utils/accountingToast'

const toasts = ref<AccountingToastItem[]>([])
let unsubscribe: (() => void) | null = null

onMounted(() => {
    unsubscribe = subscribeAccountingToast(items => {
        toasts.value = items
    })
})

onBeforeUnmount(() => {
    unsubscribe?.()
    unsubscribe = null
})

const iconFor = (type: AccountingToastItem['type']) => {
    if (type === 'success') return CheckCircle2
    if (type === 'error') return XCircle
    return Info
}

const toneClass = (type: AccountingToastItem['type']) => {
    if (type === 'success') {
        return 'border-emerald-200/80 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/90 dark:text-emerald-100'
    }
    if (type === 'error') {
        return 'border-rose-200/80 bg-rose-50 text-rose-900 dark:border-rose-800 dark:bg-rose-950/90 dark:text-rose-100'
    }
    return 'border-theme-secondary bg-theme-elevated text-theme-primary'
}
</script>

<template>
  <div
    class="pointer-events-none fixed inset-x-0 top-0 z-[110] flex flex-col items-center gap-2 px-3 pt-[max(0.75rem,env(safe-area-inset-top))]"
    aria-live="polite"
    aria-relevant="additions"
  >
    <div
      v-for="toast in toasts"
      :key="toast.id"
      class="pointer-events-auto flex w-full max-w-sm items-start gap-2 rounded-2xl border px-3.5 py-3 shadow-lg backdrop-blur-md transition"
      :class="toneClass(toast.type)"
      role="status"
    >
      <component
        :is="iconFor(toast.type)"
        class="mt-0.5 h-4 w-4 shrink-0 opacity-90"
        aria-hidden="true"
      />
      <p class="min-w-0 flex-1 text-sm leading-snug font-medium">{{ toast.message }}</p>
      <button
        type="button"
        class="shrink-0 rounded-lg p-1 opacity-60 active:opacity-100"
        aria-label="关闭"
        @click="dismissAccountingToast(toast.id)"
      >
        <X class="h-3.5 w-3.5" />
      </button>
    </div>
  </div>
</template>
