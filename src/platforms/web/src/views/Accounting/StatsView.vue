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

type StatType = '支出' | '收入'
type Granularity = 'day' | 'week' | 'month' | 'quarter' | 'year'
type RangePreset =
    | 'all_time'
    | 'this_year'
    | 'this_quarter'
    | 'this_month'
    | 'this_week'
    | 'last_12_months'
    | 'last_30_days'
    | 'last_6_weeks'
    | 'year_range'
    | 'quarter_range'
    | 'month_range'
    | 'week_range'
    | 'day_range'

interface RangeWindow {
    start: Date
    end: Date
    granularity: Granularity
    label: string
}

const store = useAccountingStore()
const router = useRouter()
const now = new Date()

const statType = ref<StatType>('支出')
const rangePreset = ref<RangePreset>('this_month')
const showRangeDialog = ref(false)

const yearNow = now.getFullYear()
const quarterNow = Math.floor(now.getMonth() / 3) + 1

const customYearStart = ref(yearNow - 1)
const customYearEnd = ref(yearNow)

const customQuarterStartYear = ref(yearNow)
const customQuarterStartQuarter = ref(1)
const customQuarterEndYear = ref(yearNow)
const customQuarterEndQuarter = ref(quarterNow)

const pad2 = (n: number) => String(n).padStart(2, '0')

const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate())
const addDays = (d: Date, days: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + days)
const startOfWeek = (d: Date) => {
    const day = d.getDay() === 0 ? 7 : d.getDay()
    return addDays(startOfDay(d), -(day - 1))
}
const startOfMonth = (d: Date) => new Date(d.getFullYear(), d.getMonth(), 1)
const startOfQuarter = (d: Date) => new Date(d.getFullYear(), Math.floor(d.getMonth() / 3) * 3, 1)

const toDateValue = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
const toMonthValue = (d: Date) => `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`

const getIsoWeekStart = (year: number, week: number) => {
    const jan4 = new Date(year, 0, 4)
    const jan4Day = jan4.getDay() === 0 ? 7 : jan4.getDay()
    const week1Monday = addDays(jan4, -(jan4Day - 1))
    return addDays(week1Monday, (week - 1) * 7)
}

const toWeekValue = (d: Date) => {
    const target = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
    const dayNum = target.getUTCDay() || 7
    target.setUTCDate(target.getUTCDate() + 4 - dayNum)
    const yearStart = new Date(Date.UTC(target.getUTCFullYear(), 0, 1))
    const weekNo = Math.ceil((((target.getTime() - yearStart.getTime()) / 86400000) + 1) / 7)
    return `${target.getUTCFullYear()}-W${pad2(weekNo)}`
}

const parseDateValue = (value: string) => {
    const m = value.match(/^(\d{4})-(\d{2})-(\d{2})$/)
    if (!m) return startOfDay(now)
    return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
}

const parseMonthValue = (value: string) => {
    const m = value.match(/^(\d{4})-(\d{2})$/)
    if (!m) return startOfMonth(now)
    return new Date(Number(m[1]), Number(m[2]) - 1, 1)
}

const parseWeekValue = (value: string) => {
    const m = value.match(/^(\d{4})-W(\d{2})$/)
    if (!m) return startOfWeek(now)
    return getIsoWeekStart(Number(m[1]), Number(m[2]))
}

const customMonthStart = ref(toMonthValue(new Date(yearNow, Math.max(0, now.getMonth() - 2), 1)))
const customMonthEnd = ref(toMonthValue(new Date(yearNow, now.getMonth(), 1)))

const customWeekStart = ref(toWeekValue(addDays(startOfWeek(now), -35)))
const customWeekEnd = ref(toWeekValue(startOfWeek(now)))

const customDayStart = ref(toDateValue(addDays(startOfDay(now), -29)))
const customDayEnd = ref(toDateValue(startOfDay(now)))

const yearOptions = computed(() => {
    const result: number[] = []
    for (let y = yearNow - 8; y <= yearNow + 2; y++) {
        result.push(y)
    }
    return result
})

const quarterOptions = [1, 2, 3, 4]

const rangeOptions: Array<{ key: RangePreset; label: string }> = [
    { key: 'all_time', label: '全部时间' },
    { key: 'this_year', label: '本年' },
    { key: 'this_quarter', label: '本季' },
    { key: 'this_month', label: '本月' },
    { key: 'this_week', label: '本周' },
    { key: 'last_12_months', label: '近12个月' },
    { key: 'last_30_days', label: '近30天' },
    { key: 'last_6_weeks', label: '近6周' },
    { key: 'year_range', label: '年范围' },
    { key: 'quarter_range', label: '季范围' },
    { key: 'month_range', label: '月范围' },
    { key: 'week_range', label: '周范围' },
    { key: 'day_range', label: '日范围' },
]

