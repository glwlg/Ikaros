<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useAccountingStore } from '@/stores/accounting'
import {
    getCategorySummaryByRange,
    getRangeSummary,
    type CategorySummaryItem,
    type PeriodSummaryItem,
} from '@/api/accounting'
import { ChevronDown, ChevronRight, Loader2 } from 'lucide-vue-next'
import * as echarts from 'echarts'
import {
    createDefaultCustomRangeState,
    getRangeWindow,
    isCustomPreset,
    rangeOptions,
    toIsoLocal,
    type Granularity,
    type RangePreset,
} from './statsRange'
import {
    loadStatsPanels,
    type StatsPanelConfig,
} from '@/utils/accountingLocal'

type StatType = '支出' | '收入'

const store = useAccountingStore()
const router = useRouter()
const now = new Date()

const statType = ref<StatType>('支出')
const rangePreset = ref<RangePreset>('last_12_months')
const customRange = ref(createDefaultCustomRangeState(now))
const showRangeDialog = ref(false)
const statsPanels = ref<StatsPanelConfig[]>([])

const timeWindow = computed(() => getRangeWindow(rangePreset.value, customRange.value, now))
const timeLabel = computed(() => timeWindow.value.label)
const isCustomRange = computed(() => isCustomPreset(rangePreset.value))

const enabledPanels = computed(() => {
    return statsPanels.value
        .filter(panel => panel.enabled)
        .sort((a, b) => a.sort_order - b.sort_order)
})

const primaryCategoryPanelId = computed(() => {
    return enabledPanels.value.find(panel => panel.kind === 'category')?.id || ''
})

const primaryTrendPanelId = computed(() => {
    return enabledPanels.value.find(panel => panel.kind === 'trend')?.id || ''
})

const primaryTeamPanelId = computed(() => {
    return enabledPanels.value.find(panel => panel.kind === 'team')?.id || ''
})

const categoryData = ref<CategorySummaryItem[]>([])
const trendData = ref<PeriodSummaryItem[]>([])
const loading = ref(false)
const currentGranularity = ref<Granularity>('day')

const granularityLabel = computed(() => {
    if (currentGranularity.value === 'day') return '天'
    if (currentGranularity.value === 'week') return '周'
    if (currentGranularity.value === 'month') return '月'
    if (currentGranularity.value === 'quarter') return '季'
    return '年'
})

const pieRef = ref<HTMLElement | null>(null)
const barRef = ref<HTMLElement | null>(null)
let pieChart: echarts.ECharts | null = null
let barChart: echarts.ECharts | null = null
let pieResizeObserver: ResizeObserver | null = null
let barResizeObserver: ResizeObserver | null = null
let delayedRenderTimer: ReturnType<typeof setTimeout> | null = null
let loadVersion = 0

const formatMoney = (n: number) =>
    new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(n)

const totalCategory = () => categoryData.value.reduce((sum, item) => sum + item.amount, 0)

const formatPeriodLabel = (period: string) => {
    if (currentGranularity.value === 'day') return period.slice(5)
    if (currentGranularity.value === 'week') return period.replace(/^\d{4}-/, '')
    if (currentGranularity.value === 'month') return period.replace('-', '/')
    return period
}

const subjectLabels: Record<string, string> = {
    dynamic: '动态日期',
    year: '年',
    quarter: '季',
    month: '月',
    week: '周',
    day: '日',
    amount: '金额',
    category: '分类',
    account: '账户',
    project: '项目',
}

const metricLabels: Record<string, string> = {
    sum: '总额',
    avg: '平均值',
    max: '最大值',
    min: '最小值',
    count: '数量',
}

const tealColors = [
    '#14b8a6', '#06b6d4', '#0ea5e9', '#6366f1', '#8b5cf6',
    '#d946ef', '#f43f5e', '#f97316', '#eab308', '#22c55e',
]

const canInitChart = (el: HTMLElement | null) => {
    return Boolean(el && el.clientWidth > 0 && el.clientHeight > 0)
}

const renderPie = () => {
    if (!canInitChart(pieRef.value)) return false
    if (!pieChart && pieRef.value) {
        pieChart = echarts.init(pieRef.value)
    }
    if (!pieChart) return false

    const data = categoryData.value.map((item, index) => ({
        name: item.category,
        value: item.amount,
        itemStyle: { color: tealColors[index % tealColors.length] },
    }))

    pieChart.setOption({
        tooltip: { trigger: 'item', formatter: '{b}: ¥{c} ({d}%)' },
        series: [{
            type: 'pie',
            radius: ['55%', '80%'],
            center: ['50%', '50%'],
            label: { show: false },
            data: data.length > 0 ? data : [{ name: '暂无', value: 0, itemStyle: { color: '#e5e7eb' } }],
        }],
        graphic: [{
            type: 'text',
            left: 'center',
            top: '42%',
            style: { text: '全部', fill: '#9ca3af', fontSize: 12 },
        }, {
            type: 'text',
            left: 'center',
            top: '52%',
            style: {
                text: formatMoney(totalCategory()),
                fill: '#111827',
                fontSize: 16,
                fontWeight: 'bold',
            },
        }],
    })
    pieChart.resize()
    return true
}

