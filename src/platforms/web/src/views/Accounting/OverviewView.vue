<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, watch, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useAccountingStore } from '@/stores/accounting'
import {
    getRecordsSummary, getDailySummary, getRecords, createBook, getBudgets, autoCreateRecordFromImage,
    type MonthlySummary, type DailySummaryItem, type RecordItem, type Book, type Budget,
} from '@/api/accounting'
import {
    ChevronDown, ChevronRight, Plus, Loader2, ChevronLeft,
} from 'lucide-vue-next'
import QuickAddFab from '@/components/accounting/QuickAddFab.vue'
import BudgetProgressRing from '@/components/accounting/BudgetProgressRing.vue'
import RecordRow from '@/components/accounting/RecordRow.vue'
import PullRefreshIndicator from '@/components/accounting/PullRefreshIndicator.vue'
import AccountingLoadingState from '@/components/accounting/AccountingLoadingState.vue'
import AccountingEmptyState from '@/components/accounting/AccountingEmptyState.vue'
import AccountingErrorState from '@/components/accounting/AccountingErrorState.vue'
import { usePullToRefresh } from '@/composables/usePullToRefresh'
import { formatAccountingMoney } from '@/utils/accountingFormat'
import {
    accountingErrorMessage,
    accountingToastError,
} from '@/utils/accountingToast'
import * as echarts from 'echarts'

const store = useAccountingStore()
const router = useRouter()

const now = new Date()
const currentYear = ref(now.getFullYear())
const currentMonth = ref(now.getMonth() + 1)

const summary = ref<MonthlySummary>({ income: 0, expense: 0, balance: 0 })
const dailyData = ref<DailySummaryItem[]>([])
const loadError = ref('')
const recentRecords = ref<RecordItem[]>([])
const currentBudget = ref<Budget | null>(null)
const loading = ref(false)
const showBookDropdown = ref(false)
const showClipboardPrompt = ref(false)
const showIOSClipboardHint = ref(false)
const clipboardImageFile = ref<File | null>(null)
const clipboardPreviewUrl = ref('')
const uploadImageInputRef = ref<HTMLInputElement | null>(null)
const clipboardSubmitting = ref(false)
const clipboardStage = ref<'uploading' | 'recognizing' | 'writing'>('uploading')
const clipboardError = ref('')
const successTip = ref('')
let successTipTimer: ReturnType<typeof setTimeout> | null = null
const pageRef = ref<HTMLElement | null>(null)

const showCreateBook = ref(false)
const newBookName = ref('')
const creatingBook = ref(false)

const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

const monthLabel = computed(() => `${currentYear.value}年${currentMonth.value}月`)

const prevMonth = () => {
    if (currentMonth.value === 1) {
        currentMonth.value = 12
        currentYear.value -= 1
    } else {
        currentMonth.value -= 1
    }
}

const nextMonth = () => {
    if (currentMonth.value === 12) {
        currentMonth.value = 1
        currentYear.value += 1
    } else {
        currentMonth.value += 1
    }
}

const loadData = async () => {
    if (!store.currentBookId) return
    loading.value = true
    loadError.value = ''
    try {
        const formattedMonth = `${currentYear.value}-${String(currentMonth.value).padStart(2, '0')}`
        const [sumRes, dailyRes, recRes, budgetRes] = await Promise.all([
            getRecordsSummary(store.currentBookId, currentYear.value, currentMonth.value),
            getDailySummary(store.currentBookId, currentYear.value, currentMonth.value),
            getRecords(store.currentBookId, 5),
            getBudgets(store.currentBookId, formattedMonth),
        ])
        summary.value = sumRes.data
        dailyData.value = dailyRes.data
        recentRecords.value = recRes.data
        const globalB = budgetRes.data.find(b => !b.category_id)
        currentBudget.value = globalB || null

        await nextTick()
        renderChart()
    } catch (e) {
        loadError.value = accountingErrorMessage(e, '首页数据加载失败')
        accountingToastError(loadError.value)
    } finally {
        loading.value = false
    }
}

