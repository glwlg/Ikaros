<script setup lang="ts">
import { ref, watch } from 'vue'
import { Plus, Zap } from 'lucide-vue-next'
import AddRecordDialog from '@/components/accounting/AddRecordDialog.vue'
import { loadGlobalSettings } from '@/utils/accountingLocal'

const props = defineProps<{
    bookId: number | null
    showImage?: boolean
}>()

const emit = defineEmits<{
    saved: []
    image: []
}>()

const enabled = ref(true)
const showDialog = ref(false)

const refreshEnabled = () => {
    enabled.value = loadGlobalSettings().quick_create_enabled !== false
}

refreshEnabled()

watch(
    () => props.bookId,
    () => refreshEnabled(),
)

const open = () => {
    refreshEnabled()
    if (!props.bookId || !enabled.value) return
    showDialog.value = true
}

const onSaved = () => {
    showDialog.value = false
    emit('saved')
}

defineExpose({ open, refreshEnabled })
</script>

<template>
  <div
    v-if="bookId && enabled"
    class="accounting-fab-stack"
  >
    <button
      v-if="showImage"
      type="button"
      class="accounting-fab accounting-fab-secondary"
      aria-label="图片识别记账"
      @click="emit('image')"
      @contextmenu.prevent
    >
      <Zap class="w-5 h-5" />
    </button>
    <button
      type="button"
      class="accounting-fab accounting-fab-primary"
      aria-label="手动记账"
      @click="open"
      @contextmenu.prevent
    >
      <Plus class="w-7 h-7" />
    </button>
  </div>

  <AddRecordDialog
    v-if="showDialog && bookId"
    :book-id="bookId"
    @close="showDialog = false"
    @saved="onSaved"
  />
</template>

<style scoped>
.accounting-fab-stack {
  position: fixed;
  z-index: 30;
  right: max(1rem, env(safe-area-inset-right, 0px));
  /* 底栏约 52px + 安全区 + 间距 */
  bottom: calc(4.25rem + env(safe-area-inset-bottom, 0px));
  display: flex;
  align-items: center;
  gap: 0.75rem;
  -webkit-touch-callout: none;
  -webkit-user-select: none;
  user-select: none;
  pointer-events: none;
}

.accounting-fab {
  pointer-events: auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 9999px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
  transition: transform 0.12s ease, opacity 0.12s ease, box-shadow 0.12s ease;
  -webkit-tap-highlight-color: transparent;
}

.accounting-fab:active {
  transform: scale(0.94);
}

.accounting-fab-primary {
  width: 3.5rem;
  height: 3.5rem;
  background: var(--color-accounting-brand);
  color: #fff;
}

.accounting-fab-secondary {
  width: 3rem;
  height: 3rem;
  background: #fbbf24;
  color: #0f172a;
}
</style>