const renderBar = () => {
    if (!canInitChart(barRef.value)) return false
    if (!barChart && barRef.value) {
        barChart = echarts.init(barRef.value)
    }
    if (!barChart) return false

    const xAxisData = trendData.value.map(item => formatPeriodLabel(item.period))
    const seriesData = trendData.value.map(item => statType.value === '支出' ? item.expense : item.income)

    barChart.setOption({
        grid: { top: 10, right: 10, bottom: 25, left: 50 },
        xAxis: {
            type: 'category',
            data: xAxisData,
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: '#9ca3af', fontSize: 11 },
        },
        yAxis: {
            type: 'value',
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: { lineStyle: { color: '#f3f4f6' } },
            axisLabel: {
                color: '#9ca3af',
                fontSize: 10,
                formatter: (v: number) => v >= 10000 ? `${(v / 10000).toFixed(0)}w` : `${v}`,
            },
        },
        series: [{
            type: 'bar',
            data: seriesData,
            barWidth: 24,
            itemStyle: {
                color: statType.value === '支出' ? '#f87171' : '#14b8a6',
                borderRadius: [4, 4, 0, 0],
            },
        }],
    })
    barChart.resize()
    return true
}

const renderChartsSafely = async () => {
    await nextTick()
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))

    const pieReady = renderPie()
    const barReady = renderBar()

    if (pieReady && barReady) return

    if (delayedRenderTimer) {
        clearTimeout(delayedRenderTimer)
    }
    delayedRenderTimer = setTimeout(() => {
        renderPie()
        renderBar()
    }, 120)
}

const loadData = async () => {
    if (!store.currentBookId) return

    const current = ++loadVersion
    const window = timeWindow.value
    currentGranularity.value = window.granularity
    loading.value = true

    try {
        const [categoryRes, trendRes] = await Promise.all([
            getCategorySummaryByRange(
                store.currentBookId,
                toIsoLocal(window.start),
                toIsoLocal(window.end),
                statType.value,
            ),
            getRangeSummary(
                store.currentBookId,
                toIsoLocal(window.start),
                toIsoLocal(window.end),
                window.granularity,
            ),
        ])

        if (current !== loadVersion) return
        categoryData.value = categoryRes.data
        trendData.value = trendRes.data
    } catch (error) {
        if (current !== loadVersion) return
        console.error('stats load failed', error)
        categoryData.value = []
        trendData.value = []
    } finally {
        if (current === loadVersion) {
            loading.value = false
        }
    }

    if (current !== loadVersion) return
    await renderChartsSafely()
}

const reloadPanels = () => {
    statsPanels.value = loadStatsPanels(store.currentBookId)
}

const selectRange = (nextPreset: RangePreset) => {
    rangePreset.value = nextPreset
    showRangeDialog.value = false
}

const metricValueForPanel = (panel: StatsPanelConfig) => {
    const amountSeries = trendData.value.map(item => panel.default_type === '收入' ? item.income : item.expense)
    const countSeries = trendData.value.map(item => panel.default_type === '收入' ? (item.income_count || 0) : (item.expense_count || 0))

    if (panel.metric === 'count') {
        return countSeries.reduce((sum, n) => sum + n, 0)
    }

    if (amountSeries.length === 0) return 0
    if (panel.metric === 'sum') return amountSeries.reduce((sum, n) => sum + n, 0)
    if (panel.metric === 'avg') return amountSeries.reduce((sum, n) => sum + n, 0) / amountSeries.length
    if (panel.metric === 'max') return Math.max(...amountSeries)
    if (panel.metric === 'min') return Math.min(...amountSeries)
    return 0
}

const makeDetailQueryForPanel = (panel: StatsPanelConfig) => {
    const window = timeWindow.value
    const type = panel.id === primaryCategoryPanelId.value || panel.id === primaryTrendPanelId.value
        ? statType.value
        : panel.default_type

    return {
        start: toIsoLocal(window.start),
        end: toIsoLocal(window.end),
        label: window.label,
        granularity: window.granularity,
        type,
        panel_id: panel.id,
        category: panel.default_category,
    }
}

