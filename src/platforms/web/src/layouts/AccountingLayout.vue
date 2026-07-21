<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, RouterView, RouterLink } from 'vue-router'
import { Home, Wallet, BarChart3, Grid2x2, UserCircle, ArrowLeft } from 'lucide-vue-next'
import AccountingDialogHost from '@/components/accounting/AccountingDialogHost.vue'

const route = useRoute()

const tabs = [
    { path: '/accounting/overview', label: '首页', icon: Home },
    { path: '/accounting/assets', label: '资产', icon: Wallet },
    { path: '/accounting/stats', label: '统计', icon: BarChart3 },
    { path: '/accounting/more', label: '更多', icon: Grid2x2 },
    { path: '/accounting/profile', label: '我的', icon: UserCircle },
]

const isActiveTab = (path: string) => {
    if (path === '/accounting/overview') {
        return route.path === path || route.path === '/accounting'
    }
    return route.path === path || route.path.startsWith(`${path}/`)
}

const isPWA = typeof window !== 'undefined' &&
    (window.matchMedia('(display-mode: standalone)').matches || ('standalone' in navigator && (navigator as any).standalone))

// Hide layout chrome on sub-pages with own headers
const isSubPage = computed(() => [
    'BalanceTrendDetail',
    'AccountDetail',
    'RecordList',
    'RecordDetail',
    'StatsAmountDetail',
    'StatsCategoryDetail',
    'StatsTrendDetail',
    'StatsTeamDetail',
    'StatsPanelManage',
    'StatsPanelEdit',
    'BudgetList',
    'DebtList',
    'ScheduledTaskList',
    'ProfileManage',
    'ProfileSettings',
].includes(route.name as string))
</script>

<template>
  <div class="accounting-shell">
    <div
      v-if="!isSubPage"
      class="accounting-header safe-top safe-x"
    >
      <RouterLink
        v-if="!isPWA"
        to="/home"
        class="accounting-back-link"
      >
        <ArrowLeft class="w-4 h-4" />
        <span>返回</span>
      </RouterLink>
      <span class="text-white font-semibold tracking-wide">智能记账</span>
    </div>

    <div class="accounting-main accounting-scroll">
      <RouterView />
    </div>

    <nav
      v-if="!isSubPage"
      class="accounting-tabbar safe-x"
      aria-label="记账主导航"
    >
      <RouterLink
        v-for="tab in tabs"
        :key="tab.path"
        :to="tab.path"
        class="accounting-tab"
        :class="{ 'is-active': isActiveTab(tab.path) }"
      >
        <component :is="tab.icon" class="w-5 h-5" />
        <span class="accounting-tab-label">{{ tab.label }}</span>
        <div
          v-if="isActiveTab(tab.path)"
          class="accounting-tab-indicator"
        />
      </RouterLink>
    </nav>

    <AccountingDialogHost />
  </div>
</template>

<style scoped>
.accounting-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
  height: 100dvh;
  max-height: 100dvh;
  overflow: hidden;
  background: linear-gradient(
    180deg,
    color-mix(in srgb, var(--color-primary-500) 6%, var(--color-bg-primary)) 0%,
    var(--color-bg-primary) 100%
  );
}

.accounting-header {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 48px;
  padding: 10px 16px;
  background: linear-gradient(135deg, var(--color-primary-600), var(--color-primary-500));
  box-shadow: var(--shadow-sm);
  flex-shrink: 0;
}

.accounting-back-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 36px;
  padding: 4px 8px 4px 2px;
  color: rgba(255, 255, 255, 0.92);
  font-size: 14px;
  font-weight: 500;
  border-radius: 10px;
  transition: background 0.15s ease, color 0.15s ease;
}

.accounting-back-link:active {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
}

.accounting-main {
  flex: 1;
  min-height: 0;
  overflow: auto;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior-y: contain;
}

.accounting-tabbar {
  position: sticky;
  bottom: 0;
  z-index: 20;
  display: flex;
  flex-shrink: 0;
  border-top: 1px solid var(--color-border-secondary);
  background: color-mix(in srgb, var(--color-bg-elevated) 92%, transparent);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.06);
  padding-bottom: env(safe-area-inset-bottom, 0px);
}

.accounting-tab {
  position: relative;
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  min-height: 52px;
  padding: 8px 0 10px;
  color: var(--color-text-muted);
  transition: color 0.15s ease;
  -webkit-tap-highlight-color: transparent;
  user-select: none;
}

.accounting-tab:active {
  opacity: 0.75;
}

.accounting-tab.is-active {
  color: var(--color-accounting-brand);
}

.accounting-tab-label {
  font-size: 10px;
  font-weight: 600;
  line-height: 1.2;
}

.accounting-tab-indicator {
  position: absolute;
  bottom: 0;
  width: 28px;
  height: 2px;
  border-radius: 999px;
  background: var(--color-accounting-brand);
}
</style>
