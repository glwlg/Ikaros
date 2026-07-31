<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, computed, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useAccountingStore } from '@/stores/accounting'
import {
    getAccounts,
    createAccount,
    mergeAccount,
    getBalanceTrend,
    type AccountItem,
    type BalanceTrendScope,
    type ScopedBalanceTrendItem,
} from '@/api/accounting'
import { appendOperationLog } from '@/utils/accountingLocal'
import {
    Plus, Eye, EyeOff, Loader2, Banknote, CreditCard, Landmark, X, ChevronRight,
    Wallet, TrendingUp, ArrowDownLeft, ArrowUpRight
} from 'lucide-vue-next'
import * as echarts from 'echarts'
import { toIsoLocal } from './statsRange'
import { accountingConfirm } from '@/utils/accountingDialog'
import { formatAccountingMoney } from '@/utils/accountingFormat'
import {
    accountingErrorMessage,
    accountingToastError,
    accountingToastSuccess,
} from '@/utils/accountingToast'
import QuickAddFab from '@/components/accounting/QuickAddFab.vue'
import PullRefreshIndicator from '@/components/accounting/PullRefreshIndicator.vue'
import AccountingLoadingState from '@/components/accounting/AccountingLoadingState.vue'
import AccountingEmptyState from '@/components/accounting/AccountingEmptyState.vue'
import AccountingErrorState from '@/components/accounting/AccountingErrorState.vue'



const router = useRouter()


const store = useAccountingStore()
const accounts = ref<AccountItem[]>([])
const loading = ref(false)
const loadError = ref('')
const showAmount = ref(true)
const showAddAccount = ref(false)
const chartRef = ref<HTMLElement | null>(null)
const netTrendRows = ref<ScopedBalanceTrendItem[]>([])
const netTrendLoading = ref(false)
const pageRef = ref<HTMLElement | null>(null)
const refreshing = ref(false)
const pullStartY = ref<number | null>(null)
const pullDistance = ref(0)
const isPulling = ref(false)
const pullThreshold = 72
let trendChart: echarts.ECharts | null = null
let trendObserver: ResizeObserver | null = null
let delayedRenderTimer: ReturnType<typeof setTimeout> | null = null

// New account form
const newAccName = ref('')
const newAccType = ref('储蓄卡')
const newAccBalance = ref(0)
const creatingAcc = ref(false)
const showMergeAccount = ref(false)
const mergeSourceAccount = ref<AccountItem | null>(null)
const mergeTargetAccountId = ref<number | null>(null)
const mergingAccount = ref(false)

const accountTypes = ['网络支付', '信用卡', '储蓄卡', '投资账户', '现金', '充值卡', '应收账户', '应付账户']

// Grouped accounts
const grouped = computed(() => {
    const groups: Record<string, AccountItem[]> = {}
    for (const acc of accounts.value) {
        if (!groups[acc.type]) groups[acc.type] = []
        groups[acc.type]!.push(acc)
    }
    return groups
})

const groupTotal = (items: AccountItem[]) =>
    items.reduce((sum, a) => sum + a.balance, 0)

const mergeCandidates = computed(() => {
    if (!mergeSourceAccount.value) return []
    return accounts.value.filter(account => account.id !== mergeSourceAccount.value?.id)
})

const includedAccounts = computed(() => {
    return accounts.value.filter(account => account.include_in_assets)
})

const totalAssets = computed(() => {
    let assets = 0, debts = 0
    for (const acc of includedAccounts.value) {
        if (acc.balance >= 0) assets += acc.balance
        else debts += acc.balance
    }
    return { assets, debts, net: assets + debts }
})


const typeIcon = (type: string) => {
    switch (type) {
        case '现金': return Banknote
        case '信用卡': return CreditCard
        case '储蓄卡': return Landmark
        case '网络支付': return Wallet
        case '投资账户': return TrendingUp
        case '充值卡': return CreditCard
        case '应收账户': return ArrowDownLeft
        case '应付账户': return ArrowUpRight
        default: return Landmark
    }
}

const typeColor = (type: string) => {
    switch (type) {
        case '网络支付': return 'bg-teal-500'
        case '信用卡': return 'bg-amber-500'
        case '储蓄卡': return 'bg-emerald-500'
        case '投资账户': return 'bg-rose-500'
        case '现金': return 'bg-rose-400'
        case '充值卡': return 'bg-amber-400'
        case '应收账户': return 'bg-indigo-500'
        case '应付账户': return 'bg-gray-500'
        default: return 'bg-gray-400'
    }
}

