<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useAccountingStore } from '@/stores/accounting'
import { getRecordsSummary, type MonthlySummary } from '@/api/accounting'
import {
  BookOpen, Rss, Clock, Activity,
  TrendingUp, TrendingDown, ArrowRight
} from 'lucide-vue-next'

const router = useRouter()
const authStore = useAuthStore()
const accountingStore = useAccountingStore()

const monthlySummary = ref<MonthlySummary | null>(null)
const now = new Date()

onMounted(async () => {
    await accountingStore.fetchBooks()
    if (accountingStore.currentBookId) {
        try {
            const res = await getRecordsSummary(
                accountingStore.currentBookId,
                now.getFullYear(),
                now.getMonth() + 1
            )
            monthlySummary.value = res.data
        } catch {
            // ignore
        }
    }
})

const goAccounting = () => router.push('/accounting')

const formatMoney = (n: number) => {
    return new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: 0,
        maximumFractionDigits: 2,
    }).format(n)
}

const modules = [
    {
        id: 'accounting',
        name: '智能记账',
        desc: '通过截图、文字或语音快速记录每一笔收支',
        icon: BookOpen,
        color: 'teal',
        enabled: true,
        action: goAccounting,
    },
    {
        id: 'rss',
        name: 'RSS 订阅',
        desc: '聚合新闻源，定时推送感兴趣的内容',
        icon: Rss,
        color: 'orange',
        enabled: true,
        action: () => router.push('/modules/rss'),
    },
    {
        id: 'scheduler',
        name: '定时任务',
        desc: '设置定时提醒、数据采集等自动化任务',
        icon: Clock,
        color: 'blue',
        enabled: true,
        action: () => router.push('/modules/scheduler'),
    },
    {
        id: 'monitor',
        name: '心跳监控',
        desc: '监控服务可用性，异常时自动告警',
        icon: Activity,
        color: 'purple',
        enabled: true,
        action: () => router.push('/modules/monitor'),
    },
]

const colorMap: Record<string, { bg: string; icon: string; border: string; hover: string }> = {
    teal: {
        bg: 'bg-teal-50 dark:bg-teal-900/20',
        icon: 'bg-teal-500',
        border: 'border-teal-200 dark:border-teal-800',
        hover: 'hover:shadow-teal-100 dark:hover:shadow-teal-900/30',
    },
    orange: {
        bg: 'bg-orange-50 dark:bg-orange-900/20',
        icon: 'bg-orange-500',
        border: 'border-orange-200 dark:border-orange-800',
        hover: 'hover:shadow-orange-100 dark:hover:shadow-orange-900/30',
    },
    blue: {
        bg: 'bg-blue-50 dark:bg-blue-900/20',
        icon: 'bg-blue-500',
        border: 'border-blue-200 dark:border-blue-800',
        hover: 'hover:shadow-blue-100 dark:hover:shadow-blue-900/30',
    },
    purple: {
        bg: 'bg-purple-50 dark:bg-purple-900/20',
        icon: 'bg-purple-500',
        border: 'border-purple-200 dark:border-purple-800',
        hover: 'hover:shadow-purple-100 dark:hover:shadow-purple-900/30',
    },
}
</script>

<template>
  <div class="p-6 max-w-5xl mx-auto">
    <!-- Welcome Section -->
    <div class="mb-8">
      <h1 class="text-2xl font-bold text-theme-primary">
        欢迎回来，{{ authStore.user?.display_name || authStore.user?.email || '用户' }} 👋
      </h1>
      <p class="text-theme-muted mt-1">这里是你的 X-Bot 控制面板，选择一个模块开始吧</p>
    </div>

    <!-- Quick Stats (if accounting has data) -->
    <div v-if="monthlySummary && accountingStore.currentBookId" class="mb-8">
      <div class="grid grid-cols-3 gap-4">
        <div class="bg-theme-elevated rounded-2xl border border-theme-primary p-4 shadow-sm">
          <div class="flex items-center gap-2 mb-2">
            <TrendingDown class="w-4 h-4 text-rose-500" />
            <span class="text-xs text-theme-muted font-medium">本月支出</span>
          </div>
          <p class="text-xl font-bold text-rose-500">¥{{ formatMoney(monthlySummary.expense) }}</p>
        </div>
        <div class="bg-theme-elevated rounded-2xl border border-theme-primary p-4 shadow-sm">
          <div class="flex items-center gap-2 mb-2">
            <TrendingUp class="w-4 h-4 text-teal-500" />
            <span class="text-xs text-theme-muted font-medium">本月收入</span>
          </div>
          <p class="text-xl font-bold text-teal-500">¥{{ formatMoney(monthlySummary.income) }}</p>
        </div>
        <div class="bg-theme-elevated rounded-2xl border border-theme-primary p-4 shadow-sm">
          <div class="flex items-center gap-2 mb-2">
            <BookOpen class="w-4 h-4 text-indigo-500" />
            <span class="text-xs text-theme-muted font-medium">结余</span>
          </div>
          <p class="text-xl font-bold text-theme-primary">¥{{ formatMoney(monthlySummary.balance) }}</p>
        </div>
      </div>
    </div>

    <!-- Module Cards -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-5">
      <div
        v-for="mod in modules"
        :key="mod.id"
        @click="mod.enabled && mod.action?.()"
        :class="[
          'group rounded-2xl border p-5 transition-all duration-200 shadow-sm',
          mod.enabled
            ? `cursor-pointer ${colorMap[mod.color]?.border} ${colorMap[mod.color]?.hover} hover:shadow-md`
            : 'opacity-50 cursor-not-allowed border-gray-200 dark:border-slate-700',
          colorMap[mod.color]?.bg || 'bg-theme-elevated',
        ]"
      >
        <div class="flex items-start justify-between mb-3">
          <div :class="[
            'w-12 h-12 rounded-xl flex items-center justify-center shadow-sm',
            colorMap[mod.color]?.icon || 'bg-gray-500'
          ]">
            <component :is="mod.icon" class="w-6 h-6 text-white" />
          </div>
          <ArrowRight
            v-if="mod.enabled"
            class="w-5 h-5 text-gray-300 group-hover:text-gray-500 dark:text-slate-600 dark:group-hover:text-slate-400 transition-colors"
          />
          <span
            v-else
            class="text-[10px] font-medium text-gray-400 bg-gray-100 dark:bg-slate-800 dark:text-slate-500 px-2 py-0.5 rounded-full"
          >
            即将推出
          </span>
        </div>
        <h2 class="text-lg font-semibold text-theme-primary mb-1">{{ mod.name }}</h2>
        <p class="text-sm text-theme-muted leading-relaxed">{{ mod.desc }}</p>
      </div>
    </div>
  </div>
</template>
