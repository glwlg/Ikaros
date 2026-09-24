<script setup lang="ts">
import { Wallet, TrendingUp, TrendingDown, PiggyBank, PieChart, Coins } from 'lucide-vue-next'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import type { PortfolioSummary } from '@/api/trade'

const props = defineProps<{
  summary: PortfolioSummary | null
}>()

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

const formatMoney = (val: number | undefined) => {
  if (val === undefined || isNaN(val)) return '--'
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(val)
}

const pnlClass = (val: number | undefined) => {
  if (!val || val === 0) return ''
  return val > 0 ? 'is-up' : 'is-down'
}
</script>

<template>
  <section class="trade-summary-grid" aria-label="资产全景概览">
    <LiquidGlass :radius="18" :optics="compactOptics" class="summary-card">
      <div class="summary-card-inner">
        <span class="card-icon"><Wallet /></span>
        <div class="card-text">
          <span class="label">总资产</span>
          <strong class="value primary">{{ formatMoney(props.summary?.total_assets) }}</strong>
        </div>
      </div>
    </LiquidGlass>

    <LiquidGlass :radius="18" :optics="compactOptics" class="summary-card">
      <div class="summary-card-inner">
        <span class="card-icon"><Coins /></span>
        <div class="card-text">
          <span class="label">可用现金</span>
          <strong class="value">{{ formatMoney(props.summary?.total_cash) }}</strong>
        </div>
      </div>
    </LiquidGlass>

    <LiquidGlass :radius="18" :optics="compactOptics" class="summary-card">
      <div class="summary-card-inner">
        <span class="card-icon"><PieChart /></span>
        <div class="card-text">
          <span class="label">持仓市值 ({{ props.summary?.position_ratio_percent ?? 0 }}%)</span>
          <strong class="value">{{ formatMoney(props.summary?.total_market_value) }}</strong>
        </div>
      </div>
    </LiquidGlass>

    <LiquidGlass :radius="18" :optics="compactOptics" class="summary-card">
      <div class="summary-card-inner">
        <span class="card-icon" :class="pnlClass(props.summary?.total_today_pnl)">
          <TrendingUp v-if="(props.summary?.total_today_pnl ?? 0) >= 0" />
          <TrendingDown v-else />
        </span>
        <div class="card-text">
          <span class="label">当日盈亏</span>
          <strong class="value" :class="pnlClass(props.summary?.total_today_pnl)">
            {{ (props.summary?.total_today_pnl ?? 0) > 0 ? '+' : '' }}{{ formatMoney(props.summary?.total_today_pnl) }}
          </strong>
        </div>
      </div>
    </LiquidGlass>

    <LiquidGlass :radius="18" :optics="compactOptics" class="summary-card">
      <div class="summary-card-inner">
        <span class="card-icon" :class="pnlClass(props.summary?.total_unrealized_pnl)"><PiggyBank /></span>
        <div class="card-text">
          <span class="label">累计持仓浮盈</span>
          <strong class="value" :class="pnlClass(props.summary?.total_unrealized_pnl)">
            {{ (props.summary?.total_unrealized_pnl ?? 0) > 0 ? '+' : '' }}{{ formatMoney(props.summary?.total_unrealized_pnl) }}
          </strong>
        </div>
      </div>
    </LiquidGlass>
  </section>
</template>

<style scoped>
.trade-summary-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}

.summary-card {
  min-height: 76px;
}

.summary-card-inner {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 18px;
  box-sizing: border-box;
}

.card-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.4);
  color: var(--ikaros-ink);
  flex-shrink: 0;
}

.card-icon.is-up {
  color: #dc2626;
  background: rgba(220, 38, 38, 0.1);
}

.card-icon.is-down {
  color: #16a34a;
  background: rgba(22, 163, 74, 0.1);
}

.card-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.label {
  font-size: 11px;
  color: var(--ikaros-muted);
  margin-bottom: 2px;
  white-space: nowrap;
}

.value {
  font-size: 16px;
  font-weight: 700;
  color: var(--ikaros-ink);
  white-space: nowrap;
}

.value.primary {
  color: var(--ikaros-pink, #e85d8e);
}

.value.is-up {
  color: #dc2626;
}

.value.is-down {
  color: #16a34a;
}
</style>
