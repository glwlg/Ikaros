<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useAccountingStore } from '@/stores/accounting'
import { getStatsOverview, importCsv, type StatsOverview } from '@/api/accounting'
import {
    Grid2x2, ListOrdered, Store, Tag,
    Download, Upload, Share2, BookOpen,
    Bot, Puzzle, ScrollText,
    ChevronRight, User, Settings
} from 'lucide-vue-next'

const authStore = useAuthStore()
const store = useAccountingStore()


const overview = ref<StatsOverview>({ days: 0, transactions: 0, net_assets: 0 })
const loading = ref(false)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const formatMoney = (n: number) =>
    new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(n)

const managementItems = [
    { icon: Grid2x2, label: '分类', color: 'bg-teal-500' },
    { icon: ListOrdered, label: '项目', color: 'bg-teal-500' },
    { icon: Store, label: '商家', color: 'bg-teal-500' },
    { icon: Tag, label: '标签', color: 'bg-teal-500' },
    { icon: Download, label: '导入', color: 'bg-teal-500', action: 'import' },
    { icon: Upload, label: '导出', color: 'bg-teal-500' },
    { icon: Share2, label: '共享', color: 'bg-teal-500' },
    { icon: BookOpen, label: '账本', color: 'bg-teal-500' },
]

const settingsItems = [
    { icon: Settings, label: '全局设置', desc: '显示/通用设置', to: '' },
    { icon: Bot, label: '自动记账', desc: '自动化规则', to: '' },
    { icon: Puzzle, label: '扩展组件', desc: '', to: '' },
    { icon: ScrollText, label: '操作日志', desc: '查看与撤回操作', to: '' },
]

const triggerImport = () => {
    fileInput.value?.click()
}

const handleFileUpload = async (event: Event) => {
    const target = event.target as HTMLInputElement
    if (!store.currentBookId || !target.files?.length) return
    const file = target.files[0]
    if (!file) return
    uploading.value = true
    try {
        await importCsv(store.currentBookId, file)
        alert('导入成功！')
    } catch (e: any) {
        alert(e.response?.data?.detail || '导入失败')
    } finally {
        uploading.value = false
        target.value = ''
    }
}

const handleItemClick = (item: typeof managementItems[0]) => {
    if ('action' in item && item.action === 'import') {
        triggerImport()
    }
}

onMounted(async () => {
    if (!store.currentBookId) await store.fetchBooks()
    if (store.currentBookId) {
        loading.value = true
        try {
            const res = await getStatsOverview(store.currentBookId)
            overview.value = res.data
        } finally {
            loading.value = false
        }
    }
})
</script>

<template>
  <div class="pb-4">
    <!-- User Card -->
    <div class="mx-4 mt-4 rounded-2xl bg-gradient-to-r from-teal-500 to-teal-400 dark:from-teal-700 dark:to-teal-600 p-5 text-white shadow-lg">
      <div class="flex items-center gap-4 mb-4">
        <div class="w-16 h-16 rounded-full bg-white/20 flex items-center justify-center">
          <User class="w-8 h-8 text-white" />
        </div>
        <div>
          <h2 class="text-xl font-bold">{{ authStore.user?.display_name || authStore.user?.email || '用户' }}</h2>
          <p class="text-sm opacity-80">ID: {{ authStore.user?.id }}</p>
        </div>
      </div>
      <div class="grid grid-cols-3 text-center">
        <div>
          <p class="text-2xl font-bold">{{ overview.days }}</p>
          <p class="text-xs opacity-80">记账天数</p>
        </div>
        <div>
          <p class="text-2xl font-bold">{{ overview.transactions }}</p>
          <p class="text-xs opacity-80">交易笔数</p>
        </div>
        <div>
          <p class="text-2xl font-bold">{{ formatMoney(overview.net_assets) }}</p>
          <p class="text-xs opacity-80">净资产</p>
        </div>
      </div>
    </div>

    <!-- Management Grid -->
    <div class="mx-4 mt-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-4">
      <div class="grid grid-cols-4 gap-4">
        <button
          v-for="item in managementItems"
          :key="item.label"
          @click="handleItemClick(item)"
          class="flex flex-col items-center gap-1.5 py-2 hover:bg-gray-50 dark:hover:bg-slate-700 rounded-xl transition"
        >
          <div :class="['w-10 h-10 rounded-xl flex items-center justify-center', item.color]">
            <component :is="item.icon" class="w-5 h-5 text-white" />
          </div>
          <span class="text-xs font-medium text-theme-primary">{{ item.label }}</span>
        </button>
      </div>
    </div>

    <!-- Settings -->
    <div class="mx-4 mt-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 overflow-hidden">
      <div
        v-for="item in settingsItems"
        :key="item.label"
        class="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 dark:hover:bg-slate-700 transition cursor-pointer border-b border-gray-50 dark:border-slate-700/50 last:border-b-0"
      >
        <component :is="item.icon" class="w-5 h-5 text-theme-muted" />
        <span class="flex-1 font-medium text-theme-primary text-sm">{{ item.label }}</span>
        <span v-if="item.desc" class="text-xs text-theme-muted">{{ item.desc }}</span>
        <ChevronRight class="w-4 h-4 text-theme-muted" />
      </div>
    </div>

    <!-- Hidden file input for CSV import -->
    <input
      type="file"
      ref="fileInput"
      accept=".csv"
      class="hidden"
      @change="handleFileUpload"
    />
  </div>
</template>