const openPanelDetail = (panel: StatsPanelConfig) => {
    const query = makeDetailQueryForPanel(panel)
    if (panel.kind === 'category') {
        router.push({ name: 'StatsCategoryDetail', query })
        return
    }
    if (panel.kind === 'team') {
        router.push({ name: 'StatsTeamDetail', query })
        return
    }
    router.push({ name: 'StatsTrendDetail', query })
}

const goPanelManager = () => {
    router.push({ name: 'StatsPanelManage' })
}

watch([statType, rangePreset], () => {
    loadData()
})

watch(
    () => customRange.value,
    () => {
        if (isCustomRange.value) {
            loadData()
        }
    },
    { deep: true }
)

watch(
    () => store.currentBookId,
    () => {
        reloadPanels()
    }
)

onMounted(async () => {
    if (!store.currentBookId) await store.fetchBooks()
    reloadPanels()
    await loadData()

    if (typeof ResizeObserver !== 'undefined') {
        pieResizeObserver = new ResizeObserver(() => pieChart?.resize())
        barResizeObserver = new ResizeObserver(() => barChart?.resize())
        if (pieRef.value) pieResizeObserver.observe(pieRef.value)
        if (barRef.value) barResizeObserver.observe(barRef.value)
    }

    window.addEventListener('resize', renderChartsSafely)
})

onBeforeUnmount(() => {
    window.removeEventListener('resize', renderChartsSafely)

    pieResizeObserver?.disconnect()
    barResizeObserver?.disconnect()
    pieResizeObserver = null
    barResizeObserver = null

    if (delayedRenderTimer) {
        clearTimeout(delayedRenderTimer)
        delayedRenderTimer = null
    }

    pieChart?.dispose()
    barChart?.dispose()
    pieChart = null
    barChart = null
})
</script>

