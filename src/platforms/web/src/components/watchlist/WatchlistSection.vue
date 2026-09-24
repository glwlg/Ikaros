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

const fieldText = (value: string | number | null | undefined) => String(value ?? '').trim()

const handleSave = async () => {
  if (!formData.value.stock_code.trim() || !formData.value.stock_name.trim()) return
  const quantityText = fieldText(formData.value.position_quantity)
  const costText = fieldText(formData.value.cost_price)
  if (Boolean(quantityText) !== Boolean(costText)) {
    alert('持仓数量和单位成本需要同时填写；两项都留空可清除持仓。')
    return
  }
  const quantity = quantityText ? Number(quantityText) : 0
  const costPrice = costText ? Number(costText) : 0
  if (
    !Number.isFinite(quantity) ||
    !Number.isFinite(costPrice) ||
    (Boolean(quantityText) && (quantity <= 0 || costPrice <= 0)) ||
    (quantity === 0) !== (costPrice === 0)
  ) {
    alert('持仓数量和单位成本必须同时为大于 0 的数字。')
    return
  }
  const payload = {
    stock_code: formData.value.stock_code.trim(),
    stock_name: formData.value.stock_name.trim(),
    position_quantity: quantity,
    cost_price: costPrice,
  }
  try {
    if (editingCode.value) {
      await request('/watchlist/' + encodeURIComponent(editingCode.value), {
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
  } catch (e) {
    console.error(e)
  }
}

const handleDelete = async (code: string) => {
  if (!confirm('确定移除 ' + code + ' 吗？')) return
  try {
    await request('/watchlist/' + encodeURIComponent(code), { method: 'DELETE' })
    loadData()
  } catch (e) {
    console.error(e)
  }
}

const gainersCount = computed(() => stocks.value.filter((s) => s.change > 0).length)
const losersCount = computed(() => stocks.value.filter((s) => s.change < 0).length)
const valuedPositions = computed(() =>
  stocks.value.filter((s) => s.position_quantity > 0 && s.cost_price > 0 && s.price > 0)
)
const dailyProfitTotal = computed(() =>
  valuedPositions.value.reduce((acc, s) => acc + s.position_quantity * s.change, 0)
)
const holdingProfitTotal = computed(() =>
  valuedPositions.value.reduce((acc, s) => acc + s.position_quantity * (s.price - s.cost_price), 0)
)

const formatMoney = (val: number) =>
  new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(val)

const profitColor = (val: number) => {
  if (val > 0) return 'is-up'
  if (val < 0) return 'is-down'
  return ''
}
const priceColor = (change: number) => {
  if (change > 0) return 'is-up'
  if (change < 0) return 'is-down'
  return ''
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="watchlist-section">
    <section class="watchlist-metrics" aria-label="自选概览">
      <LiquidGlass :radius="18" :optics="compactOptics" class="watchlist-metric">
        <div class="watchlist-metric-inner">
          <span class="watchlist-metric-icon"><ChartCandlestick /></span>
          <div class="watchlist-metric-copy">
            <span>自选总数</span>
            <strong>{{ stocks.length }}</strong>
          </div>
        </div>
      </LiquidGlass>
      <LiquidGlass :radius="18" :optics="compactOptics" class="watchlist-metric">
        <div class="watchlist-metric-inner">
          <span class="watchlist-metric-icon is-up"><TrendingUp /></span>
          <div class="watchlist-metric-copy">
            <span>上涨</span>
            <strong class="is-up">{{ gainersCount }}</strong>
          </div>
        </div>
      </LiquidGlass>
      <LiquidGlass :radius="18" :optics="compactOptics" class="watchlist-metric">
        <div class="watchlist-metric-inner">
          <span class="watchlist-metric-icon is-down"><TrendingDown /></span>
          <div class="watchlist-metric-copy">
            <span>下跌</span>
            <strong class="is-down">{{ losersCount }}</strong>
          </div>
        </div>
      </LiquidGlass>
      <LiquidGlass :radius="18" :optics="compactOptics" class="watchlist-metric">
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
      <LiquidGlass :radius="18" :optics="compactOptics" class="watchlist-metric">
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

    <LiquidGlass :radius="20" :optics="panelOptics" class="watchlist-table-panel">
      <div class="watchlist-table-shell">
        <header class="watchlist-table-head">
          <div class="watchlist-table-title">
            <h2>自选标的列表</h2>
            <p>全市场自选观察与实时行情</p>
          </div>
          <div class="head-ops">
            <button type="button" class="ikaros-secondary-action" :disabled="refreshing" @click="loadData(true)">
              <RefreshCw :size="13" :class="{ 'is-spinning': refreshing }" />
              刷新
            </button>
            <button type="button" class="ikaros-primary-action" @click="openCreate">
              <Plus :size="13" />
              添加标的
            </button>
          </div>
        </header>

        <div v-if="loading" class="watchlist-loading">
          <Loader2 class="is-spinning" />
          正在加载自选标的
        </div>

        <div v-else-if="stocks.length === 0" class="watchlist-empty">
          <TrendingUp />
          <p>暂无自选标的</p>
        </div>

        <div v-else class="watchlist-table-wrap">
          <table class="watchlist-table">
            <thead>
              <tr>
                <th>代码 / 名称</th>
                <th class="is-num">最新价</th>
                <th class="is-num">涨跌额</th>
                <th class="is-num">涨跌幅</th>
                <th class="is-num">最高</th>
                <th class="is-num">最低</th>
                <th class="is-num">持仓</th>
                <th class="is-num">成本价</th>
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
                  <span :class="priceColor(stock.change)">
                    {{ stock.change > 0 ? '+' : '' }}{{ stock.change ? stock.change.toFixed(2) : '0.00' }}
                  </span>
                </td>
                <td class="is-num">
                  <span class="watchlist-change" :class="priceColor(stock.percent)">
                    {{ stock.percent > 0 ? '+' : '' }}{{ stock.percent ? stock.percent.toFixed(2) : '0.00' }}%
                  </span>
                </td>
                <td class="is-num">{{ stock.high ? stock.high.toFixed(2) : '--' }}</td>
                <td class="is-num">{{ stock.low ? stock.low.toFixed(2) : '--' }}</td>
                <td class="is-num">{{ stock.position_quantity > 0 ? stock.position_quantity : '--' }}</td>
                <td class="is-num">{{ stock.cost_price > 0 ? stock.cost_price.toFixed(2) : '--' }}</td>
                <td class="is-num">
                  <span
                    v-if="stock.position_quantity > 0 && stock.cost_price > 0 && stock.price > 0"
                    :class="priceColor(stock.price - stock.cost_price)"
                  >
                    {{ formatMoney(stock.position_quantity * (stock.price - stock.cost_price)) }}
                  </span>
                  <span v-else>--</span>
                </td>
                <td class="is-actions">
                  <div class="watchlist-row-actions">
                    <button type="button" title="编辑" @click="openEdit(stock)"><Pencil /></button>
                    <button type="button" class="is-danger" title="删除" @click="handleDelete(stock.stock_code)"><Trash2 /></button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </LiquidGlass>

    <!-- 编辑/添加弹窗 -->
    <div v-if="showDialog" class="watchlist-dialog-layer" @click.self="closeDialog">
      <LiquidGlass :radius="22" :optics="panelOptics" class="watchlist-dialog">
        <div class="watchlist-dialog-head">
          <h2>{{ editingCode ? '编辑自选标的' : '添加自选标的' }}</h2>
        </div>
        <form class="watchlist-dialog-body" @submit.prevent="handleSave">
          <label class="watchlist-field">
            <span>股票代码</span>
            <input v-model="formData.stock_code" placeholder="如 sh600519、sz000001" :disabled="!!editingCode" />
          </label>
          <label class="watchlist-field">
            <span>股票名称</span>
            <input v-model="formData.stock_name" placeholder="如 贵州茅台" />
          </label>
          <div class="watchlist-field-pair">
            <label class="watchlist-field">
              <span>持仓数量 (股)</span>
              <input v-model="formData.position_quantity" type="number" step="any" placeholder="选填" />
            </label>
            <label class="watchlist-field">
              <span>单位成本 (元)</span>
              <input v-model="formData.cost_price" type="number" step="any" placeholder="选填" />
            </label>
          </div>
          <footer class="watchlist-dialog-foot">
            <button type="button" class="watchlist-dialog-cancel" @click="closeDialog">取消</button>
            <button type="submit" class="ikaros-primary-action watchlist-dialog-save">保存</button>
          </footer>
        </form>
      </LiquidGlass>
    </div>
  </div>
</template>

<style scoped>
.watchlist-section {
  display: grid;
  gap: 16px;
}

.watchlist-metrics {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}

.watchlist-metric-inner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
}

.watchlist-metric-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.4);
  color: var(--ikaros-ink);
}

.watchlist-metric-icon.is-up {
  color: #dc2626;
  background: rgba(220, 38, 38, 0.1);
}

.watchlist-metric-icon.is-down {
  color: #16a34a;
  background: rgba(22, 163, 74, 0.1);
}

.watchlist-metric-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.watchlist-metric-copy span {
  font-size: 11px;
  color: var(--ikaros-muted);
}

.watchlist-metric-copy strong {
  font-size: 16px;
  color: var(--ikaros-ink);
}

.watchlist-metric-copy strong.is-up {
  color: #dc2626;
}

.watchlist-metric-copy strong.is-down {
  color: #16a34a;
}

.watchlist-table-panel {
  overflow: hidden;
}

.watchlist-table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid var(--ikaros-line);
}