const pullHint = computed(() => {
    if (refreshing.value) return '刷新中...'
    return pullDistance.value >= pullThreshold ? '松开刷新' : '下拉刷新'
})

const renderTrendChart = () => {
    if (!chartRef.value || chartRef.value.clientWidth <= 0 || chartRef.value.clientHeight <= 0) return false
    if (!trendChart) trendChart = echarts.init(chartRef.value)

    const labels = netTrendRows.value.map(item => item.period.replace('-', '/'))
    const values = netTrendRows.value.map(item => item.balance)

    trendChart.setOption({
        grid: { top: 4, right: 6, bottom: 2, left: 6 },
        xAxis: {
            type: 'category',
            data: labels.length > 0 ? labels : [''],
            boundaryGap: false,
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { show: false },
        },
        yAxis: {
            type: 'value',
            axisLine: { show: false },
            axisTick: { show: false },
            splitLine: { show: false },
            axisLabel: { show: false },
        },
        series: [{
            type: 'line',
            smooth: true,
            symbol: 'none',
            data: values.length > 0 ? values : [0],
            lineStyle: { width: 2, color: '#f8fafc' },
            areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: 'rgba(255,255,255,0.42)' },
                    { offset: 1, color: 'rgba(255,255,255,0.03)' },
                ]),
            },
        }],
    })
    trendChart.resize()
    return true
}

const renderTrendChartSafely = async () => {
    await nextTick()
    await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))

    if (renderTrendChart()) return

    if (delayedRenderTimer) clearTimeout(delayedRenderTimer)
    delayedRenderTimer = setTimeout(() => {
        renderTrendChart()
    }, 120)
}

const loadNetTrend = async () => {
    if (!store.currentBookId) {
        netTrendRows.value = []
        return
    }

    netTrendLoading.value = true
    try {
        const end = new Date()
        const start = new Date(end)
        start.setMonth(end.getMonth() - 11)
        start.setDate(1)

        const endExclusive = new Date(end)
        endExclusive.setDate(endExclusive.getDate() + 1)

        const res = await getBalanceTrend(
            store.currentBookId,
            toIsoLocal(start),
            toIsoLocal(endExclusive),
            'month',
            'net',
        )
        netTrendRows.value = res.data
    } catch (error) {
        netTrendRows.value = []
        accountingToastError(accountingErrorMessage(error, '资产趋势加载失败'))
    } finally {
        netTrendLoading.value = false
    }

    await renderTrendChartSafely()
}

const goBalanceTrend = (
    scope: BalanceTrendScope,
    options: {
        accountType?: string
        accountId?: number
    } = {},
) => {
    const end = new Date()
    const start = new Date(end)
    start.setMonth(end.getMonth() - 11)
    start.setDate(1)

    const endExclusive = new Date(end)
    endExclusive.setDate(endExclusive.getDate() + 1)

    const query: Record<string, string> = {
        scope,
        start: toIsoLocal(start),
        end: toIsoLocal(endExclusive),
    }

    if (options.accountType) {
        query.account_type = options.accountType
    }
    if (options.accountId) {
        query.account_id = String(options.accountId)
    }

    router.push({ name: 'BalanceTrendDetail', query })
}



const loadData = async () => {
    if (!store.currentBookId) return
    loading.value = true
    loadError.value = ''
    try {
        const res = await getAccounts(store.currentBookId)
        accounts.value = res.data
        await loadNetTrend()
    } catch (error) {
        loadError.value = accountingErrorMessage(error, '账户加载失败')
        accountingToastError(loadError.value)
    } finally {
        loading.value = false
    }
}

const handleCreateAccount = async () => {
    if (!newAccName.value.trim() || !store.currentBookId) return
    creatingAcc.value = true
    try {
        const res = await createAccount(store.currentBookId, {
            name: newAccName.value.trim(),
            type: newAccType.value,
            balance: newAccBalance.value,
        })
        accounts.value.push(res.data)
        appendOperationLog(
            store.currentBookId,
            '新增账户',
            `${res.data.name} · ${res.data.type} · ${formatAccountingMoney(res.data.balance)}`,
        )
        await loadNetTrend()
        newAccName.value = ''
        newAccBalance.value = 0
        showAddAccount.value = false
        accountingToastSuccess('账户已创建')
    } catch (error) {
        accountingToastError(accountingErrorMessage(error, '创建账户失败'))
    } finally {
        creatingAcc.value = false
    }
}

const openMergeAccount = (account: AccountItem) => {
    mergeSourceAccount.value = account
    mergeTargetAccountId.value = accounts.value.find(item => item.id !== account.id)?.id ?? null
    showMergeAccount.value = true
}

