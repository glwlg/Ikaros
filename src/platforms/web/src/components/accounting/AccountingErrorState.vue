<script setup lang="ts">
import { AlertCircle, RefreshCw } from 'lucide-vue-next'

defineProps<{
    title?: string
    description?: string
    retryLabel?: string
}>()

const emit = defineEmits<{
    retry: []
}>()
</script>

<template>
  <div class="flex flex-col items-center justify-center py-12 px-6 text-center">
    <div class="mb-3 flex h-14 w-14 items-center justify-center rounded-2xl bg-rose-50 text-rose-500 dark:bg-rose-950/50 dark:text-rose-300">
      <slot name="icon">
        <AlertCircle class="h-6 w-6" />
      </slot>
    </div>
    <p class="text-sm font-medium text-theme-primary">{{ title || '加载失败' }}</p>
    <p class="mt-1 max-w-[260px] text-xs text-theme-muted leading-relaxed">
      {{ description || '请检查网络后重试' }}
    </p>
    <button
      type="button"
      class="mt-4 inline-flex h-10 items-center gap-1.5 rounded-xl bg-accounting-brand px-4 text-sm font-medium text-white active:opacity-90"
      @click="emit('retry')"
    >
      <RefreshCw class="h-3.5 w-3.5" />
      {{ retryLabel || '重试' }}
    </button>
  </div>
</template>