.watchlist-table-title h2 {
  margin: 0;
  font-size: 15px;
  font-weight: 700;
  color: var(--ikaros-ink);
}

.watchlist-table-title p {
  margin: 2px 0 0 0;
  font-size: 11px;
  color: var(--ikaros-muted);
}

.head-ops {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.watchlist-table-wrap {
  overflow-x: auto;
}

.watchlist-table {
  width: 100%;
  min-width: 860px;
  font-size: 13px;
  border-collapse: collapse;
}

.watchlist-table th {
  padding: 10px 14px;
  font-size: 11px;
  font-weight: 600;
  color: var(--ikaros-muted);
  text-align: left;
  border-bottom: 1px solid var(--ikaros-line);
  white-space: nowrap;
}

.watchlist-table td {
  padding: 12px 14px;
  border-bottom: 1px solid var(--ikaros-line);
  color: var(--ikaros-ink);
  white-space: nowrap;
}

.watchlist-table th.is-num,
.watchlist-table td.is-num {
  text-align: right;
}

.watchlist-table th.is-actions,
.watchlist-table td.is-actions {
  text-align: center;
}

.watchlist-stock {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.watchlist-stock strong {
  font-size: 13px;
  font-weight: 700;
}

.watchlist-stock-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}

.watchlist-platform {
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 4px;
  background: rgba(0, 0, 0, 0.05);
  color: var(--ikaros-muted);
}

.watchlist-code {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  color: var(--ikaros-muted);
}

.watchlist-change {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 6px;
  font-weight: 700;
}

.watchlist-change.is-up {
  background: rgba(220, 38, 38, 0.08);
  color: #dc2626;
}

.watchlist-change.is-down {
  background: rgba(22, 163, 74, 0.08);
  color: #16a34a;
}

.watchlist-row-actions {
  display: inline-flex;
  gap: 6px;
}

.watchlist-row-actions button {
  padding: 4px 6px;
  border-radius: 6px;
  border: 1px solid var(--ikaros-line);
  background: transparent;
  color: var(--ikaros-muted);
  cursor: pointer;
}

.watchlist-row-actions button:hover {
  color: var(--ikaros-ink);
}

.watchlist-row-actions button.is-danger:hover {
  color: #dc2626;
  border-color: rgba(220, 38, 38, 0.3);
}

.watchlist-dialog-layer {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 16px;
  background: rgba(15, 23, 42, 0.4);
  backdrop-filter: blur(6px);
}

.watchlist-dialog {
  width: min(460px, 100%);
  overflow: hidden;
}

.watchlist-dialog-head {
  padding: 16px 20px;
  border-bottom: 1px solid var(--ikaros-line);
}

.watchlist-dialog-head h2 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
  color: var(--ikaros-ink);
}

.watchlist-dialog-body {
  display: grid;
  gap: 12px;
  padding: 18px 20px;
}

.watchlist-field {
  display: grid;
  gap: 6px;
}

.watchlist-field span {
  font-size: 11px;
  font-weight: 600;
  color: var(--ikaros-muted);
}

.watchlist-field input {
  padding: 9px 12px;
  border-radius: 10px;
  border: 1px solid var(--ikaros-line);
  background: rgba(255, 255, 255, 0.5);
  font-size: 13px;
  color: var(--ikaros-ink);
  outline: none;
}

.watchlist-field-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.watchlist-dialog-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--ikaros-line);
}

.watchlist-dialog-cancel {
  padding: 8px 16px;
  border-radius: 10px;
  border: 1px solid var(--ikaros-line);
  background: transparent;
  color: var(--ikaros-muted);
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