const isCustomRange = computed(() => {
    return ['year_range', 'quarter_range', 'month_range', 'week_range', 'day_range'].includes(rangePreset.value)
})

const normalizeWindow = (a: Date, b: Date) => {
    let start = a
    let end = b
    if (start.getTime() > end.getTime()) {
        start = b
        end = a
    }
    if (start.getTime() === end.getTime()) {
        end = addDays(end, 1)
    }
    return { start, end }
}

const monthsBetween = (start: Date, end: Date) => {
    return (end.getFullYear() - start.getFullYear()) * 12 + (end.getMonth() - start.getMonth())
}

const getRangeWindow = (): RangeWindow => {
    const today = new Date()

    if (rangePreset.value === 'all_time') {
        return {
            start: new Date(1970, 0, 1),
            end: addDays(startOfDay(today), 1),
            granularity: 'year',
            label: '全部时间',
        }
    }

    if (rangePreset.value === 'this_year') {
        return {
            start: new Date(today.getFullYear(), 0, 1),
            end: new Date(today.getFullYear() + 1, 0, 1),
            granularity: 'month',
            label: `${today.getFullYear()}年`,
        }
    }

    if (rangePreset.value === 'this_quarter') {
        const start = startOfQuarter(today)
        return {
            start,
            end: new Date(start.getFullYear(), start.getMonth() + 3, 1),
            granularity: 'week',
            label: `${today.getFullYear()}年Q${Math.floor(today.getMonth() / 3) + 1}`,
        }
    }

    if (rangePreset.value === 'this_month') {
        const start = startOfMonth(today)
        return {
            start,
            end: new Date(start.getFullYear(), start.getMonth() + 1, 1),
            granularity: 'day',
            label: `${today.getFullYear()}年${today.getMonth() + 1}月`,
        }
    }

    if (rangePreset.value === 'this_week') {
        const start = startOfWeek(today)
        return {
            start,
            end: addDays(start, 7),
            granularity: 'day',
            label: '本周',
        }
    }

    if (rangePreset.value === 'last_12_months') {
        const thisMonth = startOfMonth(today)
        return {
            start: new Date(thisMonth.getFullYear(), thisMonth.getMonth() - 11, 1),
            end: new Date(thisMonth.getFullYear(), thisMonth.getMonth() + 1, 1),
            granularity: 'month',
            label: '近12个月',
        }
    }

    if (rangePreset.value === 'last_30_days') {
        return {
            start: addDays(startOfDay(today), -29),
            end: addDays(startOfDay(today), 1),
            granularity: 'day',
            label: '近30天',
        }
    }

    if (rangePreset.value === 'last_6_weeks') {
        const thisWeekStart = startOfWeek(today)
        return {
            start: addDays(thisWeekStart, -35),
            end: addDays(thisWeekStart, 7),
            granularity: 'week',
            label: '近6周',
        }
    }

    if (rangePreset.value === 'year_range') {
        const startYear = Math.min(customYearStart.value, customYearEnd.value)
        const endYear = Math.max(customYearStart.value, customYearEnd.value)
        const span = endYear - startYear + 1
        return {
            start: new Date(startYear, 0, 1),
            end: new Date(endYear + 1, 0, 1),
            granularity: span > 5 ? 'year' : 'month',
            label: `${startYear}-${endYear}年`,
        }
    }

    if (rangePreset.value === 'quarter_range') {
        const start = new Date(customQuarterStartYear.value, (customQuarterStartQuarter.value - 1) * 3, 1)
        const endBase = new Date(customQuarterEndYear.value, (customQuarterEndQuarter.value - 1) * 3, 1)
        const normalized = normalizeWindow(start, new Date(endBase.getFullYear(), endBase.getMonth() + 3, 1))
        const spanMonths = monthsBetween(normalized.start, normalized.end)
        const sQuarter = Math.floor(normalized.start.getMonth() / 3) + 1
        const eQuarter = Math.floor((normalized.end.getMonth() - 1 + 12) % 12 / 3) + 1
        const eQuarterYear = normalized.end.getMonth() === 0 ? normalized.end.getFullYear() - 1 : normalized.end.getFullYear()
        return {
            start: normalized.start,
            end: normalized.end,
            granularity: spanMonths > 24 ? 'year' : 'quarter',
            label: `${normalized.start.getFullYear()}Q${sQuarter} - ${eQuarterYear}Q${eQuarter}`,
        }
    }

    if (rangePreset.value === 'month_range') {
        const startMonth = parseMonthValue(customMonthStart.value)
        const endMonth = parseMonthValue(customMonthEnd.value)
        const normalized = normalizeWindow(startMonth, new Date(endMonth.getFullYear(), endMonth.getMonth() + 1, 1))
        const spanMonths = monthsBetween(normalized.start, normalized.end)
        return {
            start: normalized.start,
            end: normalized.end,
            granularity: spanMonths > 6 ? 'month' : 'day',
            label: `${toMonthValue(normalized.start)} 至 ${toMonthValue(addDays(normalized.end, -1))}`,
        }
    }

    if (rangePreset.value === 'week_range') {
        const startWeek = parseWeekValue(customWeekStart.value)
        const endWeek = parseWeekValue(customWeekEnd.value)
        const normalized = normalizeWindow(startWeek, addDays(endWeek, 7))
        const spanDays = Math.round((normalized.end.getTime() - normalized.start.getTime()) / 86400000)
        return {
            start: normalized.start,
            end: normalized.end,
            granularity: spanDays > 84 ? 'month' : 'week',
            label: `${toWeekValue(normalized.start)} 至 ${toWeekValue(addDays(normalized.end, -1))}`,
        }
    }

    const startDay = parseDateValue(customDayStart.value)
    const endDay = parseDateValue(customDayEnd.value)
    const normalized = normalizeWindow(startDay, addDays(endDay, 1))
    const spanDays = Math.round((normalized.end.getTime() - normalized.start.getTime()) / 86400000)
    return {
        start: normalized.start,
        end: normalized.end,
        granularity: spanDays > 180 ? 'month' : (spanDays > 45 ? 'week' : 'day'),
        label: `${toDateValue(normalized.start)} 至 ${toDateValue(addDays(normalized.end, -1))}`,
    }
}