const {
    refreshing,
    pullDistance,
    pullHint,
    handleTouchStart,
    handleTouchMove,
    handleTouchEnd,
} = usePullToRefresh({
    pageRef,
    onRefresh: async () => {
        if (!store.currentBookId) await store.fetchBooks()
        await loadData()
    },
})

const renderChart = () => {
    if (!chartRef.value) return
    if (!chartInstance) {
        chartInstance = echarts.init(chartRef.value)
    }
    const days = dailyData.value.map(d => {
        const parts = d.date.split('-')
        return `${parts[1]}.${parts[2]}`
    })
    const expenses = dailyData.value.map(d => d.expense)

    chartInstance.setOption({
        grid: { top: 10, right: 10, bottom: 25, left: 40 },
        xAxis: {
            type: 'category',
            data: days.length > 0 ? days : generateDayLabels(),
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: '#9ca3af', fontSize: 11 },
        },
        yAxis: {
            type: 'value',
            show: false,
        },
        series: [{
            type: 'line',
            data: expenses,
            smooth: true,
            symbol: 'none',
            lineStyle: { color: 'var(--color-accounting-brand, #0090ff)', width: 2 },
            areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: 'rgba(0,144,255,0.28)' },
                    { offset: 1, color: 'rgba(0,144,255,0.02)' },
                ]),
            },
        }],
    })
}

const generateDayLabels = () => {
    const daysInMonth = new Date(currentYear.value, currentMonth.value, 0).getDate()
    const labels = []
    const step = Math.max(1, Math.floor(daysInMonth / 7))
    for (let i = 1; i <= daysInMonth; i += step) {
        labels.push(`${currentMonth.value}.${i}`)
    }
    return labels
}

const handleCreateBook = async () => {
    if (!newBookName.value.trim()) return
    creatingBook.value = true
    try {
        const res = await createBook(newBookName.value.trim())
        store.books.push(res.data)
        store.setCurrentBook(res.data.id)
        newBookName.value = ''
        showCreateBook.value = false
        await loadData()
    } finally {
        creatingBook.value = false
    }
}

const switchBook = async (book: Book) => {
    store.setCurrentBook(book.id)
    showBookDropdown.value = false
    await loadData()
}

const remainingDays = computed(() => {
    const daysInMonth = new Date(currentYear.value, currentMonth.value, 0).getDate()
    const isCurrentMonth =
        currentYear.value === now.getFullYear() && currentMonth.value === now.getMonth() + 1
    if (!isCurrentMonth) return daysInMonth
    return Math.max(1, daysInMonth - now.getDate() + 1)
})

const dailyRemaining = computed(() => {
    if (!currentBudget.value) return 0
    const left = currentBudget.value.total_amount - summary.value.expense
    if (left <= 0) return 0
    return left / remainingDays.value
})

const readClipboardImage = async (): Promise<File | null> => {
    if (typeof window === 'undefined' || !window.isSecureContext) return null
    if (!navigator.clipboard || typeof navigator.clipboard.read !== 'function') return null
    try {
        const items = await navigator.clipboard.read()
        for (const item of items) {
            const imageType = item.types.find(type => type.startsWith('image/'))
            if (!imageType) continue
            const blob = await item.getType(imageType)
            const ext = imageType.split('/')[1] || 'png'
            return new File([blob], `clipboard-${Date.now()}.${ext}`, { type: imageType })
        }
        return null
    } catch (error) {
        console.debug('read clipboard image failed', error)
        return null
    }
}

const showImageAutoAccountingPrompt = (file: File) => {
    clipboardImageFile.value = file
    releaseClipboardPreview()
    clipboardPreviewUrl.value = URL.createObjectURL(file)
    clipboardError.value = ''
    clipboardSubmitting.value = false
    clipboardStage.value = 'uploading'
    showClipboardPrompt.value = true
}

const openUploadImagePicker = () => {
    uploadImageInputRef.value?.click()
}

const handleUploadImageChange = (event: Event) => {
    const input = event.target as HTMLInputElement | null
    const file = input?.files?.[0] ?? null
    if (input) input.value = ''
    if (!file || !file.type.startsWith('image/')) return
    showIOSClipboardHint.value = false
    showImageAutoAccountingPrompt(file)
}

