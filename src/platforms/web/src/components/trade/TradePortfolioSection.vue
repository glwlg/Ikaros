<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import {
  Plus,
  ArrowDownRight,
  Calculator,
  History,
  Settings,
  Trash2,
  RefreshCw,
  Pencil,
} from 'lucide-vue-next'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import TradePortfolioSummary from './TradePortfolioSummary.vue'
import AccountSelectorTabs from './AccountSelectorTabs.vue'
import TradePositionTable from './TradePositionTable.vue'
import AccountDialog from './AccountDialog.vue'
import CashFlowDialog from './CashFlowDialog.vue'
import TradeOrderDialog from './TradeOrderDialog.vue'
import TradeSimulationDialog from './TradeSimulationDialog.vue'
import TradeOrdersDrawer from './TradeOrdersDrawer.vue'
import {
  getTradeAccounts,
  getPortfolioSummary,
  getAccountPositions,
  createTradeAccount,
  updateTradeAccount,
  deleteTradeAccount,
  addCashFlow,
  createTradeOrder,
  type TradeAccount,
  type TradePosition,
  type PortfolioSummary,
} from '@/api/trade'

const panelOptics = {
  mapSize: 256,
  strength: 0.06,
  depth: 0.72,
  dispersion: 0.46,
  frost: 4,
  saturate: 1.22,
  specular: 1.15,
  glow: 0.22,
  sheen: 0.78,
  curvature: 0.38,
  bend: 0.62,
}

const loading = ref(false)
const accounts = ref<TradeAccount[]>([])
const selectedAccountId = ref<number | null>(null)
const summary = ref<PortfolioSummary | null>(null)
const positions = ref<TradePosition[]>([])
const positionsLoading = ref(false)

// 弹窗状态
const showAccountDialog = ref(false)
const editingAccount = ref<TradeAccount | null>(null)
const accountSubmitting = ref(false)

const showCashFlowDialog = ref(false)
const cashFlowSubmitting = ref(false)

const showOrderDialog = ref(false)
const orderPosition = ref<TradePosition | null>(null)
const orderTradeType = ref<'buy' | 'sell'>('buy')
const orderSubmitting = ref(false)

const showSimDialog = ref(false)
const simPosition = ref<TradePosition | null>(null)

const showDrawer = ref(false)

const currentAccount = computed(() => {
  if (!selectedAccountId.value) return null
  return accounts.value.find((a) => a.id === selectedAccountId.value) || null
})

const loadAccountsAndSummary = async () => {
  loading.value = true
  try {
    const [accRes, sumRes] = await Promise.all([
      getTradeAccounts(),
      getPortfolioSummary(),
    ])
    accounts.value = accRes.data || []
    summary.value = sumRes.data || null

    if (selectedAccountId.value && !accounts.value.some((a) => a.id === selectedAccountId.value)) {
      selectedAccountId.value = null
    }
    await loadPositions()
  } catch (err) {
    console.error('加载交易账户与资产汇总失败', err)
  } finally {
    loading.value = false
  }
}

const loadPositions = async () => {
  if (!selectedAccountId.value) {
    // 全景视图下获取所有持仓合并
    positionsLoading.value = true
    try {
      const allPos: TradePosition[] = []
      for (const acc of accounts.value) {
        const res = await getAccountPositions(acc.id)
        if (res.data) allPos.push(...res.data)
      }
      positions.value = allPos
    } catch (err) {
      console.error('加载全景持仓失败', err)
    } finally {
      positionsLoading.value = false
    }
    return
  }

  positionsLoading.value = true
  try {
    const res = await getAccountPositions(selectedAccountId.value)
    positions.value = res.data || []
  } catch (err) {
    console.error('加载账户持仓失败', err)
  } finally {
    positionsLoading.value = false
  }
}

const handleSelectAccount = (id: number | null) => {
  selectedAccountId.value = id
  loadPositions()
}

// 账户 CRUD
const openCreateAccount = () => {
  editingAccount.value = null
  showAccountDialog.value = true
}

const openEditAccount = () => {
  if (!currentAccount.value) return
  editingAccount.value = currentAccount.value
  showAccountDialog.value = true
}

const handleSaveAccount = async (payload: any) => {
  accountSubmitting.value = true
  try {
    if (editingAccount.value) {
      await updateTradeAccount(editingAccount.value.id, payload)
    } else {
      const res = await createTradeAccount(payload)
      selectedAccountId.value = res.data.id
    }
    showAccountDialog.value = false
    await loadAccountsAndSummary()
  } catch (err) {
    console.error('保存账户失败', err)
  } finally {
    accountSubmitting.value = false
  }
}