const closeMergeAccount = () => {
    showMergeAccount.value = false
    mergeSourceAccount.value = null
    mergeTargetAccountId.value = null
}

const handleMergeAccount = async () => {
    if (!store.currentBookId || !mergeSourceAccount.value || !mergeTargetAccountId.value) return

    const source = mergeSourceAccount.value
    const target = accounts.value.find(account => account.id === mergeTargetAccountId.value)
    if (!target) return

    const confirmed = await accountingConfirm(
        `确认将「${source.name}」合并到账户「${target.name}」吗？合并后原账户会删除，原名称会作为别名保留。`
    )
    if (!confirmed) return

    mergingAccount.value = true
    try {
        await mergeAccount(source.id, target.id)
        appendOperationLog(store.currentBookId, '合并账户', `${source.name} -> ${target.name}`)
        await loadData()
        closeMergeAccount()
        accountingToastSuccess('账户已合并')
    } catch (error) {
        accountingToastError(accountingErrorMessage(error, '合并失败，请稍后重试'))
    } finally {
        mergingAccount.value = false
    }
}

const getScrollParent = () => {
    let node: HTMLElement | null = pageRef.value?.parentElement || null
    while (node) {
        const style = window.getComputedStyle(node)
        const scrollable = /(auto|scroll)/.test(style.overflowY)
        if (scrollable && node.scrollHeight > node.clientHeight) {
            return node
        }
        node = node.parentElement
    }
    return null
}

const resetPull = () => {
    pullDistance.value = 0
    pullStartY.value = null
    isPulling.value = false
}

const triggerRefresh = async () => {
    if (refreshing.value) return
    refreshing.value = true
    try {
        if (!store.currentBookId) {
            await store.fetchBooks()
        }
        await loadData()
    } finally {
        refreshing.value = false
        resetPull()
    }
}

const handleTouchStart = (event: TouchEvent) => {
    if (refreshing.value) return
    const scrollParent = getScrollParent()
    if (scrollParent && scrollParent.scrollTop > 0) return
    pullStartY.value = event.touches[0]?.clientY ?? null
    isPulling.value = true
}

const handleTouchMove = (event: TouchEvent) => {
    if (!isPulling.value || pullStartY.value === null) return
    const currentY = event.touches[0]?.clientY ?? pullStartY.value
    const delta = currentY - pullStartY.value
    if (delta <= 0) {
        pullDistance.value = 0
        return
    }

    pullDistance.value = Math.min(120, delta * 0.5)
    if (pullDistance.value > 0) {
        event.preventDefault()
    }
}

const handleTouchEnd = () => {
    if (!isPulling.value) return
    if (pullDistance.value >= pullThreshold) {
        void triggerRefresh()
        return
    }
    resetPull()
}

onMounted(async () => {
    if (!store.currentBookId) await store.fetchBooks()
    await loadData()

    if (typeof ResizeObserver !== 'undefined' && chartRef.value) {
        trendObserver = new ResizeObserver(() => trendChart?.resize())
        trendObserver.observe(chartRef.value)
    }
})

onBeforeUnmount(() => {
    trendObserver?.disconnect()
    trendObserver = null

    if (delayedRenderTimer) {
        clearTimeout(delayedRenderTimer)
        delayedRenderTimer = null
    }

    trendChart?.dispose()
    trendChart = null
})
</script>

