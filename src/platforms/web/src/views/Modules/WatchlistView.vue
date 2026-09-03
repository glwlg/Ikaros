<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import {
    ChartCandlestick,
    Loader2,
    Pencil,
    PiggyBank,
    Plus,
    RefreshCw,
    Trash2,
    TrendingDown,
    TrendingUp,
    Wallet,
} from 'lucide-vue-next'
import request from '@/api/request'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'

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

const compactOptics = {
    mapSize: 256,
    strength: 0.11,
    depth: 0.9,
    dispersion: 0.58,
    frost: 3,
    saturate: 1.26,
    specular: 1.25,
    glow: 0.3,
    sheen: 1.05,
    curvature: 0.48,
    bend: 0.7,
}

interface Stock {
    stock_code: string
    stock_name: string
    platform: string
    price: number
    change: number
    percent: number
    high: number
    low: number
    open: number
    yesterday_close: number
    position_quantity: number
    cost_price: number
}

interface StockForm {
    stock_code: string
    stock_name: string
    // number inputs may bind as string | number at runtime
    position_quantity: string | number
    cost_price: string | number
}

const emptyForm = (): StockForm => ({
    stock_code: '',
    stock_name: '',
    position_quantity: '',
    cost_price: '',
})

const stocks = ref<Stock[]>([])
const loading = ref(false)
const refreshing = ref(false)
const showDialog = ref(false)
const editingCode = ref<string | null>(null)
const formData = ref<StockForm>(emptyForm())

const loadData = async (isRefresh = false) => {
    if (isRefresh) {
        refreshing.value = true
    } else {
        loading.value = true
    }
    try {
        const res = await request('/watchlist', { method: 'GET' })
        stocks.value = res.data || []
    } catch (e) {
        console.error(e)
    } finally {
        loading.value = false
        refreshing.value = false
    }
}

const openCreate = () => {
    editingCode.value = null
    formData.value = emptyForm()
    showDialog.value = true
}

const closeDialog = () => {
    showDialog.value = false
    editingCode.value = null
    formData.value = emptyForm()
}

const openEdit = (stock: Stock) => {
    editingCode.value = stock.stock_code
    formData.value = {
        stock_code: stock.stock_code,
        stock_name: stock.stock_name,
        position_quantity: stock.position_quantity > 0 ? String(stock.position_quantity) : '',
        cost_price: stock.cost_price > 0 ? String(stock.cost_price) : '',
    }
    showDialog.value = true
}

const fieldText = (value: string | number | null | undefined) =>
    String(value ?? '').trim()

const handleSave = async () => {
    if (!formData.value.stock_code.trim() || !formData.value.stock_name.trim()) return
    // type="number" v-model can yield number after user edit; never call .trim() directly
    const quantityText = fieldText(formData.value.position_quantity)
    const costText = fieldText(formData.value.cost_price)
    if (Boolean(quantityText) !== Boolean(costText)) {
        alert('持仓数量和单位成本需要同时填写；两项都留空可清除持仓。')
        return
    }
    const quantity = quantityText ? Number(quantityText) : 0
    const costPrice = costText ? Number(costText) : 0
    if (
        !Number.isFinite(quantity)
        || !Number.isFinite(costPrice)
        || (Boolean(quantityText) && (quantity <= 0 || costPrice <= 0))
        || (quantity === 0) !== (costPrice === 0)
    ) {
        alert('持仓数量和单位成本必须同时为大于 0 的数字。')
        return
    }
    const payload = {
        stock_code: formData.value.stock_code.trim(),
        stock_name: formData.value.stock_name.trim(),
        position_quantity: quantity,
        // cost_price is average unit cost (单价), not total cost
        cost_price: costPrice,
    }
    try {
        if (editingCode.value) {
            await request(`/watchlist/${encodeURIComponent(editingCode.value)}`, {
                method: 'PUT',
                data: payload,
            })
        } else {
            await request('/watchlist', {
                method: 'POST',
                data: payload,
            })
        }
        closeDialog()
        loadData()
    } catch (e: any) {
        alert(e?.response?.data?.detail || '操作失败')
    }
}

const handleDelete = async (code: string) => {
    if (!confirm(`确定移除 ${code} 吗？`)) return
    try {
        await request(`/watchlist/${encodeURIComponent(code)}`, { method: 'DELETE' })
        loadData()
    } catch (e) {
        console.error(e)
    }
}

