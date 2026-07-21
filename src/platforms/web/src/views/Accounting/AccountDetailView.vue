<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAccountingStore } from '@/stores/accounting'
import {
    getAccountDetail, getAccountRecords, getAccountBalanceTrend,
    updateAccount, adjustAccountBalance, deleteAccount,
    type AccountItem, type RecordItem, type BalanceTrendItem
} from '@/api/accounting'
import {
    ArrowLeft, Trash2, Pencil, X, Loader2, Plus
} from 'lucide-vue-next'
import * as echarts from 'echarts'
import { appendOperationLog } from '@/utils/accountingLocal'
import { formatAccountingMoney } from '@/utils/accountingFormat'
import { buildRecordListQuery } from '@/utils/accountingNavigation'
import AddRecordDialog from '@/components/accounting/AddRecordDialog.vue'
import AccountingLoadingState from '@/components/accounting/AccountingLoadingState.vue'
import AccountingEmptyState from '@/components/accounting/AccountingEmptyState.vue'
import AccountingErrorState from '@/components/accounting/AccountingErrorState.vue'
import {
    accountingErrorMessage,
    accountingToastError,
    accountingToastSuccess,
} from '@/utils/accountingToast'



const router = useRouter()
const route = useRoute()
const store = useAccountingStore()
const accountId = Number(route.params.id)

const account = ref<AccountItem | null>(null)
const records = ref<RecordItem[]>([])
const trendData = ref<BalanceTrendItem[]>([])
const loading = ref(false)
const loadError = ref('')

// Edit modal
const showEdit = ref(false)
const editName = ref('')
const editType = ref('')
const saving = ref(false)

// Balance adjust modal
const showAdjust = ref(false)
const adjustTarget = ref(0)
const adjustMethod = ref('差额补记收支')
const adjusting = ref(false)

// Delete confirmation
const showDeleteConfirm = ref(false)
const showAddRecord = ref(false)

const openAllRecords = () => {
    if (!account.value) return
    const query = buildRecordListQuery({
        account: account.value.name,
        label: account.value.name,
    })
    router.push({ name: 'RecordList', query })
}

const onRecordSaved = () => {
    showAddRecord.value = false
    void loadData()
}

const chartRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

const accountTypes = ['网络支付', '信用卡', '储蓄卡', '投资账户', '现金', '充值卡', '应收账户', '应付账户']
const adjustMethods = [
    { value: '差额补记收支', desc: '添加收入或支出，使余额达到指定金额。' },
    { value: '差额补记转账', desc: '添加无账户转账，不计入收支。' },
    { value: '更改当前余额', desc: '设置初始金额为指定金额，设置余额起始时间为当前时间，余额趋势统计将丢失。' },
    { value: '设置初始余额', desc: '设置初始金额为指定金额。' },
]

const togglingAssets = ref(false)

const resolveLogBookId = () => {
    return store.currentBookId || account.value?.book_id || null
}

const handleToggleAssets = async () => {
    if (!account.value || togglingAssets.value) return
    togglingAssets.value = true
    try {
        const newVal = !account.value.include_in_assets
        await updateAccount(accountId, { include_in_assets: newVal })
        account.value.include_in_assets = newVal
        appendOperationLog(
            resolveLogBookId(),
            '更新账户',
            `${account.value.name} · 计入资产 ${newVal ? '开启' : '关闭'}`,
        )
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '状态更新失败'))
    } finally {
        togglingAssets.value = false
    }
}


const formatDate = (iso: string) => {
    const d = new Date(iso)
    return `${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`
}

const getRecordDelta = (record: RecordItem) => {
    const currentAccountName = account.value?.name
    if (!currentAccountName) {
        return record.type === '收入' ? record.amount : -record.amount
    }

    if (record.type === '收入') return record.amount
    if (record.type === '支出') return -record.amount
    if (record.type === '转账') {
        if (record.target_account === currentAccountName) return record.amount
        if (record.account === currentAccountName) return -record.amount
    }

    return record.type === '收入' ? record.amount : -record.amount
}

const isPositiveRecord = (record: RecordItem) => getRecordDelta(record) > 0

const loadData = async () => {
    loading.value = true
    loadError.value = ''
    try {
        const [detailRes, recordsRes, trendRes] = await Promise.all([
            getAccountDetail(accountId),
            getAccountRecords(accountId, 20),
            getAccountBalanceTrend(accountId, 30),
        ])
        account.value = detailRes.data
        records.value = recordsRes.data
        trendData.value = trendRes.data
        await nextTick()
        renderChart()
    } catch (e) {
        loadError.value = accountingErrorMessage(e, '账户详情加载失败')
        accountingToastError(loadError.value)
    } finally {
        loading.value = false
    }
}