const releaseClipboardPreview = () => {
    if (clipboardPreviewUrl.value) URL.revokeObjectURL(clipboardPreviewUrl.value)
    clipboardPreviewUrl.value = ''
}

const closeClipboardPrompt = () => {
    showClipboardPrompt.value = false
    clipboardSubmitting.value = false
    clipboardError.value = ''
    clipboardImageFile.value = null
    releaseClipboardPreview()
}

const showSuccessTip = (text: string) => {
    successTip.value = text
    if (successTipTimer) clearTimeout(successTipTimer)
    successTipTimer = setTimeout(() => {
        successTip.value = ''
        successTipTimer = null
    }, 1800)
}

const handleImageFabClick = async () => {
    if (!store.currentBookId || clipboardSubmitting.value) return
    const image = await readClipboardImage()
    if (image) {
        showImageAutoAccountingPrompt(image)
        return
    }
    showIOSClipboardHint.value = true
}

const startClipboardAutoAccounting = async () => {
    if (!store.currentBookId || !clipboardImageFile.value || clipboardSubmitting.value) return
    clipboardSubmitting.value = true
    clipboardError.value = ''
    clipboardStage.value = 'uploading'
    await new Promise(resolve => window.setTimeout(resolve, 180))
    try {
        clipboardStage.value = 'recognizing'
        const res = await autoCreateRecordFromImage(store.currentBookId, clipboardImageFile.value)
        const recordId = Number(res.data?.record_id || 0)
        if (!Number.isFinite(recordId) || recordId <= 0) throw new Error('未返回有效记录ID')
        clipboardStage.value = 'writing'
        await new Promise(resolve => window.setTimeout(resolve, 160))
        closeClipboardPrompt()
        showSuccessTip('记账成功')
        await loadData()
        await router.push({ name: 'RecordDetail', params: { id: recordId } })
    } catch (error: any) {
        clipboardError.value = error?.response?.data?.detail || error?.message || '自动记账失败，请手动记账'
    } finally {
        clipboardSubmitting.value = false
    }
}

watch([currentYear, currentMonth], () => {
    if (store.currentBookId) void loadData()
})

watch(() => store.currentBookId, () => {
    if (store.currentBookId) loadData()
})

onMounted(async () => {
    await store.fetchBooks()
    if (store.currentBookId) await loadData()
})

onBeforeUnmount(() => {
    if (successTipTimer) {
        clearTimeout(successTipTimer)
        successTipTimer = null
    }
    releaseClipboardPreview()
    chartInstance?.dispose()
    chartInstance = null
})
</script>

