<script setup lang="ts">
defineProps<{
    title?: string
    description?: string
}>()
</script>

<template>
  <div class="flex flex-col items-center justify-center py-12 px-6 text-center">
    <div class="w-14 h-14 rounded-2xl bg-theme-secondary flex items-center justify-center mb-3 text-theme-muted">
      <slot name="icon" />
    </div>
    <p class="text-sm font-medium text-theme-primary">{{ title || '暂无数据' }}</p>
    <p v-if="description" class="text-xs text-theme-muted mt-1 max-w-[240px]">{{ description }}</p>
    <div v-if="$slots.action" class="mt-4">
      <slot name="action" />
    </div>
  </div>
</template>