const renderChart = () => {
    if (!chartRef.value) return
    if (!chartInstance) chartInstance = echarts.init(chartRef.value)

    const dates = trendData.value.map(t => {
        const parts = t.date.split('-')
        return `${parts[1]}.${parts[2]}`
    })
    const balances = trendData.value.map(t => t.balance)

    chartInstance.setOption({
        grid: { top: 20, right: 15, bottom: 25, left: 50 },
        xAxis: {
            type: 'category',
            data: dates.length > 0 ? dates : [''],
            axisLine: { show: false },
            axisTick: { show: false },
            axisLabel: { color: '#9ca3af', fontSize: 10 },
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
            type: 'line',
            data: balances,
            smooth: true,
            symbol: 'none',
            lineStyle: { color: '#14b8a6', width: 2 },
            areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: 'rgba(20,184,166,0.25)' },
                    { offset: 1, color: 'rgba(20,184,166,0.02)' },
                ]),
            },
        }],
    })
}

const openEdit = () => {
    if (!account.value) return
    editName.value = account.value.name
    editType.value = account.value.type
    showEdit.value = true
}

const handleSaveEdit = async () => {
    if (!account.value) return
    saving.value = true
    try {
        await updateAccount(accountId, {
            name: editName.value,
            type: editType.value,
        })
        appendOperationLog(
            resolveLogBookId(),
            '更新账户',
            `${editName.value} · ${editType.value}`,
        )
        await loadData()
        showEdit.value = false
        accountingToastSuccess('账户已更新')
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '更新失败'))
    } finally {
        saving.value = false
    }
}

const openAdjust = () => {
    if (!account.value) return
    adjustTarget.value = account.value.balance
    adjustMethod.value = '差额补记收支'
    showAdjust.value = true
}

const handleAdjust = async () => {
    adjusting.value = true
    try {
        await adjustAccountBalance(accountId, {
            target_balance: adjustTarget.value,
            method: adjustMethod.value,
        })
        appendOperationLog(
            resolveLogBookId(),
            '更新账户余额',
            `${account.value?.name || '账户'} · ${adjustMethod.value} · ${formatAccountingMoney(adjustTarget.value)}`,
        )
        await loadData()
        showAdjust.value = false
        accountingToastSuccess('余额已调整')
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '调整失败'))
    } finally {
        adjusting.value = false
    }
}

const handleDelete = async () => {
    const snapshot = account.value
    try {
        await deleteAccount(accountId)
        if (snapshot) {
            appendOperationLog(
                resolveLogBookId(),
                '删除账户',
                `${snapshot.name} · ${snapshot.type} · ${formatAccountingMoney(snapshot.balance)}`,
                {
                    rollback: {
                        kind: 'account',
                        data: {
                            name: snapshot.name,
                            type: snapshot.type,
                            balance: snapshot.balance,
                            include_in_assets: snapshot.include_in_assets,
                        },
                    },
                },
            )
        } else {
            appendOperationLog(resolveLogBookId(), '删除账户', `ID ${accountId}`)
        }
        accountingToastSuccess('账户已删除')
        router.push('/accounting/assets')
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '删除失败'))
    }
}

onMounted(loadData)
</script>

