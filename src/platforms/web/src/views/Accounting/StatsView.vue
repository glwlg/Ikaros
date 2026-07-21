<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch, type ComponentPublicInstance } from 'vue'
import { formatAccountingMoney } from '@/utils/accountingFormat'
import { useRouter } from 'vue-router'
import { useAccountingStore } from '@/stores/accounting'
import {
    getCategorySummaryByRange,
    getRangeSummary,
    type CategorySummaryItem,
    type PeriodSummaryItem,
} from '@/api/accounting'
import { ChevronDown, ChevronRight, GripVertical, Loader2 } from 'lucide-vue-next'
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
    reorderStatsPanels,
    type StatsPanelConfig,
} from '@/utils/accountingLocal'
import QuickAddFab from '@/components/accounting/QuickAddFab.vue'
import PullRefreshIndicator from '@/components/accounting/PullRefreshIndicator.vue'
import AccountingErrorState from '@/components/accounting/AccountingErrorState.vue'
import { usePullToRefresh } from '@/composables/usePullToRefresh'
import {
    accountingErrorMessage,
    accountingToastError,
} from '@/utils/accountingToast'
import { buildRecordListQuery, periodBounds } from '@/utils/accountingNavigation'

type StatType = '支出' | '收入'

const store = useAccountingStore()
const router = useRouter()
const now = new Date()

const statType = ref<StatType>('支出')
const rangePreset = ref<RangePreset>('last_12_months')
const customRange = ref(createDefaultCustomRangeState(now))
const showRangeDialog = ref(false)
const statsPanels = ref<StatsPanelConfig[]>([])
const pageRef = ref<HTMLElement | null>(null)

const timeWindow = computed(() => getRangeWindow(rangePreset.value, customRange.value, now))
const timeLabel = computed(() => timeWindow.value.label)
const isCustomRange = computed(() => isCustomPreset(rangePreset.value))

const enabledPanels = computed(() => {
    return statsPanels.value
        .filter(panel => panel.enabled)
        .sort((a, b) => a.sort_order - b.sort_order)
})

const draggingPanelId = ref<string | null>(null)
const dragOverPanelId = ref<string | null>(null)
const reordering = ref(false)

const onPanelDragStart = (panelId: string, event: DragEvent) => {
    draggingPanelId.value = panelId
    if (event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move'
        event.dataTransfer.setData('text/plain', panelId)
    }
}

const onPanelDragOver = (panelId: string, event: DragEvent) => {
    event.preventDefault()
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'move'
    dragOverPanelId.value = panelId
}

const onPanelDragEnd = () => {
    draggingPanelId.value = null
    dragOverPanelId.value = null
}

const onPanelDrop = async (targetId: string, event: DragEvent) => {
    event.preventDefault()
    const sourceId = draggingPanelId.value || event.dataTransfer?.getData('text/plain')
    dragOverPanelId.value = null
    draggingPanelId.value = null
    if (!sourceId || sourceId === targetId || reordering.value) return

    const ids = enabledPanels.value.map(p => p.id)
    const from = ids.indexOf(sourceId)
    const to = ids.indexOf(targetId)
    if (from < 0 || to < 0) return
    ids.splice(from, 1)
    ids.splice(to, 0, sourceId)

    // Keep disabled panels after enabled in relative order
    const disabledIds = statsPanels.value
        .filter(p => !p.enabled)
        .sort((a, b) => a.sort_order - b.sort_order)
        .map(p => p.id)
    const fullOrder = [...ids, ...disabledIds]

    reordering.value = true
    try {
        statsPanels.value = await reorderStatsPanels(store.currentBookId, fullOrder)
        await nextTick()
        await renderChartsSafely()
        await loadPanelPreviews()
    } finally {
        reordering.value = false
    }
}

