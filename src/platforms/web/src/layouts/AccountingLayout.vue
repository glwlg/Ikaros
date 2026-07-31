<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, RouterView, RouterLink } from 'vue-router'
import { Home, Wallet, BarChart3, Grid2x2, UserCircle, Bell, Menu } from 'lucide-vue-next'
import AccountingDialogHost from '@/components/accounting/AccountingDialogHost.vue'
import AccountingToastHost from '@/components/accounting/AccountingToastHost.vue'

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

const isEditableField = (target: EventTarget | null) => {
    if (target instanceof HTMLTextAreaElement) return true
    if (!(target instanceof HTMLInputElement)) return false
    return !['button', 'checkbox', 'color', 'file', 'hidden', 'image', 'radio', 'range', 'reset', 'submit'].includes(target.type)
}

const isIOSStandalone = () => {
    const userAgent = navigator.userAgent
    const isIOS = /iPad|iPhone|iPod/.test(userAgent)
        || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
    return isIOS && isPWA
}

let observedViewport: VisualViewport | null = null
let viewportFrame: number | undefined
let viewportWasReduced = false

const resetDocumentScroll = () => {
    document.scrollingElement?.scrollTo(0, 0)
    document.documentElement.scrollTop = 0
    document.body.scrollTop = 0
    window.scrollTo(0, 0)
}

const stopViewportRecovery = () => {
    if (viewportFrame !== undefined) {
        window.cancelAnimationFrame(viewportFrame)
        viewportFrame = undefined
    }
    observedViewport?.removeEventListener('resize', recoverViewportAfterKeyboard)
    observedViewport?.removeEventListener('scroll', recoverViewportAfterKeyboard)
    observedViewport = null
    viewportWasReduced = false
}

const recoverViewportAfterKeyboard = () => {
    if (viewportFrame !== undefined) window.cancelAnimationFrame(viewportFrame)
    viewportFrame = window.requestAnimationFrame(() => {
        viewportFrame = undefined
        const viewport = observedViewport
        if (!viewport) return

        const rootHeight = document.documentElement.getBoundingClientRect().height
        if (viewport.height < rootHeight - 1) {
            viewportWasReduced = true
            return
        }
        if (!viewportWasReduced) return

        resetDocumentScroll()
        stopViewportRecovery()
    })
}

const armViewportRecovery = (event: FocusEvent) => {
    if (!isEditableField(event.target)) return

    stopViewportRecovery()
    const viewport = window.visualViewport
    if (!viewport) return

    observedViewport = viewport
    viewport.addEventListener('resize', recoverViewportAfterKeyboard)
    viewport.addEventListener('scroll', recoverViewportAfterKeyboard)
}

onMounted(() => {
    if (!isIOSStandalone()) return
    document.addEventListener('focusin', armViewportRecovery, true)
})

onBeforeUnmount(() => {
    document.removeEventListener('focusin', armViewportRecovery, true)
    stopViewportRecovery()
})

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
      class="accounting-header"
    >
      <RouterLink to="/home" class="accounting-header-icon" aria-label="返回主应用">
        <Menu class="w-5 h-5" />
      </RouterLink>
      <span class="accounting-header-title">智能记账</span>
      <span class="accounting-header-icon accounting-header-bell" aria-hidden="true">
        <Bell class="w-5 h-5" />
      </span>
    </div>

    <div class="accounting-main accounting-scroll">
      <RouterView />
    </div>

    <nav
      v-if="!isSubPage"
      class="accounting-tabbar"
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
    <AccountingToastHost />
  </div>
</template>

<style scoped>
.accounting-shell {
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
  background: transparent;
}

.accounting-header {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 12px;
  min-height: 64px;
  padding-top: calc(12px + env(safe-area-inset-top, 0px));
  padding-right: max(20px, env(safe-area-inset-right, 0px));
  padding-bottom: 12px;
  padding-left: max(20px, env(safe-area-inset-left, 0px));
  background: transparent;
  box-shadow: none;
  flex-shrink: 0;
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
  background: color-mix(in srgb, var(--color-bg-elevated) 94%, #ffe9d8);
  box-shadow: 0 -8px 24px rgba(111, 66, 38, 0.08);
  padding-right: env(safe-area-inset-right, 0px);
  padding-bottom: env(safe-area-inset-bottom, 0px);
  padding-left: env(safe-area-inset-left, 0px);
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
