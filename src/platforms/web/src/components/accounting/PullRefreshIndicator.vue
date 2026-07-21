<script setup lang="ts">
import { Loader2 } from 'lucide-vue-next'

defineProps<{
    distance: number
    hint: string
    refreshing?: boolean
}>()
</script>

<template>
  <div
    class="overflow-hidden transition-[height] duration-150"
    :style="{ height: `${Math.round(distance)}px` }"
  >
    <div class="h-full flex items-end justify-center pb-2 text-xs text-theme-muted gap-1">
      <Loader2 v-if="refreshing" class="w-3 h-3 animate-spin" />
      <span>{{ hint }}</span>
    </div>
  </div>
</template>
