<script setup lang="ts">
import { AlertTriangle, CheckCircle2, X, XCircle } from 'lucide-vue-next'

import type { ViewToast } from '@/composables/useViewToasts'

defineProps<{ toasts: ViewToast[] }>()
const emit = defineEmits<{ dismiss: [id: number] }>()
</script>

<template>
  <div class="view-toast-stack" aria-live="polite">
    <div v-for="toast in toasts" :key="toast.id" class="view-toast" :class="toast.kind">
      <CheckCircle2 v-if="toast.kind === 'success'" class="h-4 w-4 shrink-0" />
      <AlertTriangle v-else-if="toast.kind === 'warning'" class="h-4 w-4 shrink-0" />
      <XCircle v-else class="h-4 w-4 shrink-0" />
      <span>{{ toast.text }}</span>
      <button type="button" class="view-toast-close" title="关闭" @click="emit('dismiss', toast.id)"><X class="h-3.5 w-3.5" /></button>
    </div>
  </div>
</template>

<style scoped>
.view-toast-stack {
  position: fixed;
  top: 72px;
  right: 24px;
  z-index: 1200;
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-width: min(420px, calc(100vw - 48px));
}

.view-toast {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 12px 14px;
  border: 1px solid var(--panel-border);
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 12px 32px rgba(15, 23, 42, 0.16);
  font-size: 13px;
  line-height: 1.5;
}

.view-toast.success { background: #ecfdf3; color: #15803d; border-color: #bbf7d0; }
.view-toast.warning { background: #fffbeb; color: #b45309; border-color: #fde68a; }
.view-toast.error { background: #fff1f2; color: #be123c; border-color: #fecdd3; }

.view-toast span { flex: 1; }

.view-toast-close {
  display: inline-flex;
  padding: 2px;
  border: none;
  background: transparent;
  color: inherit;
  opacity: 0.6;
  cursor: pointer;
}

.view-toast-close:hover { opacity: 1; }
</style>