const priceColor = (change: number) => {
    if (change > 0) return 'is-up'
    if (change < 0) return 'is-down'
    return 'is-flat'
}

const formatPercent = (change: number, percent: number) => {
    const sign = change > 0 ? '+' : ''
    return `${sign}${percent.toFixed(2)}%`
}

const formatChange = (change: number) => {
    const sign = change > 0 ? '+' : ''
    return `${sign}${change.toFixed(2)}`
}

const hasPosition = (stock: Stock) => stock.position_quantity > 0 && stock.cost_price > 0
const dailyProfit = (stock: Stock) => stock.change * stock.position_quantity
const holdingProfit = (stock: Stock) => (stock.price - stock.cost_price) * stock.position_quantity
const holdingPercent = (stock: Stock) => stock.cost_price > 0
    ? (stock.price / stock.cost_price - 1) * 100
    : 0
const formatMoney = (value: number) => {
    const sign = value > 0 ? '+' : value < 0 ? '-' : ''
    return `${sign}¥${Math.abs(value).toFixed(2)}`
}
const formatCost = (value: number) => value.toFixed(4).replace(/0+$/, '').replace(/\.$/, '')
const profitColor = (value: number) => {
    if (value > 0) return 'is-up'
    if (value < 0) return 'is-down'
    return 'is-flat'
}

onMounted(() => {
    loadData()
})

const gainersCount = computed(() => stocks.value.filter((stock) => stock.change > 0).length)
const losersCount = computed(() => stocks.value.filter((stock) => stock.change < 0).length)
const positionedStocks = computed(() => stocks.value.filter(hasPosition))
const valuedPositions = computed(() => positionedStocks.value.filter((stock) => stock.price > 0))
const dailyProfitTotal = computed(() => valuedPositions.value.reduce((sum, stock) => sum + dailyProfit(stock), 0))
const holdingProfitTotal = computed(() => valuedPositions.value.reduce((sum, stock) => sum + holdingProfit(stock), 0))
</script>