<template>
  <div class="accounting-subpage-pad min-h-full">
    <!-- Custom Header (override AccountingLayout) -->
    <div class="sticky top-0 z-20 bg-gradient-to-r from-indigo-500 to-indigo-400 px-4 py-3 flex items-center justify-between shadow-sm">
      <button @click="router.push('/accounting/assets')" class="flex items-center gap-1.5 text-white/90 hover:text-white transition">
        <ArrowLeft class="w-4 h-4" />
        <span class="font-semibold">{{ account?.name || '账户详情' }}</span>
      </button>
      <button @click="showDeleteConfirm = true" class="text-white/80 hover:text-white transition">
        <Trash2 class="w-5 h-5" />
      </button>
    </div>

    <AccountingLoadingState v-if="loading && !account" />
    <AccountingErrorState
      v-else-if="loadError && !account"
      title="账户加载失败"
      :description="loadError"
      @retry="loadData"
    />

    <template v-if="account">
      <!-- Balance Card -->
      <div class="mx-4 mt-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-5">
        <div class="flex items-center justify-between mb-1">
          <span class="text-sm text-theme-muted">当前余额</span>
        </div>
        <div class="flex items-center gap-3">
          <span :class="['text-3xl font-bold', account.balance >= 0 ? 'text-indigo-500' : 'text-rose-500']">
            {{ formatAccountingMoney(account.balance) }}
          </span>
          <button @click="openAdjust" class="p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-700 transition">
            <Pencil class="w-4 h-4 text-theme-muted" />
          </button>
        </div>
        <p class="text-xs text-theme-muted mt-2">当前余额 = 初始余额 + 余额起始时间后的交易金额的和</p>
      </div>

      <!-- Trend Chart -->
      <div class="mx-4 mt-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 p-4">
        <div class="flex items-center justify-between mb-2">
          <h3 class="font-semibold text-theme-primary">余额趋势</h3>
          <span class="text-xs text-theme-muted">近 30 日</span>
        </div>
        <div ref="chartRef" class="w-full h-[160px]"></div>
      </div>

      <!-- Recent Records -->
      <div class="mx-4 mt-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700">
        <div class="flex items-center justify-between p-4 pb-2">
          <h3 class="font-semibold text-theme-primary">最近交易</h3>
          <button
            type="button"
            class="accounting-touch-target inline-flex items-center justify-center p-1.5 rounded-lg active:bg-theme-secondary text-accounting-brand"
            aria-label="记一笔"
            @click="showAddRecord = true"
          >
            <Plus class="w-5 h-5" />
          </button>
        </div>

        <AccountingEmptyState
          v-if="records.length === 0"
          title="暂无交易记录"
          description="点右上角 + 记一笔"
        />

        <ul v-else class="divide-y divide-gray-50 dark:divide-slate-700/50">
          <li v-for="rec in records" :key="rec.id" class="px-4 py-3">
            <RouterLink :to="`/accounting/records/${rec.id}`" class="flex items-center justify-between hover:opacity-80 transition">
              <div class="flex items-center gap-3">
                <div class="w-2 h-2 rounded-full bg-indigo-400 flex-shrink-0" />
                <div>
                  <p class="font-medium text-theme-primary text-sm">{{ rec.category || rec.remark || '余额变更' }}</p>
                  <p class="text-xs text-theme-muted">{{ formatDate(rec.record_time) }}</p>
                </div>
              </div>
              <div class="text-right">
                <span :class="['font-semibold text-sm', isPositiveRecord(rec) ? 'text-indigo-500' : 'text-rose-500']">
                  {{ formatAccountingMoney(getRecordDelta(rec), { signed: true }) }}
                </span>
              </div>
            </RouterLink>
          </li>
        </ul>

        <button
          type="button"
          class="w-full p-3 text-sm text-accounting-brand font-medium border-t border-gray-50 dark:border-slate-700/50 min-h-[48px] active:bg-theme-secondary"
          @click="openAllRecords"
        >
          所有交易
        </button>
      </div>

      <!-- Account Settings -->
      <div class="mx-4 mt-4 rounded-2xl bg-white dark:bg-slate-800 shadow-sm border border-gray-100 dark:border-slate-700 overflow-hidden">
        <div class="px-4 py-3 flex items-center justify-between border-b border-gray-50 dark:border-slate-700/50">
          <span class="text-sm text-theme-primary flex items-center gap-2">
            计入资产
            <Loader2 v-if="togglingAssets" class="w-3 h-3 animate-spin text-theme-muted" />
          </span>
          <div
            @click="handleToggleAssets"
            :class="['w-12 h-7 rounded-full relative cursor-pointer transition-colors duration-200', account.include_in_assets ? 'bg-indigo-500' : 'bg-gray-200 dark:bg-slate-600']"
          >
            <div :class="['absolute top-0.5 w-6 h-6 rounded-full bg-white shadow transition-transform duration-200', account.include_in_assets ? 'translate-x-[22px]' : 'translate-x-0.5']" />
          </div>
        </div>
        <div @click="openEdit" class="px-4 py-3 flex items-center justify-between border-b border-gray-50 dark:border-slate-700/50 cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-700 transition">
          <span class="text-sm text-theme-primary">类型</span>
          <div class="flex items-center gap-1">
            <span class="text-sm text-theme-muted">{{ account.type }}</span>
            <ChevronRight class="w-4 h-4 text-theme-muted" />
          </div>
        </div>
        <div @click="openEdit" class="px-4 py-3 flex items-center justify-between border-b border-gray-50 dark:border-slate-700/50 cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-700 transition">
          <span class="text-sm text-theme-primary">名称</span>
          <div class="flex items-center gap-1">
            <span class="text-sm text-theme-muted">{{ account.name }}</span>
            <ChevronRight class="w-4 h-4 text-theme-muted" />
          </div>
        </div>
        <div class="px-4 py-3 flex items-center justify-between">
          <span class="text-sm text-theme-primary">货币</span>
          <span class="text-sm text-theme-muted">人民币</span>
        </div>
      </div>
    </template>

    <!-- Edit Account Modal -->
    <div v-if="showEdit" class="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4" @click.self="showEdit = false">
      <div class="bg-theme-elevated rounded-t-2xl sm:rounded-2xl p-5 sm:p-6 w-full sm:w-[360px] max-h-[90dvh] overflow-y-auto accounting-scroll shadow-xl safe-bottom">
        <div class="flex items-center justify-between mb-4">
          <h3 class="text-lg font-semibold text-theme-primary">编辑账户</h3>
          <button @click="showEdit = false"><X class="w-5 h-5 text-theme-muted" /></button>
        </div>
        <form @submit.prevent="handleSaveEdit" class="space-y-3">
          <div>
            <label class="text-xs text-theme-muted font-medium">名称</label>
            <input v-model="editName" type="text" class="accounting-field mt-1" />
          </div>
          <div>
            <label class="text-xs text-theme-muted font-medium">类型</label>
            <select v-model="editType" class="accounting-field mt-1">
              <option v-for="t in accountTypes" :key="t" :value="t">{{ t }}</option>
            </select>
          </div>
          <button type="submit" :disabled="saving" class="w-full py-2.5 bg-indigo-500 hover:bg-indigo-600 text-white font-medium rounded-xl transition disabled:opacity-50">
            <Loader2 v-if="saving" class="w-4 h-4 animate-spin mx-auto" />
            <span v-else>保存</span>
          </button>
        </form>
      </div>
    </div>

    <!-- Balance Adjust Modal -->
    <div v-if="showAdjust" class="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4" @click.self="showAdjust = false">
      <div class="bg-theme-elevated rounded-t-2xl sm:rounded-2xl p-5 sm:p-6 w-full sm:w-[360px] max-h-[90dvh] overflow-y-auto accounting-scroll shadow-xl safe-bottom">
        <h3 class="text-lg font-semibold text-theme-primary mb-4">余额校正</h3>
        <input
          v-model.number="adjustTarget"
          type="number"
          step="0.01"
          class="accounting-field mb-4 text-lg font-bold"
        />
        <div class="space-y-3 mb-5">
          <label
            v-for="m in adjustMethods"
            :key="m.value"
            class="flex items-start gap-3 cursor-pointer"
          >
            <div :class="['w-5 h-5 mt-0.5 rounded border-2 flex-shrink-0 flex items-center justify-center transition',
              adjustMethod === m.value
                ? 'border-indigo-500 bg-indigo-500'
                : 'border-gray-300 dark:border-slate-600'
            ]">
              <svg v-if="adjustMethod === m.value" class="w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3"><path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" /></svg>
            </div>
            <div @click="adjustMethod = m.value">
              <p class="text-sm font-medium text-theme-primary">{{ m.value }}</p>
              <p class="text-xs text-theme-muted">{{ m.desc }}</p>
            </div>
          </label>
        </div>
        <div class="flex gap-3">
          <button
            @click="showAdjust = false"
            class="flex-1 py-2.5 border border-gray-200 dark:border-slate-600 rounded-xl text-theme-secondary font-medium hover:bg-gray-50 dark:hover:bg-slate-700 transition"
          >取消</button>
          <button
            @click="handleAdjust"
            :disabled="adjusting"
            class="flex-1 py-2.5 text-indigo-500 font-bold rounded-xl transition hover:bg-indigo-50 dark:hover:bg-indigo-900/20 disabled:opacity-50"
          >
            <Loader2 v-if="adjusting" class="w-4 h-4 animate-spin mx-auto" />
            <span v-else>完成</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Delete Confirm -->
    <div v-if="showDeleteConfirm" class="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 p-0 sm:p-4" @click.self="showDeleteConfirm = false">
      <div class="bg-theme-elevated rounded-t-2xl sm:rounded-2xl p-5 sm:p-6 w-full sm:w-[340px] max-h-[90dvh] overflow-y-auto accounting-scroll shadow-xl safe-bottom text-center">
        <h3 class="text-lg font-semibold text-theme-primary mb-2">删除账户</h3>
        <p class="text-sm text-theme-muted mb-5">确定要删除「{{ account?.name }}」吗？删除后可在操作日志里回滚。</p>
        <div class="flex gap-3">
          <button @click="showDeleteConfirm = false" class="flex-1 py-2.5 border border-gray-200 dark:border-slate-600 rounded-xl text-theme-secondary font-medium">取消</button>
          <button @click="handleDelete" class="flex-1 py-2.5 bg-rose-500 hover:bg-rose-600 text-white font-medium rounded-xl transition">删除</button>
        </div>
      </div>
    </div>

    <AddRecordDialog
      v-if="showAddRecord && store.currentBookId"
      :book-id="store.currentBookId"
      @close="showAddRecord = false"
      @saved="onRecordSaved"
    />
  </div>
</template>
