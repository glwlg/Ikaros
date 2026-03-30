<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAccountingStore } from '@/stores/accounting'
import { getRangeSummary, type PeriodSummaryItem } from '@/api/accounting'
import { ChevronLeft, Loader2, TrendingUp, TrendingDown } from 'lucide-vue-next'
import * as echarts from 'echarts'
import {
    createDefaultCustomRangeState,
    getRangeWindow,
    rangeOptions,
    toIsoLocal,
    type RangePreset,
} from './statsRange'

type StatType = '支出' | '收入' | '结余' | '转账'

const router = useRouter()
const route = useRoute()
const store = useAccountingStore()
const now = new Date()

const loading = ref(false)
const statType = ref<StatType>('支出')
const rangePreset = ref<RangePreset>('this_month')
const customRange = ref(createDefaultCustomRangeState(now))

const currentData = ref<PeriodSummaryItem[]>([])
const previousData = ref<PeriodSummaryItem[]>([])

const chartRef = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
let resizeObserver: ResizeObserver | null = null
let delayedRenderTimer: ReturnType<typeof setTimeout> | null = null
let loadVersion = 0

const detailRangeOptions = rangeOptions.filter(item =>
    !['year_range', 'quarter_range', 'month_range', 'week_range'].includes(item.key)
)

const timeWindow = computed(() => getRangeWindow(rangePreset.value, customRange.value, now))
const isCustomRange = computed(() => ['year_range', 'quarter_range', 'month_range', 'week_range', 'day_range'].includes(rangePreset.value))

const formatMoney = (n: number) =>
    new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(n)

const formatPercent = (n: number) => {
    if (!Number.isFinite(n)) return '0%'
    return `${n >= 0 ? '+' : ''}${(n * 100).toFixed(1)}%`
}

// Calculate totals for current period
const currentTotal = computed(() => {
    return currentData.value.reduce((sum, item) => {
        if (statType.value === '支出') return sum + item.expense
        if (statType.value === '收入') return sum + item.income
        if (statType.value === '结余') return sum + (item.income - item.expense)
        return sum
    }, 0)
})

// Calculate totals for previous period
const previousTotal = computed(() => {
    return previousData.value.reduce((sum, item) => {
        if (statType.value === '支出') return sum + item.expense
        if (statType.value === '收入') return sum + item.income
        if (statType.value === '结余') return sum + (item.income - item.expense)
        return sum
    }, 0)
})

// Year-over-year comparison
const yoyChange = computed(() => {
    if (previousTotal.value === 0) return null
    return (currentTotal.value - previousTotal.value) / previousTotal.value
})

const granularityLabel = computed(() => {
    const g = timeWindow.value.granularity
    if (g === 'day') return '天'
    if (g === 'week') return '周'
    if (g === 'month') return '月'
    if (g === 'quarter') return '季'
    return '年'
})

const formatPeriodLabel = (period: string) => {
    const g = timeWindow.value.granularity
    if (g === 'day') return period.slice(5)
    if (g === 'week') return period.replace(/^\d{4}-/, '')
    if (g === 'month') return period.replace('-', '/')
    return period
}

const getPreviousWindow = () => {
    const current = timeWindow.value
    const spanMs = current.end.getTime() - current.start.getTime()
    return {
        start: new Date(current.start.getTime() - spanMs),
        end: current.start,
        granularity: current.granularity,
    }
}

const renderChart = () => {
    if (!chartRef.value || chartRef.value.clientWidth <= 0 || chartRef.value.clientHeight <= 0) return false
    if (!chart) chart = echarts.init(chartRef.value)

    const xAxisData = currentData.value.map(item => formatPeriodLabel(item.period))
    const seriesData = currentData.value.map(item => {
        if (statType.value === '支出') return item.expense
        if (statType.value === '收入') return item.income
        if (statType.value === '结余') return item.income - item.expense
        return 0
    })

    const barColor = statType.value === '支出' ? '#f87171' :
                     statType.value === '收入' ? '#14b8a6' :
                     statType.value === '结余' ? '#6366f1' : '#8b5cf6'

    chart.setOption({
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
                color: barColor,
                borderRadius: [4, 4, 0, 0],
            },
        }],
    })

    chart.resize()
    return true
}