<template>
  <div class="ikaros-page watchlist-page">
    <header class="ikaros-page-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Market</p>
        <h1 class="ikaros-page-title">市场追踪</h1>
        <p class="ikaros-page-description">
          跟踪自选股行情与持仓盈亏，盈亏按当前行情实时计算。
        </p>
      </div>
      <div class="watchlist-header-actions">
        <button type="button" class="ikaros-secondary-action" :disabled="refreshing" @click="loadData(true)">
          <RefreshCw :class="{ 'is-spinning': refreshing }" />
          刷新
        </button>
        <button type="button" class="ikaros-primary-action watchlist-add" @click="openCreate">
          <Plus />
          添加股票
        </button>
      </div>
    </header>

    <section class="watchlist-metrics" aria-label="持仓概览">
      <LiquidGlass :radius="20" :optics="compactOptics" class="watchlist-metric">
        <div class="watchlist-metric-inner">
          <span class="watchlist-metric-icon"><ChartCandlestick /></span>
          <div class="watchlist-metric-copy">
            <span>自选总数</span>
            <strong>{{ stocks.length }}</strong>
          </div>
        </div>
      </LiquidGlass>
      <LiquidGlass :radius="20" :optics="compactOptics" class="watchlist-metric">
        <div class="watchlist-metric-inner">
          <span class="watchlist-metric-icon is-up"><TrendingUp /></span>
          <div class="watchlist-metric-copy">
            <span>上涨</span>
            <strong class="is-up">{{ gainersCount }}</strong>
          </div>
        </div>
      </LiquidGlass>
      <LiquidGlass :radius="20" :optics="compactOptics" class="watchlist-metric">
        <div class="watchlist-metric-inner">
          <span class="watchlist-metric-icon is-down"><TrendingDown /></span>
          <div class="watchlist-metric-copy">
            <span>下跌</span>
            <strong class="is-down">{{ losersCount }}</strong>
          </div>
        </div>
      </LiquidGlass>
      <LiquidGlass :radius="20" :optics="compactOptics" class="watchlist-metric">
        <div class="watchlist-metric-inner">
          <span class="watchlist-metric-icon"><Wallet /></span>
          <div class="watchlist-metric-copy">
            <span>今日盈亏</span>
            <strong :class="profitColor(dailyProfitTotal)">
              {{ valuedPositions.length ? formatMoney(dailyProfitTotal) : '--' }}
            </strong>
          </div>
        </div>
      </LiquidGlass>
      <LiquidGlass :radius="20" :optics="compactOptics" class="watchlist-metric">
        <div class="watchlist-metric-inner">
          <span class="watchlist-metric-icon"><PiggyBank /></span>
          <div class="watchlist-metric-copy">
            <span>持仓盈亏</span>
            <strong :class="profitColor(holdingProfitTotal)">
              {{ valuedPositions.length ? formatMoney(holdingProfitTotal) : '--' }}
            </strong>
          </div>
        </div>
      </LiquidGlass>
    </section>

    <LiquidGlass :radius="22" :optics="panelOptics" class="watchlist-table-panel">
      <div class="watchlist-table-shell">
        <header class="watchlist-table-head">
          <div class="watchlist-table-title">
            <h2>自选持仓列表</h2>
            <p>价格、涨跌幅与持仓盈亏一览</p>
          </div>
          <span class="watchlist-count-chip">{{ stocks.length }} 项</span>
        </header>

        <div v-if="loading" class="watchlist-loading">
          <Loader2 class="is-spinning" />
          正在加载自选股
        </div>

        <div v-else-if="stocks.length === 0" class="watchlist-empty">
          <TrendingUp />
          <p>暂无自选股</p>
        </div>

        <div v-else class="watchlist-table-wrap">
          <table class="watchlist-table">
            <thead>
              <tr>
                <th>代码 / 名称</th>
                <th class="is-num">最新价</th>
                <th class="is-num">涨跌幅</th>
                <th class="is-num">持仓数量</th>
                <th class="is-num">单位成本</th>
                <th class="is-num">今日盈亏</th>
                <th class="is-num">持仓盈亏</th>
                <th class="is-actions">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="stock in stocks" :key="stock.stock_code">
                <td>
                  <div class="watchlist-stock">
                    <strong>{{ stock.stock_name }}</strong>
                    <div class="watchlist-stock-meta">
                      <span class="watchlist-platform">{{ stock.platform }}</span>
                      <span class="watchlist-code">{{ stock.stock_code }}</span>
                    </div>
                  </div>
                </td>
                <td class="is-num">
                  <span class="watchlist-price" :class="priceColor(stock.change)">
                    {{ stock.price ? stock.price.toFixed(2) : '--' }}
                  </span>
                </td>
                <td class="is-num">
                  <span v-if="stock.price" class="watchlist-change" :class="priceColor(stock.change)">
                    {{ formatChange(stock.change) }}（{{ formatPercent(stock.change, stock.percent) }}）
                  </span>
                  <span v-else class="is-flat">--</span>
                </td>
                <td class="is-num">
                  <span v-if="hasPosition(stock)">{{ stock.position_quantity }}</span>
                  <span v-else class="is-flat">--</span>
                </td>
                <td class="is-num">
                  <span v-if="hasPosition(stock)">¥{{ formatCost(stock.cost_price) }}</span>
                  <span v-else class="is-flat">--</span>
                </td>
                <td class="is-num">
                  <span v-if="hasPosition(stock) && stock.price > 0" :class="profitColor(dailyProfit(stock))">
                    {{ formatMoney(dailyProfit(stock)) }}
                  </span>
                  <span v-else class="is-flat">--</span>
                </td>
                <td class="is-num">
                  <span v-if="hasPosition(stock) && stock.price > 0" :class="profitColor(holdingProfit(stock))">
                    {{ formatMoney(holdingProfit(stock)) }}（{{ holdingPercent(stock).toFixed(2) }}%）
                  </span>
                  <span v-else class="is-flat">--</span>
                </td>
                <td class="is-actions">
                  <div class="watchlist-row-actions">
                    <button type="button" title="编辑" @click="openEdit(stock)">
                      <Pencil />
                    </button>
                    <button type="button" class="is-danger" title="移除" @click="handleDelete(stock.stock_code)">
                      <Trash2 />
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </LiquidGlass>

    <div v-if="showDialog" class="watchlist-dialog-layer">
      <div class="ikaros-surface ikaros-surface-strong watchlist-dialog">
        <header class="watchlist-dialog-head">
          <h2>{{ editingCode ? '编辑自选股' : '添加自选股' }}</h2>
        </header>
        <div class="watchlist-dialog-body">
          <label class="watchlist-field">
            <span>股票代码</span>
            <input
              v-model="formData.stock_code"
              type="text"
              :disabled="!!editingCode"
              placeholder="例如: sh600519"
            >
          </label>
          <label class="watchlist-field">
            <span>股票名称</span>
            <input
              v-model="formData.stock_name"
              type="text"
              placeholder="例如: 贵州茅台"
            >
          </label>
          <div class="watchlist-field-pair">
            <label class="watchlist-field">
              <span>持仓数量</span>
              <input
                v-model="formData.position_quantity"
                type="number"
                min="0"
                step="any"
                inputmode="decimal"
                placeholder="例如: 100"
              >
            </label>
            <label class="watchlist-field">
              <span>单位成本（单价）</span>
              <input
                v-model="formData.cost_price"
                type="number"
                min="0"
                step="any"
                inputmode="decimal"
                placeholder="例如: 7.025"
              >
            </label>
          </div>
          <p class="watchlist-dialog-hint">
            单位成本为每股/每份均价，不是总成本。两项同时留空可清除持仓；盈亏按当前行情实时计算。
          </p>
        </div>
        <footer class="watchlist-dialog-foot">
          <button type="button" class="watchlist-dialog-cancel" @click="closeDialog">取消</button>
          <button type="button" class="ikaros-primary-action watchlist-dialog-save" @click="handleSave">保存</button>
        </footer>
      </div>
    </div>
  </div>
