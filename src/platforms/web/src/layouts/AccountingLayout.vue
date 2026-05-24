<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, RouterView, RouterLink } from 'vue-router'
import { Home, Wallet, BarChart3, Grid2x2, UserCircle, ArrowLeft } from 'lucide-vue-next'

const route = useRoute()

const tabs = [
    { path: '/accounting/overview', label: '首页', icon: Home },
    { path: '/accounting/assets', label: '资产', icon: Wallet },
    { path: '/accounting/stats', label: '统计', icon: BarChart3 },
    { path: '/accounting/more', label: '更多', icon: Grid2x2 },
    { path: '/accounting/profile', label: '我的', icon: UserCircle },
]

const isActiveTab = (path: string) => route.path === path

const isPWA = typeof window !== 'undefined' && 
    (window.matchMedia('(display-mode: standalone)').matches || ('standalone' in navigator && (navigator as any).standalone))

// Hide layout chrome on sub-pages with own headers
const isSubPage = computed(() => [
    'BalanceTrendDetail',
    'AccountDetail',
    'RecordList',
    'RecordDetail',
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
      class="accounting-header"
    >
      <RouterLink
        v-if="!isPWA"
        to="/home"
        class="flex items-center gap-1.5 text-white/90 hover:text-white transition text-sm font-medium"
      >
        <ArrowLeft class="w-4 h-4" />
        <span>返回</span>
      </RouterLink>
      <span class="text-white font-semibold">智能记账</span>
    </div>

    <div class="flex-1 overflow-auto">
      <RouterView />
    </div>

    <nav
      v-if="!isSubPage"
      class="accounting-tabbar"
    >
      <RouterLink
        v-for="tab in tabs"
        :key="tab.path"
        :to="tab.path"
        class="accounting-tab"
        :class="{ 'is-active': isActiveTab(tab.path) }"
      >
        <component :is="tab.icon" class="w-5 h-5" />
        <span class="text-[10px] font-medium">{{ tab.label }}</span>
        <div
          v-if="isActiveTab(tab.path)"
          class="accounting-tab-indicator"
        />
      </RouterLink>
    </nav>
  </div>
</template>

<style scoped>
.accounting-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
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
  padding: 12px 16px;
  background: linear-gradient(135deg, var(--color-primary-600), var(--color-primary-500));
  box-shadow: var(--shadow-sm);
}

.accounting-tabbar {
  position: sticky;
  bottom: 0;
  z-index: 20;
  display: flex;
  border-top: 1px solid var(--color-border-secondary);
  background: var(--color-bg-elevated);
  box-shadow: 0 -2px 10px rgba(0, 0, 0, 0.05);
}

.accounting-tab {
  position: relative;
  display: flex;
  flex: 1;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 0;
  color: var(--color-text-muted);
  transition: color 0.15s ease;
}

.accounting-tab:hover,
.accounting-tab.is-active {
  color: var(--color-primary-600);
}

.accounting-tab-indicator {
  position: absolute;
  bottom: 0;
  width: 32px;
  height: 2px;
  border-radius: 999px;
  background: var(--color-primary-600);
}
</style>
