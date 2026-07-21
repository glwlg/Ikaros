<script setup lang="ts">
import { Loader2 } from 'lucide-vue-next'

defineProps<{
    label?: string
}>()
</script>

<template>
  <div class="p-8 text-center text-theme-muted">
    <Loader2 class="w-5 h-5 animate-spin mx-auto mb-2 text-accounting-brand" />
    <span class="text-sm">{{ label || '加载中...' }}</span>
  </div>
</template>
