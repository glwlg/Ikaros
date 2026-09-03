<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch, type Component } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import {
    Activity,
    Cable,
    Cctv,
    ChevronRight,
    ChevronsLeft,
    Cloud,
    Gauge,
    HeartPulse,
    KeyRound,
    LayoutDashboard,
    Link2,
    LogOut,
    Menu,
    MessageSquareText,
    Moon,
    Plus,
    Puzzle,
    Radio,
    Search,
    Settings2,
    ShieldCheck,
    ShieldUser,
    Sun,
    X,
    Zap,
} from 'lucide-vue-next'

import AuroraBackdrop from '@/components/layout/AuroraBackdrop.vue'
import IkarosMark from '@/components/layout/IkarosMark.vue'
import { LiquidGlass } from '@/components/liquid-glass'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'

interface NavigationItem {
    label: string
    description: string
    to: string
    icon: Component
}

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const themeStore = useThemeStore()
const searchInput = ref<HTMLInputElement | null>(null)
const isMobile = ref(false)
const sidebarOpen = ref(false)
const sidebarCollapsed = ref(false)
const commandOpen = ref(false)
const commandQuery = ref('')

const workspaceNav = computed<NavigationItem[]>(() => [
    { label: '系统概览', description: '运行状态与待办', to: '/home', icon: LayoutDashboard },
    { label: '对话工作台', description: '会话与任务协作', to: '/chat', icon: MessageSquareText },
    { label: '定时任务', description: '调度与推送', to: '/modules/scheduler', icon: Cable },
    { label: '心跳监控', description: '周期巡检清单', to: '/modules/monitor', icon: HeartPulse },
    { label: '实时监控', description: '摄像头与实时画面', to: '/modules/cameras', icon: Cctv },
    { label: '市场追踪', description: '自选行情', to: '/modules/watchlist', icon: Activity },
    { label: 'RSS 订阅', description: '信息源同步', to: '/modules/rss', icon: Radio },
    { label: '续费订阅', description: '到期与续费提醒', to: '/modules/subscriptions', icon: Zap },
])

const managementNav = computed<NavigationItem[]>(() => {
    const items: NavigationItem[] = [
        { label: '渠道绑定', description: '用户渠道账号', to: '/bindings', icon: Link2 },
        { label: '凭据管理', description: '密钥与授权', to: '/credentials', icon: KeyRound },
    ]
    if (authStore.isAdmin) {
        items.push(
            { label: '模型路由', description: '供应商与模型策略', to: '/admin/models', icon: Settings2 },
            { label: '渠道权限', description: '渠道用户能力', to: '/admin/channel-access', icon: ShieldCheck },
            { label: '运行配置', description: '运行时与渠道开关', to: '/admin/runtime', icon: Zap },
            { label: '阿里云流量', description: 'CDT 免费额度', to: '/admin/aliyun-traffic', icon: Cloud },
        )
    }
    if (authStore.isOperator) {
        items.push(
            { label: '用户与权限', description: '后台账号角色', to: '/admin/users', icon: ShieldUser },
            { label: '技能管理', description: '技能安装与开关', to: '/admin/skills', icon: Puzzle },
            { label: '诊断中心', description: '运行质量与故障', to: '/admin/diagnostics', icon: Gauge },
        )
    }
    return items
})

const allNavigation = computed(() => [...workspaceNav.value, ...managementNav.value])
const commandResults = computed(() => {
    const query = commandQuery.value.trim().toLocaleLowerCase('zh-CN')
    if (!query) return allNavigation.value
    return allNavigation.value.filter((item) => (
        `${item.label} ${item.description} ${item.to}`.toLocaleLowerCase('zh-CN').includes(query)
    ))
})

const identityName = computed(() => (
    authStore.user?.display_name
    || authStore.user?.username
    || authStore.user?.email
    || '管理员'
))
const identityEmail = computed(() => authStore.user?.email || '')
const identityInitial = computed(() => identityName.value.trim().charAt(0).toUpperCase() || 'I')
const identityRole = computed(() => (
    authStore.isAdmin ? '系统管理员' : authStore.isOperator ? '运营人员' : '观察者'
))
const currentTitle = computed(() => String(route.meta.title || '系统概览'))
const currentSection = computed(() => route.path.startsWith('/admin') ? '管理中心' : '核心')

const isNavActive = (to: string) => route.path === to || route.path.startsWith(`${to}/`)

const checkViewport = () => {
    isMobile.value = window.innerWidth <= 1024
    if (!isMobile.value) sidebarOpen.value = true
    if (isMobile.value) sidebarCollapsed.value = false
}

const toggleSidebar = () => {
    if (isMobile.value) sidebarOpen.value = !sidebarOpen.value
    else sidebarCollapsed.value = !sidebarCollapsed.value
}

const openCommand = async () => {
    commandOpen.value = true
    commandQuery.value = ''
    await nextTick()
    searchInput.value?.focus()
}

const closeCommand = () => {
    commandOpen.value = false
    commandQuery.value = ''
}

const selectCommand = async (item: NavigationItem) => {
    closeCommand()
    await router.push(item.to)
}

const onGlobalKeydown = (event: KeyboardEvent) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        if (commandOpen.value) closeCommand()
        else openCommand()
        return
    }
    if (event.key === 'Escape') {
        closeCommand()
        if (isMobile.value) sidebarOpen.value = false
    }
}

const handleLogout = async () => {
    await authStore.logout()
    await router.push('/login')
}

watch(() => route.fullPath, () => {
    closeCommand()
    if (isMobile.value) sidebarOpen.value = false
})