const movePanel = async (panelId: string, direction: -1 | 1) => {
    const ids = enabledPanels.value.map(p => p.id)
    const idx = ids.indexOf(panelId)
    const next = idx + direction
    if (idx < 0 || next < 0 || next >= ids.length || reordering.value) return
    ;[ids[idx], ids[next]] = [ids[next]!, ids[idx]!]
    const disabledIds = statsPanels.value
        .filter(p => !p.enabled)
        .sort((a, b) => a.sort_order - b.sort_order)
        .map(p => p.id)
    reordering.value = true
    try {
        statsPanels.value = await reorderStatsPanels(store.currentBookId, [...ids, ...disabledIds])
        await nextTick()
        await renderChartsSafely()
        await loadPanelPreviews()
    } finally {
        reordering.value = false
    }
}

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
const loadError = ref('')
const currentGranularity = ref<Granularity>('day')
const panelPreviewMap = ref<Record<string, {
    value: number
    count: number
    label: string
    granularity: Granularity
    loading: boolean
}>>({})

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
let previewLoadVersion = 0


const totalCategory = () => categoryData.value.reduce((sum, item) => sum + item.amount, 0)

const insightLine = computed(() => {
    const total = totalCategory()
    const top = [...categoryData.value].sort((a, b) => b.amount - a.amount)[0]
    const days = Math.max(
        1,
        Math.round((timeWindow.value.end.getTime() - timeWindow.value.start.getTime()) / 86400000),
    )
    const daily = total / days
    const parts: string[] = []
    if (top && total > 0) {
        const pct = Math.round((top.amount / total) * 100)
        parts.push(`最大分类「${top.category}」占 ${pct}%`)
    }
    parts.push(`日均${statType.value} ${formatAccountingMoney(daily)}`)
    return parts.join(' · ')
})

const formatPeriodLabel = (period: string) => {
    if (currentGranularity.value === 'day') return period.slice(5)
    if (currentGranularity.value === 'week') return period.replace(/^\d{4}-/, '')
    if (currentGranularity.value === 'month') return period.replace('-', '/')
    return period
}

const resolveGranularityForSubject = (
    subject: StatsPanelConfig['subject'],
    fallback: Granularity,
): Granularity => {
    if (subject === 'year') return 'year'
    if (subject === 'quarter') return 'quarter'
    if (subject === 'month') return 'month'
    if (subject === 'week') return 'week'
    if (subject === 'day') return 'day'
    return fallback
}

const panelWindowFor = (panel: StatsPanelConfig) => {
    return getRangeWindow(panel.default_range, createDefaultCustomRangeState(now), now)
}

const panelPreviewValue = (panelId: string) => {
    return panelPreviewMap.value[panelId]?.value ?? 0
}

const panelPreviewCount = (panelId: string) => {
    return panelPreviewMap.value[panelId]?.count ?? 0
}

const panelPreviewLabel = (panelId: string) => {
    return panelPreviewMap.value[panelId]?.label ?? ''
}

