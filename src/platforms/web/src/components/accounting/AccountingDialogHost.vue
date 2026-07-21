<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import {
    resolveAccountingDialog,
    subscribeAccountingDialog,
    type AccountingDialogRequest,
} from '@/utils/accountingDialog'

const current = ref<AccountingDialogRequest | null>(null)
let unsubscribe: (() => void) | null = null

onMounted(() => {
    unsubscribe = subscribeAccountingDialog(req => {
        current.value = req
    })
})

onBeforeUnmount(() => {
    unsubscribe?.()
    unsubscribe = null
})

const accept = () => {
    if (!current.value) return
    resolveAccountingDialog(current.value.id, true)
}

const reject = () => {
    if (!current.value) return
    resolveAccountingDialog(current.value.id, false)
}
</script>

<template>
  <div
    v-if="current"
    class="fixed inset-0 z-[100] flex items-end sm:items-center justify-center bg-black/45 p-0 sm:p-4"
    @click.self="current.kind === 'alert' ? accept() : reject()"
  >
    <div class="w-full sm:max-w-[360px] rounded-t-2xl sm:rounded-2xl bg-theme-elevated border border-theme-secondary shadow-xl p-5 safe-x safe-bottom sm:safe-bottom-0">
      <h3 class="text-base font-semibold text-theme-primary">{{ current.title }}</h3>
      <p class="mt-2 text-sm text-theme-secondary leading-relaxed whitespace-pre-wrap">{{ current.message }}</p>
      <div class="mt-5 flex gap-2 justify-stretch sm:justify-end">
        <button
          v-if="current.kind === 'confirm'"
          type="button"
          class="flex-1 sm:flex-none px-4 min-h-[44px] rounded-xl border border-theme-primary text-theme-secondary text-sm font-medium active:bg-theme-secondary transition"
          @click="reject"
        >
          {{ current.cancelLabel }}
        </button>
        <button
          type="button"
          class="flex-1 sm:flex-none px-4 min-h-[44px] rounded-xl bg-accounting-brand text-white text-sm font-medium active:opacity-90 transition"
          @click="accept"
        >
          {{ current.confirmLabel }}
        </button>
      </div>
    </div>
  </div>
</template>