<template>
  <div
    ref="pageRef"
    class="accounting-page-pad accounting-overview-page"
    @touchstart="handleTouchStart"
    @touchmove="handleTouchMove"
    @touchend="handleTouchEnd"
    @touchcancel="handleTouchEnd"
  >
    <input
      ref="uploadImageInputRef"
      type="file"
      accept="image/*"
      class="hidden"
      @change="handleUploadImageChange"
    >

    <PullRefreshIndicator :distance="pullDistance" :hint="pullHint" :refreshing="refreshing" />

    <!-- Book Selector -->
    <div class="px-4 pt-3 pb-2 flex items-center justify-between">
      <div class="relative">
        <button
          type="button"
          class="accounting-ledger-select flex items-center gap-1 text-lg font-bold text-theme-primary"
          @click="showBookDropdown = !showBookDropdown"
        >
          {{ store.books.find(b => b.id === store.currentBookId)?.name || '选择账本' }}
          <ChevronDown class="w-4 h-4" />
        </button>

        <div
          v-if="showBookDropdown"
          class="absolute top-full left-0 mt-1 bg-theme-elevated border border-theme-secondary rounded-xl shadow-lg py-1 min-w-[160px] z-30"
        >
          <button
            v-for="book in store.books"
            :key="book.id"
            type="button"
            :class="[
              'w-full text-left px-4 py-2 text-sm transition',
              book.id === store.currentBookId
                ? 'bg-theme-secondary text-accounting-brand font-medium'
                : 'text-theme-primary hover:bg-theme-secondary'
            ]"
            @click="switchBook(book)"
          >
            {{ book.name }}
          </button>
          <div class="border-t border-theme-secondary mt-1 pt-1">
            <button
              type="button"
              class="w-full text-left px-4 py-2 text-sm text-accounting-brand hover:bg-theme-secondary flex items-center gap-2"
              @click="showCreateBook = true; showBookDropdown = false"
            >
              <Plus class="w-3.5 h-3.5" /> 新建账本
            </button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="store.books.length === 0 && !store.loading" class="px-4 py-12 text-center">
      <div class="w-20 h-20 mx-auto mb-4 rounded-full bg-theme-secondary flex items-center justify-center">
        <Plus class="w-8 h-8 text-accounting-brand" />
      </div>
      <h3 class="text-lg font-semibold text-theme-primary mb-2">还没有账本</h3>
      <p class="text-theme-muted text-sm mb-4">创建一个账本开始记账吧</p>
      <button
        type="button"
        class="px-6 py-2.5 bg-accounting-brand hover:opacity-90 text-white font-medium rounded-xl transition shadow-sm"
        @click="showCreateBook = true"
      >
        创建第一个账本
      </button>
    </div>

    <div
      v-if="showCreateBook"
      class="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4"
      @click.self="showCreateBook = false"
    >
      <div class="bg-theme-elevated rounded-t-2xl sm:rounded-2xl p-5 sm:p-6 w-full sm:w-[360px] max-h-[90dvh] overflow-y-auto accounting-scroll shadow-xl safe-bottom">
        <h3 class="text-lg font-semibold text-theme-primary mb-4">新建账本</h3>
        <form @submit.prevent="handleCreateBook">
          <input
            v-model="newBookName"
            type="text"
            placeholder="输入账本名称…"
            class="accounting-field mb-4"
            autofocus
          />
          <div class="flex gap-3">
            <button
              type="button"
              class="flex-1 py-2.5 border border-theme-primary rounded-xl text-theme-secondary font-medium hover:bg-theme-secondary transition"
              @click="showCreateBook = false"
            >
              取消
            </button>
            <button
              type="submit"
              :disabled="creatingBook || !newBookName.trim()"
              class="flex-1 py-2.5 bg-accounting-brand hover:opacity-90 text-white font-medium rounded-xl transition disabled:opacity-50"
            >
              <Loader2 v-if="creatingBook" class="w-4 h-4 animate-spin mx-auto" />
              <span v-else>创建</span>
            </button>
          </div>
        </form>
      </div>
    </div>

    <template v-if="store.currentBookId">
      <!-- Month navigation -->
      <div class="accounting-month-switcher mx-3 sm:mx-4 mt-1 flex items-center justify-between rounded-2xl bg-theme-elevated border border-theme-secondary px-1 py-1.5 shadow-sm">
        <button type="button" class="accounting-touch-target inline-flex items-center justify-center p-2 rounded-xl active:bg-theme-secondary" aria-label="上一月" @click="prevMonth">
          <ChevronLeft class="w-5 h-5 text-theme-secondary" />
        </button>
        <span class="text-sm font-semibold text-theme-primary">{{ monthLabel }}</span>
        <button type="button" class="accounting-touch-target inline-flex items-center justify-center p-2 rounded-xl active:bg-theme-secondary" aria-label="下一月" @click="nextMonth">
          <ChevronLeft class="w-5 h-5 text-theme-secondary rotate-180" />
        </button>
      </div>

      <!-- Monthly Summary Card -->
      <div class="accounting-summary-card mx-3 sm:mx-4 mt-3 rounded-2xl bg-theme-elevated shadow-sm border border-theme-secondary overflow-hidden">
        <div class="p-3 sm:p-4">
          <RouterLink
            :to="{ name: 'StatsAmountDetail', query: { year: currentYear, month: currentMonth, type: '支出' } }"
            class="flex items-center justify-between mb-3 cursor-pointer active:opacity-80 transition"
          >
            <span class="text-sm text-theme-muted">{{ currentMonth }}月收支</span>
            <ChevronRight class="w-4 h-4 text-accounting-brand" />
          </RouterLink>
          <div class="grid grid-cols-3 gap-2">
            <div class="min-w-0">
              <p class="text-xs text-theme-muted mb-1">支出</p>
              <p class="text-lg sm:text-2xl font-bold text-accounting-expense tabular-nums break-all leading-tight">
                {{ formatAccountingMoney(summary.expense) }}
              </p>
            </div>
            <div class="min-w-0">
              <p class="text-xs text-theme-muted mb-1">收入</p>
              <p class="text-lg sm:text-2xl font-bold text-accounting-income tabular-nums break-all leading-tight">
                {{ formatAccountingMoney(summary.income) }}
              </p>
            </div>
            <div class="min-w-0">
              <p class="text-xs text-theme-muted mb-1">结余</p>
              <p class="text-lg sm:text-2xl font-bold text-theme-primary tabular-nums break-all leading-tight">
                {{ formatAccountingMoney(summary.balance) }}
              </p>
            </div>
          </div>
        </div>
        <div ref="chartRef" class="w-full h-[148px]" />
      </div>

      <!-- Recent Transactions -->
      <div class="mx-4 mt-4 rounded-2xl bg-theme-elevated shadow-sm border border-theme-secondary">
        <RouterLink to="/accounting/records" class="flex items-center justify-between p-4 pb-2 cursor-pointer hover:opacity-80 transition">
          <h3 class="font-semibold text-theme-primary">最近交易</h3>
          <ChevronRight class="w-4 h-4 text-accounting-brand" />
        </RouterLink>

        <AccountingLoadingState v-if="loading" />
        <AccountingErrorState
          v-else-if="loadError"
          title="加载失败"
          :description="loadError"
          @retry="loadData"
        />
        <AccountingEmptyState
          v-else-if="recentRecords.length === 0"
          title="暂无记录"
          description="点击右下角 + 开始记账"
        />
        <ul v-else class="divide-y divide-[var(--color-border-secondary)]">
          <li v-for="rec in recentRecords" :key="rec.id">
            <RouterLink :to="`/accounting/records/${rec.id}`" class="block hover:bg-theme-secondary/50 transition">
              <RecordRow
                :id="rec.id"
                :type="rec.type"
                :amount="rec.amount"
                :category="rec.category"
                :payee="rec.payee"
                :remark="rec.remark"
                :account="rec.account"
                :target-account="rec.target_account"
                :record-time="rec.record_time"
                :show-date="true"
                :show-chevron="true"
              />
            </RouterLink>
          </li>
        </ul>
      </div>

      <!-- Budget -->
      <div class="mx-4 mt-4 rounded-2xl bg-theme-elevated shadow-sm border border-theme-secondary p-4">
        <RouterLink to="/accounting/budgets" class="flex items-center justify-between mb-4 cursor-pointer hover:opacity-80 transition">
          <h3 class="font-semibold text-theme-primary">{{ currentMonth }}月预算</h3>
          <ChevronRight class="w-4 h-4 text-accounting-brand" />
        </RouterLink>
        <div class="flex items-center justify-around">
          <div class="text-center">
            <p class="text-xs text-theme-muted">支出</p>
            <p class="text-lg font-bold text-theme-primary tabular-nums">{{ formatAccountingMoney(summary.expense) }}</p>
          </div>
          <RouterLink to="/accounting/budgets" class="cursor-pointer hover:opacity-80 transition">
            <BudgetProgressRing
              :spent="summary.expense"
              :total="currentBudget?.total_amount || 0"
            />
          </RouterLink>
          <div class="text-center">
            <p class="text-xs text-theme-muted">剩余日均</p>
            <p class="text-lg font-bold text-theme-primary tabular-nums">
              {{ formatAccountingMoney(dailyRemaining) }}
            </p>
          </div>
        </div>
      </div>
    </template>

    <QuickAddFab
      :book-id="store.currentBookId"
      :show-image="true"
      @saved="loadData"
      @image="handleImageFabClick"
    />

    <div
      v-if="successTip"
      class="fixed top-20 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-xl bg-slate-900 text-white text-sm shadow-lg"
    >
      {{ successTip }}
    </div>

    <div
      v-if="showClipboardPrompt"
      class="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/45 p-0 sm:p-4"
      @click.self="!clipboardSubmitting && closeClipboardPrompt()"
    >
      <div class="w-full sm:max-w-[360px] rounded-t-2xl sm:rounded-2xl bg-theme-elevated border border-theme-secondary shadow-xl p-4 safe-bottom">
        <template v-if="!clipboardSubmitting">
          <h3 class="text-base font-semibold text-theme-primary mb-2">已选择图片</h3>
          <p class="text-sm text-theme-muted">是否直接让 AI 识别并记账？</p>
          <img
            v-if="clipboardPreviewUrl"
            :src="clipboardPreviewUrl"
            alt="clipboard preview"
            class="mt-3 w-full max-h-44 object-contain rounded-xl border border-theme-secondary bg-theme-secondary"
          />
          <p v-if="clipboardError" class="mt-3 text-sm text-accounting-expense">{{ clipboardError }}</p>
          <div class="mt-4 flex gap-2">
            <button type="button" class="flex-1 h-10 rounded-xl border border-theme-primary text-theme-secondary" @click="closeClipboardPrompt">取消</button>
            <button type="button" class="flex-1 h-10 rounded-xl border border-accounting-brand text-accounting-brand" @click="closeClipboardPrompt(); /* open via fab */">手动记账</button>
            <button type="button" class="flex-1 h-10 rounded-xl bg-accounting-brand text-white" @click="startClipboardAutoAccounting">识别并记账</button>
          </div>
        </template>
        <template v-else>
          <h3 class="text-base font-semibold text-theme-primary mb-3">正在处理</h3>
          <div class="space-y-2 text-sm">
            <div class="flex items-center justify-between rounded-xl px-3 py-2 bg-theme-secondary">
              <span>上传中</span>
              <Loader2 v-if="clipboardStage === 'uploading'" class="w-4 h-4 animate-spin text-accounting-brand" />
              <span v-else class="text-accounting-income">完成</span>
            </div>
            <div class="flex items-center justify-between rounded-xl px-3 py-2 bg-theme-secondary">
              <span>AI识别中</span>
              <Loader2 v-if="clipboardStage === 'recognizing'" class="w-4 h-4 animate-spin text-accounting-brand" />
              <span v-else-if="clipboardStage === 'writing'" class="text-accounting-income">完成</span>
              <span v-else class="text-theme-muted">等待</span>
            </div>
            <div class="flex items-center justify-between rounded-xl px-3 py-2 bg-theme-secondary">
              <span>写入账本</span>
              <Loader2 v-if="clipboardStage === 'writing'" class="w-4 h-4 animate-spin text-accounting-brand" />
              <span v-else class="text-theme-muted">等待</span>
            </div>
          </div>
        </template>
      </div>
    </div>

    <div
      v-if="showIOSClipboardHint"
      class="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/45 p-0 sm:p-4"
      @click.self="showIOSClipboardHint = false"
    >
      <div class="w-full sm:max-w-[360px] rounded-t-2xl sm:rounded-2xl bg-theme-elevated border border-theme-secondary shadow-xl p-4 safe-bottom">
        <h3 class="text-base font-semibold text-theme-primary mb-2">未检测到可读取的剪贴板图片</h3>
        <p class="text-sm text-theme-muted">你可以上传截图识别，或切换为手动记账。</p>
        <div class="mt-4 flex gap-2 justify-end">
          <button type="button" class="px-4 h-10 rounded-xl border border-accounting-brand text-accounting-brand" @click="showIOSClipboardHint = false; openUploadImagePicker()">上传图片识别</button>
          <button type="button" class="px-4 h-10 rounded-xl border border-theme-primary text-theme-secondary" @click="showIOSClipboardHint = false">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>
