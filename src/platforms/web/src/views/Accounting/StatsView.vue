<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import { useAccountingStore } from '@/stores/accounting'
import { getCategorySummary, getYearlySummary, type CategorySummaryItem, type YearlySummaryItem } from '@/api/accounting'
import { ChevronRight, Loader2 } from 'lucide-vue-next'
import * as echarts from 'echarts'

const store = useAccountingStore()
const now = new Date()
const currentYear = ref(now.getFullYear())
const currentMonth = ref(now.getMonth() + 1)
const statType = ref<'支出' | '收入'>('支出')

const categoryData = ref<CategorySummaryItem[]>([])
const yearlyData = ref<YearlySummaryItem[]>([])
const loading = ref(false)

const pieRef = ref<HTMLElement | null>(null)
const barRef = ref<HTMLElement | null>(null)
let pieChart: echarts.ECharts | null = null
let barChart: echarts.ECharts | null = null

const formatMoney = (n: number) =>
    new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(n)

const totalCategory = () => categoryData.value.reduce((s, c) => s + c.amount, 0)

const loadData = async () => {
    if (!store.currentBookId) return
    loading.value = true
    try {
        const [catRes, yearRes] = await Promise.all([
            getCategorySummary(store.currentBookId, currentYear.value, currentMonth.value, statType.value),
            getYearlySummary(store.currentBookId),
        ])
        categoryData.value = catRes.data
        yearlyData.value = yearRes.data
        await nextTick()
        renderPie()
        renderBar()
    } finally {
        loading.value = false
    }
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

const renderBar = () => {
    if (!barRef.value) return
    if (!barChart) barChart = echarts.init(barRef.value)

    const years = yearlyData.value.map(y => y.year)
    const dataArr = yearlyData.value.map(y =>
        statType.value === '支出' ? y.expense : y.income
    )

    barChart.setOption({
        grid: { top: 10, right: 10, bottom: 25, left: 50 },
        xAxis: {
            type: 'category',
            data: years,
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
            data: dataArr,
            barWidth: 30,
            itemStyle: {
                color: '#f87171',
                borderRadius: [4, 4, 0, 0],
            },
        }],
    })
}

watch([statType], () => loadData())

onMounted(async () => {
    if (!store.currentBookId) await store.fetchBooks()
    await loadData()
})
</script>

<template>
  <div class="pb-4">
    <div v-if="loading" class="p-12 text-center text-theme-muted">
      <Loader2 class="w-5 h-5 animate-spin mx-auto mb-2 text-teal-400" />
    </div>

    <template v-else>
      <!-- Category Stats Card -->
      <div class="mx-4 mt-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-4">
        <div class="flex items-center justify-between mb-1">
          <h3 class="font-bold text-theme-primary">分类统计</h3>
          <ChevronRight class="w-4 h-4 text-teal-500" />
        </div>
        <p class="text-xs text-theme-muted mb-3">
          ¥{{ formatMoney(totalCategory()) }} · {{ currentMonth }}月 · {{ statType }} · 一级分类
        </p>

        <!-- Type toggle -->
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

        <!-- Category List -->
        <ul class="mt-2 space-y-2">
          <li v-for="(cat, i) in categoryData" :key="cat.category" class="flex items-center gap-3">
            <div :style="{ backgroundColor: tealColors[i % tealColors.length] }" class="w-3 h-3 rounded-full flex-shrink-0" />
            <span class="flex-1 text-sm text-theme-primary">{{ cat.category }}</span>
            <span class="text-sm font-medium text-theme-primary">¥{{ formatMoney(cat.amount) }}</span>
          </li>
        </ul>
      </div>

      <!-- Yearly Stats Card -->
      <div class="mx-4 mt-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-4">
        <div class="flex items-center justify-between mb-1">
          <h3 class="font-bold text-theme-primary">年度统计</h3>
          <ChevronRight class="w-4 h-4 text-teal-500" />
        </div>
        <p class="text-xs text-theme-muted mb-3">全部时间 · {{ statType }}</p>
        <div ref="barRef" class="w-full h-[200px]"></div>
      </div>

      <!-- Multi-person Stats (placeholder) -->
      <div class="mx-4 mt-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-4">
        <div class="flex items-center justify-between mb-1">
          <h3 class="font-bold text-theme-primary">多人统计</h3>
          <ChevronRight class="w-4 h-4 text-teal-500" />
        </div>
        <p class="text-xs text-theme-muted mb-3">¥0 · {{ currentMonth }}月 · 支出</p>
        <div class="w-32 h-32 mx-auto rounded-full border-[8px] border-gray-100 dark:border-slate-700 flex items-center justify-center">
          <div class="text-center">
            <p class="text-xs text-theme-muted">全部</p>
            <p class="text-lg font-bold text-theme-primary">0</p>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>
