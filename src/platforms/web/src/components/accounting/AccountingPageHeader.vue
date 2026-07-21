<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ChevronLeft } from 'lucide-vue-next'

withDefaults(defineProps<{
    title: string
    /** Show back button (default true) */
    showBack?: boolean
    /** Use brand gradient header instead of neutral */
    variant?: 'neutral' | 'brand'
}>(), {
    showBack: true,
    variant: 'neutral',
})

const router = useRouter()

const goBack = () => {
    if (window.history.length > 1) router.back()
    else router.push('/accounting/overview')
}
</script>

<template>
  <header
    class="accounting-page-header safe-top safe-x relative z-10 shadow-sm flex-shrink-0"
    :class="variant === 'brand'
      ? 'bg-accounting-brand text-white'
      : 'bg-theme-elevated border-b border-theme-secondary text-theme-primary'"
  >
    <div class="flex items-center justify-between h-12 sm:h-14 px-3 sm:px-4">
      <div class="w-16 sm:w-20 flex justify-start">
        <button
          v-if="showBack"
          type="button"
          class="accounting-touch-target inline-flex items-center justify-center p-2 -ml-1 rounded-xl transition active:scale-95"
          :class="variant === 'brand' ? 'hover:bg-white/10 active:bg-white/15' : 'hover:bg-theme-secondary text-theme-secondary active:bg-theme-tertiary'"
          aria-label="返回"
          @click="goBack"
        >
          <ChevronLeft class="w-6 h-6" />
        </button>
      </div>
      <h1 class="text-base sm:text-lg font-bold truncate max-w-[55%] text-center">{{ title }}</h1>
      <div class="w-16 sm:w-20 flex justify-end items-center gap-1 min-h-[44px]">
        <slot name="actions" />
      </div>
    </div>
    <slot name="below" />
  </header>
</template>
