<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAccountingStore } from '@/stores/accounting'
import { ChevronLeft, Trash2 } from 'lucide-vue-next'
import {
    appendOperationLog,
    clearOperationLogs,
    loadExtensionSettings,
    loadGlobalSettings,
    loadOperationLogs,
    saveExtensionSettings,
    saveGlobalSettings,
    type ExtensionSettingsState,
    type GlobalSettingsState,
    type OperationLogEntry,
} from '@/utils/accountingLocal'

type SettingsKind = 'global' | 'extensions' | 'logs'

const route = useRoute()
const router = useRouter()
const store = useAccountingStore()

const savedHint = ref('')

const globalSettings = ref<GlobalSettingsState>(loadGlobalSettings())
const extensionSettings = ref<ExtensionSettingsState>(loadExtensionSettings())
const operationLogs = ref<OperationLogEntry[]>([])

const resolveKind = (value: unknown): SettingsKind => {
    const raw = typeof value === 'string' ? value : ''
    if (raw === 'extensions' || raw === 'logs') return raw
    return 'global'
}

const kind = computed<SettingsKind>(() => {
    const raw = Array.isArray(route.params.kind) ? route.params.kind[0] : route.params.kind
    return resolveKind(raw)
})

const titleMap: Record<SettingsKind, string> = {
    global: '全局设置',
    extensions: '扩展组件',
    logs: '操作日志',
}

const pageTitle = computed(() => titleMap[kind.value])

const refreshLogs = () => {
    operationLogs.value = loadOperationLogs(store.currentBookId)
}

const showSavedHint = (text: string) => {
    savedHint.value = text
    window.setTimeout(() => {
        if (savedHint.value === text) {
            savedHint.value = ''
        }
    }, 1500)
}

const handleSaveGlobal = () => {
    saveGlobalSettings(globalSettings.value)
    appendOperationLog(store.currentBookId, '保存全局设置', JSON.stringify(globalSettings.value))
    showSavedHint('全局设置已保存')
}

const handleSaveExtensions = () => {
    saveExtensionSettings(extensionSettings.value)
    appendOperationLog(store.currentBookId, '保存扩展设置', JSON.stringify(extensionSettings.value))
    showSavedHint('扩展设置已保存')
}

const handleClearLogs = () => {
    if (!confirm('确认清空操作日志吗？')) return
    clearOperationLogs(store.currentBookId)
    refreshLogs()
}

watch(kind, () => {
    if (kind.value === 'logs') {
        refreshLogs()
    }
})

onMounted(async () => {
    if (!store.currentBookId) {
        await store.fetchBooks()
    }

    if (kind.value === 'logs') {
        refreshLogs()
    }
})
</script>

<template>
  <div class="h-screen flex flex-col bg-slate-50 dark:bg-slate-900 absolute inset-0 z-50">
    <header class="bg-white dark:bg-slate-800 shadow-sm relative z-10 safe-top">
      <div class="flex items-center justify-between h-14 px-4">
        <button @click="router.back()" class="p-2 -ml-2 text-slate-600 dark:text-slate-300">
          <ChevronLeft class="w-6 h-6" />
        </button>
        <h1 class="text-lg font-bold text-slate-800 dark:text-white">{{ pageTitle }}</h1>
        <span class="text-xs text-teal-600 w-20 text-right">{{ savedHint }}</span>
      </div>
    </header>

    <main class="flex-1 overflow-y-auto p-4 safe-bottom">
      <div v-if="kind === 'global'" class="space-y-4">
        <div class="bg-white dark:bg-slate-800 rounded-2xl p-4 border border-slate-100 dark:border-slate-700 shadow-sm space-y-4">
          <div>
            <label class="block text-xs text-slate-500 mb-1">货币符号</label>
            <select
              v-model="globalSettings.currency_symbol"
              class="w-full px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
            >
              <option value="¥">人民币 (¥)</option>
              <option value="$">美元 ($)</option>
              <option value="€">欧元 (€)</option>
            </select>
          </div>

          <div>
            <label class="block text-xs text-slate-500 mb-1">金额小数位</label>
            <input
              v-model.number="globalSettings.decimal_places"
              type="number"
              min="0"
              max="4"
              class="w-full px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
            />
          </div>

          <div>
            <label class="block text-xs text-slate-500 mb-1">周起始日</label>
            <select
              v-model="globalSettings.week_start"
              class="w-full px-3 py-2.5 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
            >
              <option value="周一">周一</option>
              <option value="周日">周日</option>
            </select>
          </div>

          <label class="flex items-center justify-between rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 px-3 py-2.5">
            <span class="text-sm text-slate-700 dark:text-slate-200">快速记账模式</span>
            <input v-model="globalSettings.quick_create_enabled" type="checkbox" class="w-4 h-4" />
          </label>
        </div>

        <button
          @click="handleSaveGlobal"
          class="w-full py-3 rounded-xl bg-teal-500 hover:bg-teal-600 text-white font-medium"
        >保存设置</button>
      </div>

      <div v-else-if="kind === 'extensions'" class="space-y-4">
        <div class="bg-white dark:bg-slate-800 rounded-2xl p-4 border border-slate-100 dark:border-slate-700 shadow-sm space-y-3">
          <label class="flex items-center justify-between rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 px-3 py-2.5">
            <span class="text-sm text-slate-700 dark:text-slate-200">智能分类建议</span>
            <input v-model="extensionSettings.smart_category_enabled" type="checkbox" class="w-4 h-4" />
          </label>

          <label class="flex items-center justify-between rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 px-3 py-2.5">
            <span class="text-sm text-slate-700 dark:text-slate-200">周期任务提醒</span>
            <input v-model="extensionSettings.recurring_reminder_enabled" type="checkbox" class="w-4 h-4" />
          </label>

          <label class="flex items-center justify-between rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 px-3 py-2.5">
            <span class="text-sm text-slate-700 dark:text-slate-200">往来到期提醒</span>
            <input v-model="extensionSettings.debt_reminder_enabled" type="checkbox" class="w-4 h-4" />
          </label>

          <label class="flex items-center justify-between rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-200 dark:border-slate-700 px-3 py-2.5">
            <span class="text-sm text-slate-700 dark:text-slate-200">快捷导入助手</span>
            <input v-model="extensionSettings.quick_import_enabled" type="checkbox" class="w-4 h-4" />
          </label>
        </div>

        <button
          @click="handleSaveExtensions"
          class="w-full py-3 rounded-xl bg-teal-500 hover:bg-teal-600 text-white font-medium"
        >保存扩展设置</button>
      </div>

      <div v-else class="space-y-4">
        <div class="bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm overflow-hidden">
          <div v-if="operationLogs.length === 0" class="p-6 text-center text-sm text-slate-500">暂无操作日志</div>
          <div
            v-for="log in operationLogs"
            :key="log.id"
            class="px-4 py-3 border-b border-slate-100 dark:border-slate-700 last:border-b-0"
          >
            <p class="text-sm font-medium text-slate-800 dark:text-white">{{ log.action }}</p>
            <p class="text-xs text-slate-500 mt-0.5">{{ log.detail }}</p>
            <p class="text-[11px] text-slate-400 mt-1">{{ new Date(log.created_at).toLocaleString('zh-CN') }}</p>
          </div>
        </div>

        <button
          @click="handleClearLogs"
          class="w-full py-3 rounded-xl border border-rose-200 text-rose-600 bg-rose-50 hover:bg-rose-100 font-medium flex items-center justify-center gap-1"
        >
          <Trash2 class="w-4 h-4" />
          清空日志
        </button>
      </div>
    </main>
  </div>
</template>