const panelPreviewLoading = (panelId: string) => {
    return panelPreviewMap.value[panelId]?.loading ?? false
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

const indigoColors = [
    '#14b8a6', '#06b6d4', '#0ea5e9', '#6366f1', '#8b5cf6',
    '#d946ef', '#f43f5e', '#f97316', '#eab308', '#22c55e',
]

const canInitChart = (el: HTMLElement | null) => {
    return Boolean(el && el.clientWidth > 0 && el.clientHeight > 0)
}

const setPieRef = (el: Element | ComponentPublicInstance | null) => {
    if (el && '$el' in el) {
        pieRef.value = el.$el as HTMLElement
        return
    }
    pieRef.value = el as HTMLElement | null
}

const setBarRef = (el: Element | ComponentPublicInstance | null) => {
    if (el && '$el' in el) {
        barRef.value = el.$el as HTMLElement
        return
    }
    barRef.value = el as HTMLElement | null
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
        itemStyle: { color: indigoColors[index % indigoColors.length] },
    }))

    pieChart.setOption({
        tooltip: {
            trigger: 'item',
            formatter: (params: any) => `${params.name}: ${formatAccountingMoney(Number(params.value) || 0)} (${params.percent}%)`,
        },
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
                text: formatAccountingMoney(totalCategory()),
                fill: '#111827',
                fontSize: 16,
                fontWeight: 'bold',
            },
        }],
    })
    pieChart.off('click')
    pieChart.on('click', (params: any) => {
        const name = typeof params?.name === 'string' ? params.name : ''
        if (!name || name === '暂无') return
        const query = buildRecordListQuery({
            type: statType.value,
            category: name,
            start: timeWindow.value.start,
            end: timeWindow.value.end,
            label: `${timeWindow.value.label} · ${statType.value} · ${name}`,
        })
        router.push({ name: 'RecordList', query })
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
    barChart.off('click')
    barChart.on('click', (params: any) => {
        const dataIndex = typeof params?.dataIndex === 'number' ? params.dataIndex : -1
        const row = dataIndex >= 0 ? trendData.value[dataIndex] : null
        if (row?.period) {
            const bounds = periodBounds(row.period, currentGranularity.value)
            if (bounds) {
                const query = buildRecordListQuery({
                    type: statType.value,
                    start: bounds.start,
                    end: bounds.end,
                    label: `${row.period} · ${statType.value}`,
                })
                router.push({ name: 'RecordList', query })
                return
            }
        }
        const panel = enabledPanels.value.find(p => p.id === primaryTrendPanelId.value)
        if (panel) {
            openPanelDetail(panel)
        }
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
    loadError.value = ''

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
        categoryData.value = []
        trendData.value = []
        loadError.value = accountingErrorMessage(error, '统计数据加载失败')
        accountingToastError(loadError.value)
    } finally {
        if (current === loadVersion) {
            loading.value = false
        }
    }

    if (current !== loadVersion) return
    await renderChartsSafely()
}

const loadPanelPreviews = async () => {
    if (!store.currentBookId) return

    const targets = enabledPanels.value.filter(panel =>
        panel.id !== primaryCategoryPanelId.value &&
        panel.id !== primaryTrendPanelId.value &&
        panel.id !== primaryTeamPanelId.value
    )

    const current = ++previewLoadVersion
    const nextMap: Record<string, {
        value: number
        count: number
        label: string
        granularity: Granularity
        loading: boolean
    }> = {}

    for (const panel of targets) {
        nextMap[panel.id] = {
            value: 0,
            count: 0,
            label: panelWindowFor(panel).label,
            granularity: panelWindowFor(panel).granularity,
            loading: true,
        }
    }
    panelPreviewMap.value = nextMap

    const results = await Promise.all(
        targets.map(async (panel) => {
            try {
                const panelWindow = panelWindowFor(panel)
                const granularity = resolveGranularityForSubject(panel.subject, panelWindow.granularity)
                const res = await getRangeSummary(
                    store.currentBookId!,
                    toIsoLocal(panelWindow.start),
                    toIsoLocal(panelWindow.end),
                    granularity,
                    panel.default_category || '',
                )

                const amounts = res.data.map(item => panel.default_type === '支出' ? item.expense : item.income)
                const counts = res.data.map(item => panel.default_type === '支出' ? (item.expense_count || 0) : (item.income_count || 0))

                let value = 0
                if (panel.metric === 'count') {
                    value = counts.reduce((sum, n) => sum + n, 0)
                } else if (amounts.length > 0) {
                    if (panel.metric === 'sum') value = amounts.reduce((sum, n) => sum + n, 0)
                    if (panel.metric === 'avg') value = amounts.reduce((sum, n) => sum + n, 0) / amounts.length
                    if (panel.metric === 'max') value = Math.max(...amounts)
                    if (panel.metric === 'min') value = Math.min(...amounts)
                }

                return {
                    panelId: panel.id,
                    value,
                    count: counts.reduce((sum, n) => sum + n, 0),
                    label: panelWindow.label,
                    granularity,
                }
            } catch (error) {
                console.error('panel preview load failed', panel.id, error)
                const panelWindow = panelWindowFor(panel)
                return {
                    panelId: panel.id,
                    value: 0,
                    count: 0,
                    label: panelWindow.label,
                    granularity: resolveGranularityForSubject(panel.subject, panelWindow.granularity),
                }
            }
        })
    )

    if (current !== previewLoadVersion) return

    const finalMap: Record<string, {
        value: number
        count: number
        label: string
        granularity: Granularity
        loading: boolean
    }> = {}
    for (const result of results) {
        finalMap[result.panelId] = {
            value: result.value,
            count: result.count,
            label: result.label,
            granularity: result.granularity,
            loading: false,
        }
    }
    panelPreviewMap.value = finalMap
}

const reloadPanels = async () => {
    statsPanels.value = await loadStatsPanels(store.currentBookId)
}

const selectRange = (nextPreset: RangePreset) => {
    rangePreset.value = nextPreset
    showRangeDialog.value = false
}

const makeDetailQueryForPanel = (panel: StatsPanelConfig) => {
    const isPrimary = panel.id === primaryCategoryPanelId.value || panel.id === primaryTrendPanelId.value
    const window = isPrimary ? timeWindow.value : panelWindowFor(panel)
    const type = isPrimary ? statType.value : panel.default_type
    const granularity = resolveGranularityForSubject(panel.subject, window.granularity)

    return {
        start: toIsoLocal(window.start),
        end: toIsoLocal(window.end),
        label: window.label,
        granularity,
        type,
        panel_id: panel.id,
        category: panel.default_category,
    }
}

const openPanelDetail = (panel: StatsPanelConfig) => {
    const query = makeDetailQueryForPanel(panel)
    if (panel.kind === 'category' || panel.subject === 'category') {
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
        await reloadPanels()
        await loadData()
        await loadPanelPreviews()
    },
})

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
    async () => {
        await reloadPanels()
        await loadPanelPreviews()
    }
)