onMounted(() => {
    checkViewport()
    window.addEventListener('resize', checkViewport)
    window.addEventListener('keydown', onGlobalKeydown)
})

onUnmounted(() => {
    window.removeEventListener('resize', checkViewport)
    window.removeEventListener('keydown', onGlobalKeydown)
})
</script>

<template>
  <div class="ikaros-shell" :class="{ 'is-sidebar-collapsed': sidebarCollapsed }">
    <AuroraBackdrop />

    <button
      v-if="isMobile && sidebarOpen"
      type="button"
      class="ikaros-sidebar-scrim"
      aria-label="关闭导航"
      @click="sidebarOpen = false"
    />

    <aside class="ikaros-sidebar" :class="{ 'is-open': sidebarOpen, 'is-collapsed': sidebarCollapsed }">
      <div class="ikaros-brand-row">
        <RouterLink to="/home" class="ikaros-brand" aria-label="返回系统概览">
          <IkarosMark :size="36" />
          <span class="ikaros-brand-copy">
            <strong>IKAROS</strong>
            <small>AGENT OPERATIONS</small>
          </span>
        </RouterLink>
        <button
          type="button"
          class="ikaros-sidebar-toggle"
          :aria-label="sidebarCollapsed ? '展开导航' : '收起导航'"
          :title="sidebarCollapsed ? '展开导航' : '收起导航'"
          @click="toggleSidebar"
        >
          <ChevronsLeft />
        </button>
      </div>

      <nav class="ikaros-navigation" aria-label="主导航">
        <section class="ikaros-nav-group">
          <h2>工作空间</h2>
          <RouterLink
            v-for="item in workspaceNav"
            :key="item.to"
            :to="item.to"
            class="ikaros-nav-item"
            :class="{ 'is-active': isNavActive(item.to) }"
            :title="sidebarCollapsed ? item.label : undefined"
          >
            <component :is="item.icon" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </section>

        <section class="ikaros-nav-group">
          <h2>管理中心</h2>
          <RouterLink
            v-for="item in managementNav"
            :key="item.to"
            :to="item.to"
            class="ikaros-nav-item"
            :class="{ 'is-active': isNavActive(item.to) }"
            :title="sidebarCollapsed ? item.label : undefined"
          >
            <component :is="item.icon" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </section>
      </nav>

      <div class="ikaros-sidebar-footer">
        <div class="ikaros-user-card">
          <span class="ikaros-user-avatar">{{ identityInitial }}</span>
          <span class="ikaros-user-copy">
            <strong>{{ identityName }}</strong>
            <small>{{ identityRole }}</small>
          </span>
          <button type="button" title="退出登录" aria-label="退出登录" @click="handleLogout">
            <LogOut />
          </button>
        </div>
      </div>
    </aside>

    <section class="ikaros-main-shell">
      <header class="ikaros-topbar">
        <div class="ikaros-topbar-left">
          <button type="button" class="ikaros-mobile-menu" aria-label="打开导航" @click="toggleSidebar">
            <X v-if="sidebarOpen" />
            <Menu v-else />
          </button>
          <div class="ikaros-breadcrumb" aria-label="当前位置">
            <span>{{ currentSection }}</span>
            <ChevronRight />
            <strong>{{ currentTitle }}</strong>
          </div>
          <button type="button" class="ikaros-command-trigger" @click="openCommand">
            <Search />
            <span>搜索页面或命令</span>
            <kbd>⌘K</kbd>
          </button>
        </div>

        <div class="ikaros-topbar-actions">
          <RouterLink to="/chat" class="ikaros-create-button">
            <Plus />
            <span>新建会话</span>
          </RouterLink>
          <button
            type="button"
            class="ikaros-topbar-button"
            :aria-label="themeStore.isDark ? '切换浅色模式' : '切换深色模式'"
            :title="themeStore.isDark ? '切换浅色模式' : '切换深色模式'"
            @click="themeStore.toggleTheme()"
          >
            <Sun v-if="themeStore.isDark" />
            <Moon v-else />
          </button>
          <div class="ikaros-topbar-profile" :title="identityEmail || identityName">
            {{ identityInitial }}
          </div>
        </div>
      </header>

      <main class="ikaros-main-scroll">
        <div class="ikaros-view-slot">
          <RouterView />
        </div>
      </main>
    </section>

    <div v-if="commandOpen" class="ikaros-command-layer" @click.self="closeCommand">
      <LiquidGlass
        class="ikaros-command-panel"
        :radius="18"
        :optics="{
          strength: 0.1,
          depth: 0.8,
          dispersion: 0.5,
          frost: 3.5,
          specular: 1.2,
          glow: 0.26,
          sheen: 0.9,
          curvature: 0.44,
          bend: 0.68,
          brightness: 0.1,
        }"
      >
        <div class="ikaros-command-search">
          <Search />
          <input
            ref="searchInput"
            v-model="commandQuery"
            type="search"
            placeholder="输入页面名称，例如“心跳监控”"
            aria-label="搜索页面"
          >
          <button type="button" aria-label="关闭搜索" @click="closeCommand"><X /></button>
        </div>
        <div class="ikaros-command-results">
          <button
            v-for="item in commandResults"
            :key="item.to"
            type="button"
            class="ikaros-command-result"
            @click="selectCommand(item)"
          >
            <span class="ikaros-command-icon"><component :is="item.icon" /></span>
            <span>
              <strong>{{ item.label }}</strong>
              <small>{{ item.description }}</small>
            </span>
            <ChevronRight />
          </button>
          <p v-if="!commandResults.length" class="ikaros-command-empty">没有匹配的页面</p>
        </div>
      </LiquidGlass>
    </div>
  </div>
</template>