</template>

<style scoped>
.watchlist-page {
  gap: 20px;
}

.watchlist-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.watchlist-header-actions svg {
  width: 15px;
  height: 15px;
}

.watchlist-add {
  border: 0;
  cursor: pointer;
}

.watchlist-metrics {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.watchlist-metric {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.8);
}

:global(.dark) .watchlist-metric {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.82);
}

.watchlist-metric-inner {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 15px 17px;
}

.watchlist-metric-icon {
  display: grid;
  width: 38px;
  height: 38px;
  flex: none;
  place-items: center;
  border: 1px solid rgba(232, 93, 142, 0.2);
  border-radius: 13px;
  background: rgba(232, 93, 142, 0.09);
  color: var(--ikaros-pink);
}

.watchlist-metric-icon.is-up {
  border-color: rgba(220, 38, 38, 0.18);
  background: rgba(220, 38, 38, 0.07);
  color: #dc2626;
}

.watchlist-metric-icon.is-down {
  border-color: rgba(22, 163, 74, 0.18);
  background: rgba(22, 163, 74, 0.07);
  color: #16a34a;
}

.watchlist-metric-icon svg {
  width: 18px;
  height: 18px;
}

.watchlist-metric-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.watchlist-metric-copy span {
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
}

.watchlist-metric-copy strong {
  color: var(--ikaros-ink);
  font-size: 20px;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.watchlist-metric-copy strong.is-up,
.is-up {
  color: #dc2626;
}

.watchlist-metric-copy strong.is-down,
.is-down {
  color: #16a34a;
}

.is-flat {
  color: var(--ikaros-muted);
}

.watchlist-table-panel {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .watchlist-table-panel {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.86);
}

.watchlist-table-shell {
  display: grid;
  gap: 16px;
  padding: 20px;
}

.watchlist-table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.watchlist-table-title h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.watchlist-table-title p {
  margin: 3px 0 0;
  color: var(--ikaros-muted);
  font-size: 11px;
}

.watchlist-count-chip {
  flex: none;
  padding: 5px 10px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: var(--panel-muted);
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 700;
}

.watchlist-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 2px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.watchlist-loading svg {
  width: 16px;
  height: 16px;
}

.watchlist-empty {
  display: flex;
  min-height: 220px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border: 1px dashed var(--ikaros-line);
  border-radius: 18px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.watchlist-empty svg {
  width: 26px;
  height: 26px;
}

.watchlist-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--ikaros-line);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.32);
}

:global(.dark) .watchlist-table-wrap {
  background: rgba(255, 255, 255, 0.03);
}

.watchlist-table {
  width: 100%;
  min-width: 880px;
  font-size: 13px;
}

.watchlist-table thead {
  background: rgba(255, 255, 255, 0.38);
}

:global(.dark) .watchlist-table thead {
  background: rgba(255, 255, 255, 0.045);
}

.watchlist-table th {
  padding: 11px 16px;
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0.06em;
  text-align: left;
  white-space: nowrap;
}

.watchlist-table th.is-num {
  text-align: right;
}

.watchlist-table th.is-actions {
  text-align: center;
}