<template>
  <div class="pb-4">
    <div class="px-4 py-2">
      <button
        @click="showRangeDialog = true"
        class="w-full rounded-2xl bg-white dark:bg-slate-800 border border-gray-100 dark:border-slate-700 shadow-sm px-4 py-3 flex items-center justify-between"
      >
        <div class="text-left">
          <p class="text-xs text-theme-muted">日期范围</p>
          <p class="text-sm font-semibold text-theme-primary mt-0.5">{{ timeLabel }}</p>
        </div>
        <ChevronDown class="w-4 h-4 text-theme-muted" />
      </button>
    </div>

    <div v-if="isCustomRange" class="mx-4 mt-1 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-4 space-y-3">
      <template v-if="rangePreset === 'year_range'">
        <div class="grid grid-cols-2 gap-2">
          <select v-model.number="customRange.yearStart" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm">
            <option v-for="y in 11" :key="`ys-${y}`" :value="now.getFullYear() - 9 + y">{{ now.getFullYear() - 9 + y }}年</option>
          </select>
          <select v-model.number="customRange.yearEnd" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm">
            <option v-for="y in 11" :key="`ye-${y}`" :value="now.getFullYear() - 9 + y">{{ now.getFullYear() - 9 + y }}年</option>
          </select>
        </div>
      </template>

      <template v-else-if="rangePreset === 'quarter_range'">
        <div class="grid grid-cols-2 gap-2">
          <input v-model.number="customRange.quarterStartYear" type="number" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
          <select v-model.number="customRange.quarterStartQuarter" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm">
            <option v-for="q in [1,2,3,4]" :key="`qs-${q}`" :value="q">Q{{ q }}</option>
          </select>
          <input v-model.number="customRange.quarterEndYear" type="number" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
          <select v-model.number="customRange.quarterEndQuarter" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm">
            <option v-for="q in [1,2,3,4]" :key="`qe-${q}`" :value="q">Q{{ q }}</option>
          </select>
        </div>
      </template>

      <template v-else-if="rangePreset === 'month_range'">
        <div class="grid grid-cols-2 gap-2">
          <input v-model="customRange.monthStart" type="month" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
          <input v-model="customRange.monthEnd" type="month" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
        </div>
      </template>

      <template v-else-if="rangePreset === 'week_range'">
        <div class="grid grid-cols-2 gap-2">
          <input v-model="customRange.weekStart" type="week" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
          <input v-model="customRange.weekEnd" type="week" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
        </div>
      </template>

      <template v-else-if="rangePreset === 'day_range'">
        <div class="grid grid-cols-2 gap-2">
          <input v-model="customRange.dayStart" type="date" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
          <input v-model="customRange.dayEnd" type="date" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
        </div>
      </template>
    </div>

    <template v-for="(panel, index) in enabledPanels" :key="panel.id">
      <div :class="['mx-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-4', index === 0 ? 'mt-2' : 'mt-4']">
        <div class="flex items-center justify-between mb-1">
          <h3 class="font-bold text-theme-primary">{{ panel.name }}</h3>
          <button type="button" @click="openPanelDetail(panel)" class="p-1 rounded hover:bg-gray-100 dark:hover:bg-slate-700">
            <ChevronRight class="w-4 h-4 text-teal-500" />
          </button>
        </div>

        <template v-if="panel.id === primaryCategoryPanelId && panel.kind === 'category'">
          <p class="text-xs text-theme-muted mb-3">
            ¥{{ formatMoney(totalCategory()) }} · {{ timeLabel }} · {{ statType }}
          </p>

          <div class="flex gap-2 mb-3">
            <button
              @click="statType = '支出'"
              :class="['px-3 py-1 rounded-full text-xs font-medium transition', statType === '支出' ? 'bg-teal-500 text-white' : 'bg-gray-100 dark:bg-slate-700 text-theme-secondary']"
            >支出</button>
            <button
              @click="statType = '收入'"
              :class="['px-3 py-1 rounded-full text-xs font-medium transition', statType === '收入' ? 'bg-teal-500 text-white' : 'bg-gray-100 dark:bg-slate-700 text-theme-secondary']"
            >收入</button>
          </div>

          <div class="relative">
            <div ref="pieRef" class="w-full h-[220px] pointer-events-none"></div>
            <div v-if="loading" class="absolute inset-0 flex items-center justify-center bg-white/30 dark:bg-slate-800/30 rounded-xl">
              <Loader2 class="w-5 h-5 animate-spin text-teal-400" />
            </div>
          </div>
        </template>

        <template v-else-if="panel.id === primaryTrendPanelId && panel.kind === 'trend'">
          <p class="text-xs text-theme-muted mb-3">{{ timeLabel }} · 按{{ granularityLabel }} · {{ statType }}</p>

          <div class="relative">
            <div ref="barRef" class="w-full h-[220px] pointer-events-none"></div>
            <div v-if="loading" class="absolute inset-0 flex items-center justify-center bg-white/30 dark:bg-slate-800/30 rounded-xl">
              <Loader2 class="w-5 h-5 animate-spin text-teal-400" />
            </div>
          </div>
        </template>

        <template v-else-if="panel.id === primaryTeamPanelId && panel.kind === 'team'">
          <p class="text-xs text-theme-muted mb-3">¥0 · {{ timeLabel }} · 支出</p>
          <div class="w-32 h-32 mx-auto rounded-full border-[8px] border-gray-100 dark:border-slate-700 flex items-center justify-center">
            <div class="text-center">
              <p class="text-xs text-theme-muted">全部</p>
              <p class="text-lg font-bold text-theme-primary">0</p>
            </div>
          </div>
        </template>

        <template v-else>
          <p class="text-xs text-theme-muted mb-3">{{ panel.description || '自定义统计面板' }}</p>
          <div class="rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-700 p-3">
            <p class="text-xs text-theme-muted">{{ metricLabels[panel.metric] || '统计值' }}</p>
            <p class="text-xl font-semibold text-theme-primary mt-1">{{ panel.metric === 'count' ? metricValueForPanel(panel) : `¥${formatMoney(metricValueForPanel(panel))}` }}</p>
            <p class="text-xs text-theme-muted mt-1">对象：{{ subjectLabels[panel.subject] || panel.subject }} · {{ panel.default_type }}</p>
          </div>
        </template>
      </div>
    </template>

    <button
      @click="goPanelManager"
      class="mx-4 mt-4 w-[calc(100%-2rem)] rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-4 flex items-center justify-between"
    >
      <div class="text-left">
        <p class="text-sm font-semibold text-theme-primary">管理统计面板</p>
        <p class="text-xs text-theme-muted mt-1">预设模板与自定义统计</p>
      </div>
      <ChevronRight class="w-4 h-4 text-teal-500" />
    </button>

    <div
      v-if="showRangeDialog"
      class="fixed inset-0 z-[70] bg-black/45 flex items-center justify-center p-4"
      @click.self="showRangeDialog = false"
    >
      <div class="w-full max-w-md bg-white dark:bg-slate-800 rounded-3xl shadow-xl overflow-hidden">
        <div class="px-5 py-4 border-b border-gray-100 dark:border-slate-700">
          <h3 class="text-2xl font-semibold text-theme-primary">日期范围</h3>
        </div>
        <div class="max-h-[70vh] overflow-y-auto">
          <button
            v-for="option in rangeOptions"
            :key="option.key"
            @click="selectRange(option.key)"
            class="w-full text-left px-5 py-4 border-b border-gray-100 dark:border-slate-700/60 last:border-b-0 flex items-center justify-between hover:bg-gray-50 dark:hover:bg-slate-700/40"
          >
            <span class="text-xl text-theme-primary">{{ option.label }}</span>
            <span v-if="rangePreset === option.key" class="text-xs font-medium text-teal-500">当前</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
