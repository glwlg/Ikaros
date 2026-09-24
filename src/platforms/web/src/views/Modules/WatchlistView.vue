<script setup lang="ts">
import { ref } from 'vue'
import { Briefcase, Eye } from 'lucide-vue-next'
import TradePortfolioSection from '@/components/trade/TradePortfolioSection.vue'
import WatchlistSection from '@/components/watchlist/WatchlistSection.vue'

const activeTab = ref<'trade' | 'watchlist'>('trade')
</script>

<template>
  <div class="ikaros-page watchlist-page">
    <header class="ikaros-page-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Portfolio & Market</p>
        <h1 class="ikaros-page-title">股票自选与多账户资产</h1>
        <p class="ikaros-page-description">
          支持多券商账户资金隔离、买卖流水移动加权摊薄、调仓预演试算与全市场行情追踪。
        </p>
      </div>

      <div class="view-mode-toggle">
        <button
          type="button"
          class="mode-toggle-btn"
          :class="{ 'is-active': activeTab === 'trade' }"
          @click="activeTab = 'trade'"
        >
          <Briefcase :size="14" />
          <span>账户资产</span>
        </button>
        <button
          type="button"
          class="mode-toggle-btn"
          :class="{ 'is-active': activeTab === 'watchlist' }"
          @click="activeTab = 'watchlist'"
        >
          <Eye :size="14" />
          <span>自选标的</span>
        </button>
      </div>
    </header>

    <main class="view-content">
      <TradePortfolioSection v-if="activeTab === 'trade'" />
      <WatchlistSection v-else />
    </main>
  </div>
</template>

<style scoped>
.watchlist-page {
  display: grid;
  gap: 20px;
  padding-bottom: 40px;
}

.view-mode-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 255, 255, 0.45);
  padding: 4px;
  border-radius: 12px;
  border: 1px solid var(--ikaros-line);
}

.mode-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 8px;
  border: 0;
  background: transparent;
  color: var(--ikaros-muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 160ms ease;
}

.mode-toggle-btn:hover {
  color: var(--ikaros-ink);
}

.mode-toggle-btn.is-active {
  background: #fff;
  color: var(--ikaros-ink);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.05);
}

.view-content {
  min-width: 0;
}
</style>