<template>
  <div
    ref="pageRef"
    class="accounting-page-pad accounting-assets-page"
    @touchstart="handleTouchStart"
    @touchmove="handleTouchMove"
    @touchend="handleTouchEnd"
    @touchcancel="handleTouchEnd"
  >
    <PullRefreshIndicator :distance="pullDistance" :hint="pullHint" :refreshing="refreshing" />

    <!-- Header -->
    <div class="flex items-center justify-between px-4 pt-3 pb-2">
      <h2 class="text-lg font-bold text-theme-primary">净资产</h2>
      <button
        type="button"
        class="accounting-touch-target inline-flex items-center justify-center rounded-xl p-2 active:bg-theme-secondary"
        aria-label="添加账户"
        @click="showAddAccount = true"
      >
        <Plus class="w-5 h-5 text-theme-muted" />
      </button>
    </div>

    <!-- Net Worth Card -->
    <div
      class="accounting-net-worth-card mx-3 sm:mx-4 rounded-3xl p-4 sm:p-5 text-white shadow-lg relative overflow-hidden cursor-pointer"
      @click="goBalanceTrend('net')"
    >
      <div class="absolute inset-0 opacity-10 bg-[radial-gradient(circle_at_20%_20%,rgba(255,255,255,0.35),transparent_45%),radial-gradient(circle_at_80%_70%,rgba(255,255,255,0.18),transparent_45%)]" />
      <div class="relative z-10">
        <div class="flex items-start justify-between gap-2 mb-1">
          <div class="flex items-center gap-2 min-w-0 flex-1">
            <span class="text-2xl sm:text-4xl font-bold tracking-tight tabular-nums break-all leading-tight drop-shadow-[0_2px_8px_rgba(0,0,0,0.35)]">
              {{ showAmount ? formatAccountingMoney(totalAssets.net) : '****' }}
            </span>
            <button
              type="button"
              class="accounting-touch-target inline-flex items-center justify-center opacity-85 active:opacity-100 flex-shrink-0"
              aria-label="显示或隐藏金额"
              @click.stop="showAmount = !showAmount"
            >
              <EyeOff v-if="showAmount" class="w-5 h-5" />
              <Eye v-else class="w-5 h-5" />
            </button>
          </div>

          <button
            type="button"
            class="px-2.5 py-1.5 rounded-full border border-white/50 text-xs bg-white/15 active:bg-white/25 transition flex-shrink-0"
            @click.stop="goBalanceTrend('net')"
          >
            趋势
          </button>
        </div>

        <div class="flex flex-wrap gap-2 text-sm mt-2">
          <button
            type="button"
            class="px-3 py-1.5 rounded-xl bg-white/18 active:bg-white/28 transition min-h-[36px]"
            @click.stop="goBalanceTrend('assets')"
          >
            资产 {{ showAmount ? formatAccountingMoney(totalAssets.assets) : '****' }}
          </button>
          <button
            type="button"
            class="px-3 py-1.5 rounded-xl bg-white/18 active:bg-white/28 transition min-h-[36px]"
            @click.stop="goBalanceTrend('liabilities')"
          >
            负债 {{ showAmount ? formatAccountingMoney(totalAssets.debts) : '****' }}
          </button>
        </div>
      </div>

      <div ref="chartRef" class="h-[64px] sm:h-[76px] mt-3 relative z-10"></div>
      <div v-if="netTrendLoading" class="absolute inset-0 z-20 flex items-center justify-center bg-black/10">
        <Loader2 class="w-4 h-4 animate-spin text-white" />
      </div>
    </div>

    <AccountingLoadingState v-if="loading" />
    <AccountingErrorState
      v-else-if="loadError"
      title="账户加载失败"
      :description="loadError"
      @retry="loadData"
    />

    <!-- Account Groups -->
    <template v-else>
      <div v-for="(items, type) in grouped" :key="type" class="mx-3 sm:mx-4 mt-3 sm:mt-4 rounded-2xl bg-theme-elevated shadow-sm border border-theme-secondary overflow-hidden">
        <!-- Group Header -->
        <div class="flex items-center justify-between px-3 sm:px-4 py-2.5 border-b border-theme-secondary">
          <button
            type="button"
            class="text-sm text-theme-muted font-medium active:text-accounting-brand transition"
            @click="goBalanceTrend('account_type', { accountType: type as string })"
          >
            {{ type }}
          </button>
          <button
            type="button"
            class="text-sm text-theme-muted tabular-nums active:text-accounting-brand transition"
            @click="goBalanceTrend('account_type', { accountType: type as string })"
          >
            {{ showAmount ? formatAccountingMoney(groupTotal(items)) : '****' }}
          </button>
        </div>
        <!-- Account Items -->
        <div
          v-for="acc in items"
          :key="acc.id"
          class="flex items-center gap-2.5 sm:gap-3 px-3 sm:px-4 py-3 min-h-[56px] active:bg-theme-secondary/70 transition cursor-pointer"
          @click="router.push(`/accounting/account/${acc.id}`)"
        >
          <div :class="['w-9 h-9 rounded-xl flex items-center justify-center flex-shrink-0', typeColor(type as string)]">
            <component :is="typeIcon(type as string)" class="w-4 h-4 text-white" />
          </div>
          <div class="flex-1 min-w-0">
            <div class="font-medium text-theme-primary text-sm truncate">{{ acc.name }}</div>
            <div v-if="acc.aliases?.length" class="mt-0.5 text-xs text-theme-muted truncate">
              别名：{{ acc.aliases.join(' / ') }}
            </div>
          </div>
          <div class="flex flex-col items-end gap-1 flex-shrink-0">
            <span class="text-accounting-brand font-semibold text-sm tabular-nums">
              {{ showAmount ? formatAccountingMoney(acc.balance) : '****' }}
            </span>
            <button
              v-if="accounts.length > 1"
              type="button"
              class="px-2 py-0.5 rounded-md border border-theme-primary text-[11px] text-theme-muted active:text-accounting-brand active:border-accounting-brand"
              @click.stop="openMergeAccount(acc)"
            >
              合并
            </button>
          </div>
          <ChevronRight class="w-4 h-4 text-theme-muted flex-shrink-0" />
        </div>
      </div>

      <AccountingEmptyState
        v-if="accounts.length === 0"
        title="暂无账户"
        description="点击右上角 + 添加第一个账户"
      />
    </template>

    <!-- Add Account Modal -->
    <div
      v-if="showAddAccount"
      class="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4"
      @click.self="showAddAccount = false"
    >
      <div class="bg-theme-elevated rounded-t-2xl sm:rounded-2xl p-5 sm:p-6 w-full sm:w-[360px] max-h-[90dvh] overflow-y-auto accounting-scroll shadow-xl safe-bottom">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-lg font-semibold text-theme-primary">添加账户</h3>
          <button @click="showAddAccount = false"><X class="w-5 h-5 text-theme-muted" /></button>
        </div>
        <form @submit.prevent="handleCreateAccount" class="space-y-3">
          <div>
            <label class="text-xs text-theme-muted font-medium">账户名称</label>
            <input v-model="newAccName" type="text" placeholder="如：招商银行-陈" class="accounting-field mt-1" autofocus />
          </div>
          <div>
            <label class="text-xs text-theme-muted font-medium">类型</label>
            <select v-model="newAccType" class="accounting-field mt-1">
              <option v-for="t in accountTypes" :key="t" :value="t">{{ t }}</option>
            </select>
          </div>
          <div>
            <label class="text-xs text-theme-muted font-medium">余额</label>
            <input v-model.number="newAccBalance" type="number" step="0.01" class="accounting-field mt-1" />
          </div>
          <button
            type="submit"
            :disabled="creatingAcc || !newAccName.trim()"
            class="w-full py-2.5 bg-accounting-brand hover:opacity-90 text-white font-medium rounded-xl transition disabled:opacity-50"
          >
            <Loader2 v-if="creatingAcc" class="w-4 h-4 animate-spin mx-auto" />
            <span v-else>添加</span>
          </button>
        </form>
      </div>
    </div>

    <div
      v-if="showMergeAccount && mergeSourceAccount"
      class="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4"
      @click.self="closeMergeAccount"
    >
      <div class="bg-theme-elevated rounded-t-2xl sm:rounded-2xl p-5 sm:p-6 w-full sm:w-[360px] max-h-[90dvh] overflow-y-auto accounting-scroll shadow-xl safe-bottom">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-lg font-semibold text-theme-primary">合并账户</h3>
          <button @click="closeMergeAccount"><X class="w-5 h-5 text-theme-muted" /></button>
        </div>
        <div class="space-y-3">
          <div class="rounded-2xl bg-slate-50 dark:bg-slate-700/60 px-3 py-3">
            <div class="text-xs text-theme-muted">待合并账户</div>
            <div class="mt-1 text-sm font-medium text-theme-primary">{{ mergeSourceAccount.name }}</div>
            <div v-if="mergeSourceAccount.aliases?.length" class="mt-1 text-xs text-theme-muted">
              现有别名：{{ mergeSourceAccount.aliases.join(' / ') }}
            </div>
          </div>
          <div>
            <label class="text-xs text-theme-muted font-medium">合并到</label>
            <select
              v-model.number="mergeTargetAccountId"
              class="accounting-field mt-1"
            >
              <option v-for="account in mergeCandidates" :key="account.id" :value="account.id">
                {{ account.name }}
              </option>
            </select>
          </div>
          <p class="text-xs leading-5 text-theme-muted">
            合并后，原账户会被删除，原名称和已有别名会挂到目标账户下，后续识别到账户名时会优先匹配这些别名。
          </p>
          <button
            type="button"
            :disabled="mergingAccount || !mergeTargetAccountId"
            @click="handleMergeAccount"
            class="w-full py-2.5 bg-accounting-brand hover:opacity-90 text-white font-medium rounded-xl transition disabled:opacity-50"
          >
            <Loader2 v-if="mergingAccount" class="w-4 h-4 animate-spin mx-auto" />
            <span v-else>确认合并</span>
          </button>
        </div>
      </div>
    </div>

    <QuickAddFab :book-id="store.currentBookId" @saved="loadData" />
  </div>
</template>