watch(enabledPanels, async () => {
    await loadPanelPreviews()
    await renderChartsSafely()
})

onMounted(async () => {
    if (!store.currentBookId) await store.fetchBooks()
    await reloadPanels()
    await loadData()
    await loadPanelPreviews()

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
  <div
    ref="pageRef"
    class="accounting-page-pad"
    @touchstart="handleTouchStart"
    @touchmove="handleTouchMove"
    @touchend="handleTouchEnd"
    @touchcancel="handleTouchEnd"
  >
    <PullRefreshIndicator :distance="pullDistance" :hint="pullHint" :refreshing="refreshing" />

    <AccountingErrorState
      v-if="loadError && !loading"
      class="mx-4"
      title="统计加载失败"
      :description="loadError"
      @retry="loadData"
    />

    <div class="px-4 py-2">
      <button
        @click="showRangeDialog = true"
        class="w-full rounded-2xl bg-theme-elevated border border-theme-secondary shadow-sm px-4 py-3 flex items-center justify-between"
      >
        <div class="text-left">
          <p class="text-xs text-theme-muted">日期范围</p>
          <p class="text-sm font-semibold text-theme-primary mt-0.5">{{ timeLabel }}</p>
        </div>
        <ChevronDown class="w-4 h-4 text-theme-muted" />
      </button>
      <p v-if="!loading && categoryData.length" class="mt-2 text-xs text-theme-muted px-1">
        洞察：{{ insightLine }}
      </p>
    </div>

    <div v-if="isCustomRange" class="mx-4 mt-1 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-4 space-y-3">
      <template v-if="rangePreset === 'year_range'">
        <div class="grid grid-cols-2 gap-2">
          <select v-model.number="customRange.yearStart" class="accounting-field">
            <option v-for="y in 11" :key="`ys-${y}`" :value="now.getFullYear() - 9 + y">{{ now.getFullYear() - 9 + y }}年</option>
          </select>
          <select v-model.number="customRange.yearEnd" class="accounting-field">
            <option v-for="y in 11" :key="`ye-${y}`" :value="now.getFullYear() - 9 + y">{{ now.getFullYear() - 9 + y }}年</option>
          </select>
        </div>
      </template>

      <template v-else-if="rangePreset === 'quarter_range'">
        <div class="grid grid-cols-2 gap-2">
          <input v-model.number="customRange.quarterStartYear" type="number" class="accounting-field" />
          <select v-model.number="customRange.quarterStartQuarter" class="accounting-field">
            <option v-for="q in [1,2,3,4]" :key="`qs-${q}`" :value="q">Q{{ q }}</option>
          </select>
          <input v-model.number="customRange.quarterEndYear" type="number" class="accounting-field" />
          <select v-model.number="customRange.quarterEndQuarter" class="accounting-field">
            <option v-for="q in [1,2,3,4]" :key="`qe-${q}`" :value="q">Q{{ q }}</option>
          </select>
        </div>
      </template>

      <template v-else-if="rangePreset === 'month_range'">
        <div class="grid grid-cols-2 gap-2">
          <input v-model="customRange.monthStart" type="month" class="accounting-field" />
          <input v-model="customRange.monthEnd" type="month" class="accounting-field" />
        </div>
      </template>

      <template v-else-if="rangePreset === 'week_range'">
        <div class="grid grid-cols-2 gap-2">
          <input v-model="customRange.weekStart" type="week" class="accounting-field" />
          <input v-model="customRange.weekEnd" type="week" class="accounting-field" />
        </div>
      </template>

      <template v-else-if="rangePreset === 'day_range'">
        <div class="grid grid-cols-2 gap-2">
          <input v-model="customRange.dayStart" type="date" class="accounting-field" />
          <input v-model="customRange.dayEnd" type="date" class="accounting-field" />
        </div>
      </template>
    </div>

    <p class="mx-4 mt-1 text-[11px] text-theme-muted">长按左侧把手拖动，可调整面板顺序</p>

    <template v-for="(panel, index) in enabledPanels" :key="panel.id">
      <div
        :class="[
          'mx-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border p-4 transition',
          index === 0 ? 'mt-2' : 'mt-3',
          dragOverPanelId === panel.id ? 'border-accounting-brand ring-2 ring-[var(--color-accounting-brand)]/20' : 'border-gray-100 dark:border-slate-700',
          draggingPanelId === panel.id ? 'opacity-60' : '',
        ]"
        draggable="false"
        @dragover="onPanelDragOver(panel.id, $event)"
        @drop="onPanelDrop(panel.id, $event)"
      >
        <div class="flex items-center justify-between mb-1 gap-2">
          <div class="flex items-center gap-1 min-w-0 flex-1">
            <button
              type="button"
              class="shrink-0 p-1.5 -ml-1 rounded-lg text-theme-muted active:bg-theme-secondary cursor-grab active:cursor-grabbing touch-none"
              aria-label="拖动排序"
              draggable="true"
              @dragstart="onPanelDragStart(panel.id, $event)"
              @dragend="onPanelDragEnd"
              @click.stop
            >
              <GripVertical class="w-5 h-5" />
            </button>
            <h3 class="font-bold text-theme-primary truncate">{{ panel.name }}</h3>
          </div>
          <div class="flex items-center gap-0.5 shrink-0">
            <button
              type="button"
              class="px-2 h-8 rounded-lg text-xs text-theme-muted active:bg-theme-secondary disabled:opacity-30"
              :disabled="index === 0 || reordering"
              aria-label="上移"
              @click="movePanel(panel.id, -1)"
            >↑</button>
            <button
              type="button"
              class="px-2 h-8 rounded-lg text-xs text-theme-muted active:bg-theme-secondary disabled:opacity-30"
              :disabled="index >= enabledPanels.length - 1 || reordering"
              aria-label="下移"
              @click="movePanel(panel.id, 1)"
            >↓</button>
            <button type="button" @click="openPanelDetail(panel)" class="p-1 rounded hover:bg-gray-100 dark:hover:bg-slate-700">
              <ChevronRight class="w-4 h-4 text-accounting-brand" />
            </button>
          </div>
        </div>

        <template v-if="panel.id === primaryCategoryPanelId && panel.kind === 'category'">
          <p class="text-xs text-theme-muted mb-3">
            {{ formatAccountingMoney(totalCategory()) }} · {{ timeLabel }} · {{ statType }}
          </p>

          <div class="flex gap-2 mb-3">
            <button
              @click="statType = '支出'"
              :class="['px-3 py-1 rounded-full text-xs font-medium transition', statType === '支出' ? 'bg-accounting-brand text-white' : 'bg-theme-secondary text-theme-secondary']"
            >支出</button>
            <button
              @click="statType = '收入'"
              :class="['px-3 py-1 rounded-full text-xs font-medium transition', statType === '收入' ? 'bg-accounting-brand text-white' : 'bg-theme-secondary text-theme-secondary']"
            >收入</button>
          </div>

          <div class="relative">
            <div :ref="setPieRef" class="w-full h-[220px]"></div>
            <div v-if="loading" class="absolute inset-0 flex items-center justify-center bg-white/30 dark:bg-slate-800/30 rounded-xl">
              <Loader2 class="w-5 h-5 animate-spin text-indigo-400" />
            </div>
          </div>
        </template>

        <template v-else-if="panel.id === primaryTrendPanelId && panel.kind === 'trend'">
          <p class="text-xs text-theme-muted mb-3">{{ timeLabel }} · 按{{ granularityLabel }} · {{ statType }}</p>

          <div class="relative">
            <div :ref="setBarRef" class="w-full h-[220px]"></div>
            <div v-if="loading" class="absolute inset-0 flex items-center justify-center bg-white/30 dark:bg-slate-800/30 rounded-xl">
              <Loader2 class="w-5 h-5 animate-spin text-indigo-400" />
            </div>
          </div>
        </template>

        <template v-else-if="panel.id === primaryTeamPanelId && panel.kind === 'team'">
          <p class="text-xs text-theme-muted mb-3">{{ timeLabel }} · 个人模式</p>
          <div class="w-full rounded-xl border border-dashed border-theme-primary bg-theme-secondary/40 px-4 py-6 text-center">
            <p class="text-sm font-medium text-theme-primary">多人协作未启用</p>
            <p class="text-xs text-theme-muted mt-1">当前账本为个人模式，暂无成员维度数据</p>
          </div>
        </template>

        <template v-else>
          <p class="text-xs text-theme-muted mb-3">{{ panel.description || '自定义统计面板' }}</p>
          <div class="rounded-xl bg-slate-50 dark:bg-slate-900 border border-slate-100 dark:border-slate-700 p-3">
            <p class="text-xs text-theme-muted">{{ metricLabels[panel.metric] || '统计值' }}</p>
            <p class="text-xl font-semibold text-theme-primary mt-1">
              <Loader2 v-if="panelPreviewLoading(panel.id)" class="w-4 h-4 animate-spin" />
              <template v-else>
                {{ panel.metric === 'count' ? panelPreviewValue(panel.id) : formatAccountingMoney(panelPreviewValue(panel.id)) }}
              </template>
            </p>
            <p class="text-xs text-theme-muted mt-1">
              对象：{{ subjectLabels[panel.subject] || panel.subject }} · {{ panel.default_type }}
              <template v-if="panel.metric === 'count'"> · {{ panelPreviewCount(panel.id) }}笔</template>
              <template v-if="panelPreviewLabel(panel.id)"> · {{ panelPreviewLabel(panel.id) }}</template>
            </p>
          </div>
        </template>
      </div>
    </template>

    <button
      @click="goPanelManager"
      class="mx-4 mt-4 w-[calc(100%-2rem)] rounded-2xl bg-theme-elevated shadow-sm border border-theme-secondary p-4 flex items-center justify-between"
    >
      <div class="text-left">
        <p class="text-sm font-semibold text-theme-primary">管理统计面板</p>
        <p class="text-xs text-theme-muted mt-1">预设模板与自定义统计</p>
      </div>
      <ChevronRight class="w-4 h-4 text-accounting-brand" />
    </button>

    <QuickAddFab :book-id="store.currentBookId" @saved="() => { loadData(); loadPanelPreviews() }" />

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
            <span v-if="rangePreset === option.key" class="text-xs font-medium text-indigo-500">当前</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