const renderChartSafely = async () => {
    await nextTick()
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))

    if (renderChart()) return

    if (delayedRenderTimer) clearTimeout(delayedRenderTimer)
    delayedRenderTimer = setTimeout(() => {
        renderChart()
    }, 120)
}

const loadData = async () => {
    if (!store.currentBookId) return
    const current = ++loadVersion
    loading.value = true

    try {
        const window = timeWindow.value

        // Load current period data
        const currentRes = await getRangeSummary(
            store.currentBookId,
            toIsoLocal(window.start),
            toIsoLocal(window.end),
            window.granularity,
        )

        if (current !== loadVersion) return
        currentData.value = currentRes.data

        // Load previous period data for comparison
        const prevWindow = getPreviousWindow()
        const prevRes = await getRangeSummary(
            store.currentBookId,
            toIsoLocal(prevWindow.start),
            toIsoLocal(prevWindow.end),
            prevWindow.granularity,
        )

        if (current !== loadVersion) return
        previousData.value = prevRes.data
    } catch (error) {
        if (current !== loadVersion) return
        console.error('stats detail load failed', error)
        currentData.value = []
        previousData.value = []
    } finally {
        if (current === loadVersion) loading.value = false
    }

    if (current !== loadVersion) return
    await renderChartSafely()
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

const initializeFromQuery = () => {
    const queryType = route.query.type
    if (queryType === '支出' || queryType === '收入' || queryType === '结余' || queryType === '转账') {
        statType.value = queryType
    }

    const queryRange = route.query.range
    if (queryRange && typeof queryRange === 'string') {
        rangePreset.value = queryRange as RangePreset
    }

    const queryYear = route.query.year
    const queryMonth = route.query.month
    if (queryYear && queryMonth) {
        const y = Number(queryYear)
        const m = Number(queryMonth)
        if (Number.isFinite(y) && Number.isFinite(m)) {
            rangePreset.value = 'this_month'
            // Override to show specific month
            customRange.value.dayStart = `${y}-${String(m).padStart(2, '0')}-01`
            const lastDay = new Date(y, m, 0).getDate()
            customRange.value.dayEnd = `${y}-${String(m).padStart(2, '0')}-${String(lastDay).padStart(2, '0')}`
        }
    }
}

onMounted(async () => {
    if (!store.currentBookId) await store.fetchBooks()
    initializeFromQuery()
    await loadData()

    if (typeof ResizeObserver !== 'undefined' && chartRef.value) {
        resizeObserver = new ResizeObserver(() => chart?.resize())
        resizeObserver.observe(chartRef.value)
    }
    window.addEventListener('resize', renderChartSafely)
})

onBeforeUnmount(() => {
    resizeObserver?.disconnect()
    resizeObserver = null

    if (delayedRenderTimer) {
        clearTimeout(delayedRenderTimer)
        delayedRenderTimer = null
    }

    window.removeEventListener('resize', renderChartSafely)
    chart?.dispose()
    chart = null
})
</script>

<template>
  <div class="min-h-screen flex flex-col bg-slate-50 dark:bg-slate-900 pb-20">
    <header class="bg-white dark:bg-slate-800 shadow-sm sticky top-0 z-10 safe-top">
      <div class="flex items-center justify-between h-14 px-4">
        <button @click="router.back()" class="p-2 -ml-2 text-slate-600 dark:text-slate-300">
          <ChevronLeft class="w-6 h-6" />
        </button>
        <h1 class="text-lg font-bold text-slate-800 dark:text-white">收支统计</h1>
        <div class="w-8"></div>
      </div>
    </header>

    <main class="flex-1 overflow-y-auto p-4">
      <!-- Filters -->
      <div class="rounded-2xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 shadow-sm p-4 space-y-3">
        <!-- Time Range Selector -->
        <div>
          <label class="text-xs text-gray-500 mb-1 block">时间范围</label>
          <select v-model="rangePreset" class="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm">
            <option v-for="item in detailRangeOptions" :key="item.key" :value="item.key">{{ item.label }}</option>
          </select>
        </div>

        <!-- Custom Range Inputs -->
        <div v-if="isCustomRange && rangePreset === 'day_range'" class="grid grid-cols-2 gap-2">
          <input v-model="customRange.dayStart" type="date" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
          <input v-model="customRange.dayEnd" type="date" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
        </div>

        <!-- Type Tabs -->
        <div>
          <label class="text-xs text-gray-500 mb-1 block">统计类型</label>
          <div class="flex gap-2">
            <button
              v-for="type in ['支出', '收入', '结余', '转账'] as const"
              :key="type"
              @click="statType = type"
              :class="[
                'flex-1 py-2 rounded-xl text-xs font-medium transition',
                statType === type
                  ? 'bg-indigo-500 text-white'
                  : 'bg-gray-100 dark:bg-slate-700 text-theme-secondary'
              ]"
            >
              {{ type }}
            </button>
          </div>
        </div>
      </div>

      <!-- Summary Card -->
      <div class="mt-4 rounded-2xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 shadow-sm p-4">
        <div class="flex items-end justify-between">
          <div>
            <p class="text-xs text-theme-muted">{{ timeWindow.label }} · {{ statType }}</p>
            <p class="text-3xl font-bold mt-1" :class="[
              statType === '支出' ? 'text-rose-500' :
              statType === '收入' ? 'text-teal-500' :
              statType === '结余' ? 'text-indigo-500' : 'text-purple-500'
            ]">
              ¥{{ formatMoney(currentTotal) }}
            </p>
            <!-- YoY Comparison -->
            <div v-if="yoyChange !== null" class="mt-2 flex items-center gap-1">
              <template v-if="yoyChange !== 0">
                <TrendingUp v-if="yoyChange > 0" class="w-3 h-3" :class="statType === '支出' ? 'text-rose-500' : 'text-teal-500'" />
                <TrendingDown v-else class="w-3 h-3" :class="statType === '支出' ? 'text-teal-500' : 'text-rose-500'" />
                <span class="text-xs" :class="yoyChange > 0 ? (statType === '支出' ? 'text-rose-500' : 'text-teal-500') : (statType === '支出' ? 'text-teal-500' : 'text-rose-500')">
                  同比 {{ formatPercent(yoyChange) }}
                </span>
              </template>
              <span v-else class="text-xs text-gray-400">同比持平</span>
              <span class="text-xs text-gray-400 ml-1">环比 ¥{{ formatMoney(previousTotal) }}</span>
            </div>
          </div>
        </div>

        <!-- Chart -->
        <div class="relative mt-4">
          <div ref="chartRef" class="w-full h-[220px]"></div>
          <div v-if="loading" class="absolute inset-0 bg-white/40 dark:bg-slate-800/40 flex items-center justify-center rounded-xl">
            <Loader2 class="w-5 h-5 animate-spin text-indigo-400" />
          </div>
        </div>
      </div>

      <!-- Detail List -->
      <div class="mt-4 rounded-2xl bg-white dark:bg-slate-800 border border-slate-100 dark:border-slate-700 shadow-sm p-4">
        <h3 class="font-semibold text-theme-primary mb-3">按{{ granularityLabel }}明细</h3>
        <ul v-if="currentData.length > 0" class="space-y-2">
          <li v-for="item in currentData" :key="item.period" class="flex items-center justify-between py-2 border-b border-gray-50 dark:border-slate-700/50 last:border-b-0">
            <span class="text-sm text-theme-secondary">{{ formatPeriodLabel(item.period) }}</span>
            <div class="text-right">
              <p class="text-sm font-medium text-theme-primary">
                ¥{{ formatMoney(statType === '支出' ? item.expense : statType === '收入' ? item.income : item.income - item.expense) }}
              </p>
              <p class="text-xs text-theme-muted">
                {{ item.expense_count || 0 }}笔支出 · {{ item.income_count || 0 }}笔收入
              </p>
            </div>
          </li>
        </ul>
        <p v-else-if="!loading" class="text-center text-theme-muted text-sm py-8">暂无数据</p>
      </div>
    </main>
  </div>
</template>