.watchlist-table td {
  padding: 13px 16px;
  border-top: 1px solid var(--ikaros-line);
  color: var(--ikaros-ink);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  white-space: nowrap;
}

.watchlist-table td:first-child {
  font-family: inherit;
  font-size: 13px;
}

.watchlist-table td.is-num {
  text-align: right;
}

.watchlist-table td.is-actions {
  text-align: center;
}

.watchlist-table tbody tr {
  transition: background-color 160ms ease;
}

.watchlist-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.3);
}

:global(.dark) .watchlist-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.03);
}

.watchlist-stock {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.watchlist-stock strong {
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 750;
}

.watchlist-stock-meta {
  display: flex;
  align-items: center;
  gap: 7px;
}

.watchlist-platform {
  padding: 2px 6px;
  border: 1px solid var(--ikaros-line);
  border-radius: 6px;
  background: var(--panel-muted);
  color: var(--ikaros-muted);
  font-size: 9px;
  font-weight: 750;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.watchlist-code {
  color: var(--ikaros-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
}

.watchlist-price {
  font-size: 13px;
  font-weight: 750;
}

.watchlist-change {
  display: inline-flex;
  align-items: center;
  padding: 4px 8px;
  border-radius: 8px;
  font-weight: 750;
}

.watchlist-change.is-up {
  background: rgba(220, 38, 38, 0.08);
}

.watchlist-change.is-down {
  background: rgba(22, 163, 74, 0.08);
}

.watchlist-row-actions {
  display: inline-flex;
  gap: 7px;
}

.watchlist-row-actions button {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border: 1px solid var(--ikaros-line);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.45);
  color: var(--ikaros-copy);
  transition: border-color 160ms ease, color 160ms ease, background-color 160ms ease;
}

:global(.dark) .watchlist-row-actions button {
  background: rgba(255, 255, 255, 0.05);
}

.watchlist-row-actions button:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.watchlist-row-actions button.is-danger:hover {
  border-color: rgba(198, 55, 65, 0.3);
  background: rgba(198, 55, 65, 0.07);
  color: #c63741;
}

.watchlist-row-actions svg {
  width: 14px;
  height: 14px;
}

.watchlist-dialog-layer {
  position: fixed;
  z-index: 60;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(23, 19, 26, 0.32);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}

.watchlist-dialog {
  width: min(480px, 100%);
  overflow: hidden;
}

.watchlist-dialog-head {
  padding: 18px 22px;
  border-bottom: 1px solid var(--ikaros-line);
}

.watchlist-dialog-head h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.watchlist-dialog-body {
  display: grid;
  gap: 14px;
  padding: 20px 22px;
}

.watchlist-field {
  display: grid;
  gap: 7px;
}

.watchlist-field span {
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 700;
}

.watchlist-field input {
  width: 100%;
  padding: 10px 13px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.55);
  color: var(--ikaros-ink);
  font-size: 13px;
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease, background-color 160ms ease;
}

:global(.dark) .watchlist-field input {
  background: rgba(255, 255, 255, 0.06);
}

.watchlist-field input:focus {
  border-color: rgba(232, 93, 142, 0.45);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.12);
}

:global(.dark) .watchlist-field input:focus {
  background: rgba(255, 255, 255, 0.09);
}

.watchlist-field input:disabled {
  opacity: 0.55;
}

.watchlist-field-pair {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.watchlist-dialog-hint {
  margin: 0;
  color: var(--ikaros-muted);
  font-size: 11px;
  line-height: 1.6;
}

.watchlist-dialog-foot {
  display: flex;
  gap: 10px;
  padding: 16px 22px;
  border-top: 1px solid var(--ikaros-line);
}

.watchlist-dialog-cancel {
  flex: 1;
  min-height: 40px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.45);
  color: var(--ikaros-copy);
  font-size: 13px;
  font-weight: 700;
}

:global(.dark) .watchlist-dialog-cancel {
  background: rgba(255, 255, 255, 0.06);
}

.watchlist-dialog-cancel:hover {
  border-color: rgba(232, 93, 142, 0.3);
  color: var(--ikaros-pink);
}

.watchlist-dialog-save {
  flex: 1;
  border: 0;
  cursor: pointer;
}

.is-spinning {
  animation: watchlist-spin 850ms linear infinite;
}

@keyframes watchlist-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (min-width: 900px) {
  .watchlist-metrics {
    grid-template-columns: repeat(5, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .watchlist-field-pair {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning {
    animation: none;
  }
}
</style>