const handleDeleteCurrentAccount = async () => {
  if (!currentAccount.value) return
  if (!confirm('确定删除账户「' + currentAccount.value.name + '」及其所有持仓与流水吗？此操作无法撤销。')) return
  try {
    await deleteTradeAccount(currentAccount.value.id)
    selectedAccountId.value = null
    await loadAccountsAndSummary()
  } catch (err) {
    console.error('删除账户失败', err)
  }
}

// 银证转账
const openCashFlow = () => {
  if (!currentAccount.value) return
  showCashFlowDialog.value = true
}

const handleSaveCashFlow = async (payload: { flow_type: 'deposit' | 'withdraw'; amount: number; notes: string }) => {
  if (!currentAccount.value) return
  cashFlowSubmitting.value = true
  try {
    await addCashFlow(currentAccount.value.id, payload)
    showCashFlowDialog.value = false
    await loadAccountsAndSummary()
  } catch (err: any) {
    alert(err?.response?.data?.detail || '转账处理失败')
  } finally {
    cashFlowSubmitting.value = false
  }
}

// 记账订单
const openNewOrder = () => {
  orderPosition.value = null
  orderTradeType.value = 'buy'
  showOrderDialog.value = true
}

const handleBuyPosition = (pos: TradePosition) => {
  orderPosition.value = pos
  orderTradeType.value = 'buy'
  showOrderDialog.value = true
}

const handleSellPosition = (pos: TradePosition) => {
  orderPosition.value = pos
  orderTradeType.value = 'sell'
  showOrderDialog.value = true
}

const handleSaveOrder = async (payload: any) => {
  orderSubmitting.value = true
  try {
    await createTradeOrder(payload)
    showOrderDialog.value = false
    await loadAccountsAndSummary()
  } catch (err: any) {
    alert(err?.response?.data?.detail || '交割记账失败')
  } finally {
    orderSubmitting.value = false
  }
}

// 试算
const openSimulate = (pos?: TradePosition) => {
  simPosition.value = pos || null
  showSimDialog.value = true
}

const handleApplySimToOrder = (applied: { stock_code: string; stock_name: string; price: number; quantity: number }) => {
  showSimDialog.value = false
  orderPosition.value = {
    id: 0,
    account_id: currentAccount.value?.id || 0,
    stock_code: applied.stock_code,
    stock_name: applied.stock_name,
    quantity: applied.quantity,
    cost_price: applied.price,
    accumulated_pnl: 0,
    current_price: applied.price,
    change: 0,
    percent: 0,
    market_value: applied.price * applied.quantity,
    cost_amount: applied.price * applied.quantity,
    unrealized_pnl: 0,
    unrealized_pnl_percent: 0,
    today_pnl: 0,
  }
  orderTradeType.value = 'buy'
  showOrderDialog.value = true
}

onMounted(() => {
  loadAccountsAndSummary()
})
</script>