const timeLabel = computed(() => getRangeWindow().label)

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
let loadVersion = 0

const formatMoney = (n: number) =>
    new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(n)

const totalCategory = () => categoryData.value.reduce((s, c) => s + c.amount, 0)

const toIsoLocal = (d: Date) => {
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
}

const loadData = async () => {
    if (!store.currentBookId) return

    const current = ++loadVersion
    const window = getRangeWindow()
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
    } finally {
        if (current === loadVersion) {
            loading.value = false
        }
    }

    if (current !== loadVersion) return
    await nextTick()
    renderPie()
    renderBar()
    pieChart?.resize()
    barChart?.resize()
}

const tealColors = [
    '#14b8a6', '#06b6d4', '#0ea5e9', '#6366f1', '#8b5cf6',
    '#d946ef', '#f43f5e', '#f97316', '#eab308', '#22c55e',
]

const renderPie = () => {
    if (!pieRef.value) return
    if (!pieChart) pieChart = echarts.init(pieRef.value)

    const data = categoryData.value.map((c, i) => ({
        name: c.category,
        value: c.amount,
        itemStyle: { color: tealColors[i % tealColors.length] },
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
            style: {
                text: '全部',
                fill: '#9ca3af',
                fontSize: 12,
            },
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
}

const formatPeriodLabel = (period: string) => {
    if (currentGranularity.value === 'day') return period.slice(5)
    if (currentGranularity.value === 'week') return period.replace(/^\d{4}-/, '')
    if (currentGranularity.value === 'month') return period.replace('-', '/')
    return period
}

const renderBar = () => {
    if (!barRef.value) return
    if (!barChart) barChart = echarts.init(barRef.value)

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
}

const selectRange = (value: RangePreset) => {
    rangePreset.value = value
    showRangeDialog.value = false
}

const makeDetailQuery = () => {
    const window = getRangeWindow()
    return {
        start: toIsoLocal(window.start),
        end: toIsoLocal(window.end),
        label: window.label,
        granularity: window.granularity,
        type: statType.value,
    }
}

const goCategoryDetail = () => {
    router.push({ name: 'StatsCategoryDetail', query: makeDetailQuery() })
}

const goTrendDetail = () => {
    router.push({ name: 'StatsTrendDetail', query: makeDetailQuery() })
}

const goTeamDetail = () => {
    router.push({ name: 'StatsTeamDetail', query: makeDetailQuery() })
}

watch([statType, rangePreset], () => {
    loadData()
})

watch(
    [
        customYearStart,
        customYearEnd,
        customQuarterStartYear,
        customQuarterStartQuarter,
        customQuarterEndYear,
        customQuarterEndQuarter,
        customMonthStart,
        customMonthEnd,
        customWeekStart,
        customWeekEnd,
        customDayStart,
        customDayEnd,
    ],
    () => {
        if (isCustomRange.value) {
            loadData()
        }
    }
)

const handleResize = () => {
    pieChart?.resize()
    barChart?.resize()
}

onMounted(async () => {
    if (!store.currentBookId) await store.fetchBooks()
    await loadData()
    window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
    window.removeEventListener('resize', handleResize)
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
          <select v-model.number="customYearStart" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm">
            <option v-for="y in yearOptions" :key="`ys-${y}`" :value="y">{{ y }}年</option>
          </select>
          <select v-model.number="customYearEnd" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm">
            <option v-for="y in yearOptions" :key="`ye-${y}`" :value="y">{{ y }}年</option>
          </select>
        </div>
      </template>

      <template v-else-if="rangePreset === 'quarter_range'">
        <div class="grid grid-cols-2 gap-2">
          <select v-model.number="customQuarterStartYear" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm">
            <option v-for="y in yearOptions" :key="`qsy-${y}`" :value="y">{{ y }}年</option>
          </select>
          <select v-model.number="customQuarterStartQuarter" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm">
            <option v-for="q in quarterOptions" :key="`qsq-${q}`" :value="q">Q{{ q }}</option>
          </select>
          <select v-model.number="customQuarterEndYear" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm">
            <option v-for="y in yearOptions" :key="`qey-${y}`" :value="y">{{ y }}年</option>
          </select>
          <select v-model.number="customQuarterEndQuarter" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm">
            <option v-for="q in quarterOptions" :key="`qeq-${q}`" :value="q">Q{{ q }}</option>
          </select>
        </div>
      </template>

      <template v-else-if="rangePreset === 'month_range'">
        <div class="grid grid-cols-2 gap-2">
          <input v-model="customMonthStart" type="month" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
          <input v-model="customMonthEnd" type="month" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
        </div>
      </template>

      <template v-else-if="rangePreset === 'week_range'">
        <div class="grid grid-cols-2 gap-2">
          <input v-model="customWeekStart" type="week" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
          <input v-model="customWeekEnd" type="week" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
        </div>
      </template>

      <template v-else-if="rangePreset === 'day_range'">
        <div class="grid grid-cols-2 gap-2">
          <input v-model="customDayStart" type="date" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
          <input v-model="customDayEnd" type="date" class="px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm" />
        </div>
      </template>
    </div>

    <div v-if="loading" class="p-12 text-center text-theme-muted">
      <Loader2 class="w-5 h-5 animate-spin mx-auto mb-2 text-teal-400" />
    </div>

    <template v-else>
      <div class="mx-4 mt-2 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-4">
        <div class="flex items-center justify-between mb-1">
          <h3 class="font-bold text-theme-primary">分类统计</h3>
          <button @click="goCategoryDetail" class="p-1 rounded hover:bg-gray-100 dark:hover:bg-slate-700">
            <ChevronRight class="w-4 h-4 text-teal-500" />
          </button>
        </div>
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

        <div ref="pieRef" class="w-full h-[220px]"></div>
      </div>

      <div class="mx-4 mt-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-4">
        <div class="flex items-center justify-between mb-1">
          <h3 class="font-bold text-theme-primary">年度统计</h3>
          <button @click="goTrendDetail" class="p-1 rounded hover:bg-gray-100 dark:hover:bg-slate-700">
            <ChevronRight class="w-4 h-4 text-teal-500" />
          </button>
        </div>
        <p class="text-xs text-theme-muted mb-3">{{ timeLabel }} · 按{{ granularityLabel }} · {{ statType }}</p>
        <div ref="barRef" class="w-full h-[220px]"></div>
      </div>

      <div class="mx-4 mt-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-4">
        <div class="flex items-center justify-between mb-1">
          <h3 class="font-bold text-theme-primary">多人统计</h3>
          <button @click="goTeamDetail" class="p-1 rounded hover:bg-gray-100 dark:hover:bg-slate-700">
            <ChevronRight class="w-4 h-4 text-teal-500" />
          </button>
        </div>
        <p class="text-xs text-theme-muted mb-3">¥0 · {{ timeLabel }} · 支出</p>
        <div class="w-32 h-32 mx-auto rounded-full border-[8px] border-gray-100 dark:border-slate-700 flex items-center justify-center">
          <div class="text-center">
            <p class="text-xs text-theme-muted">全部</p>
            <p class="text-lg font-bold text-theme-primary">0</p>
          </div>
        </div>
      </div>
    </template>

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