<template>
  <div class="trade-portfolio-section">
    <!-- 资产全景汇总卡片 -->
    <TradePortfolioSummary :summary="summary" />

    <!-- 账户选项卡导航 -->
    <div class="account-bar">
      <AccountSelectorTabs
        :accounts="accounts"
        :selected-account-id="selectedAccountId"
        @select="handleSelectAccount"
        @create="openCreateAccount"
      />

      <div class="account-actions">
        <button type="button" class="tool-btn" :disabled="loading" @click="loadAccountsAndSummary">
          <RefreshCw :size="13" :class="{ 'is-spinning': loading }" />
          <span>刷新</span>
        </button>
        <button type="button" class="tool-btn" @click="showDrawer = true">
          <History :size="13" />
          <span>交割流水</span>
        </button>
      </div>
    </div>

    <!-- 选中账户专属资金工具栏 -->
    <div v-if="currentAccount" class="account-detail-strip">
      <div class="strip-cash">
        <span class="label">{{ currentAccount.name }} 可用现金</span>
        <strong class="cash-num">¥ {{ currentAccount.cash_balance.toFixed(2) }}</strong>
        <button
          type="button"
          class="cash-edit-btn"
          title="修改可用现金"
          @click="openEditAccount"
        >
          <Pencil :size="12" />
        </button>
        <span class="broker-tag">{{ currentAccount.broker }}</span>
        <span class="rate-tag">佣金 万{{ (currentAccount.commission_rate * 10000).toFixed(1) }} (保底¥{{ currentAccount.min_commission }})</span>
      </div>

      <div class="strip-btns">
        <button type="button" class="action-btn is-primary" @click="openNewOrder">
          <Plus :size="13" />
          <span>记账交易</span>
        </button>
        <button type="button" class="action-btn" @click="openCashFlow">
          <ArrowDownRight :size="13" />
          <span>银证转账</span>
        </button>
        <button type="button" class="action-btn" @click="openSimulate()">
          <Calculator :size="13" />
          <span>调仓试算</span>
        </button>
        <button type="button" class="action-icon-btn" title="账户设置" @click="openEditAccount">
          <Settings :size="13" />
        </button>
        <button type="button" class="action-icon-btn is-danger" title="删除账户" @click="handleDeleteCurrentAccount">
          <Trash2 :size="13" />
        </button>
      </div>
    </div>

    <!-- 持仓表格面板 -->
    <LiquidGlass :radius="20" :optics="panelOptics" class="portfolio-table-panel">
      <header class="table-panel-header">
        <div class="panel-title">
          <h3>{{ currentAccount ? currentAccount.name + ' · 持仓组合' : '全市场合并持仓组合' }}</h3>
          <small>{{ positions.length }} 只标的</small>
        </div>
        <button v-if="currentAccount" type="button" class="panel-add-btn" @click="openNewOrder">
          <Plus :size="13" />
          买入加仓
        </button>
      </header>

      <TradePositionTable
        :positions="positions"
        :loading="positionsLoading"
        @buy="handleBuyPosition"
        @sell="handleSellPosition"
        @simulate="openSimulate"
      />
    </LiquidGlass>

    <!-- 各功能弹窗 -->
    <AccountDialog
      :visible="showAccountDialog"
      :account="editingAccount"
      :submitting="accountSubmitting"
      @close="showAccountDialog = false"
      @save="handleSaveAccount"
    />

    <CashFlowDialog
      :visible="showCashFlowDialog"
      :account="currentAccount"
      :submitting="cashFlowSubmitting"
      @close="showCashFlowDialog = false"
      @save="handleSaveCashFlow"
    />

    <TradeOrderDialog
      :visible="showOrderDialog"
      :account="currentAccount || (accounts[0] ?? null)"
      :position="orderPosition"
      :preset-trade-type="orderTradeType"
      :submitting="orderSubmitting"
      @close="showOrderDialog = false"
      @save="handleSaveOrder"
    />

    <TradeSimulationDialog
      :visible="showSimDialog"
      :account="currentAccount || (accounts[0] ?? null)"
      :position="simPosition"
      @close="showSimDialog = false"
      @apply="handleApplySimToOrder"
    />

    <TradeOrdersDrawer
      :visible="showDrawer"
      :account-id="selectedAccountId"
      :account-name="currentAccount?.name"
      @close="showDrawer = false"
    />
  </div>
</template>

<style scoped>
.trade-portfolio-section {
  display: grid;
  gap: 16px;
}

.account-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.account-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  border-radius: 10px;
  border: 1px solid var(--ikaros-line);
  background: rgba(255, 255, 255, 0.4);
  color: var(--ikaros-muted);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.tool-btn:hover {
  color: var(--ikaros-ink);
}

.account-detail-strip {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 12px 18px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.45);
  border: 1px solid var(--ikaros-line);
  flex-wrap: wrap;
}

.strip-cash {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.strip-cash .label {
  font-size: 12px;
  color: var(--ikaros-muted);
}

.cash-num {
  font-size: 18px;
  color: var(--ikaros-ink);
  font-weight: 750;
}

.cash-edit-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  border: 1px solid var(--ikaros-line);
  background: rgba(255, 255, 255, 0.4);
  color: var(--ikaros-muted);
  cursor: pointer;
  transition: all 140ms ease;
}

.cash-edit-btn:hover {
  color: var(--ikaros-pink);
  border-color: var(--ikaros-pink);
}

.broker-tag,
.rate-tag {
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.04);
  color: var(--ikaros-muted);
}

.strip-btns {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 6px 12px;
  border-radius: 9px;
  border: 1px solid var(--ikaros-line);
  background: #fff;
  color: var(--ikaros-ink);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 140ms ease;
}

.action-btn.is-primary {
  background: var(--ikaros-pink);
  border-color: var(--ikaros-pink);
  color: #fff;
}

.action-icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  border: 1px solid var(--ikaros-line);
  background: transparent;
  color: var(--ikaros-muted);
  cursor: pointer;
}

.action-icon-btn:hover {
  color: var(--ikaros-ink);
}

.action-icon-btn.is-danger:hover {
  color: #dc2626;
  border-color: rgba(220, 38, 38, 0.3);
}

.portfolio-table-panel {
  overflow: hidden;
}

.table-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--ikaros-line);
}

.panel-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.panel-title h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--ikaros-ink);
}

.panel-title small {
  font-size: 11px;
  color: var(--ikaros-muted);
}

.panel-add-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 12px;
  border-radius: 8px;
  border: 1px solid var(--ikaros-pink);
  background: rgba(232, 93, 142, 0.08);
  color: var(--ikaros-pink);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.is-spinning {
  animation: spin 850ms linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
