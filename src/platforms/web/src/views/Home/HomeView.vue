<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import {
    Activity,
    AlertTriangle,
    ArrowRight,
    CalendarClock,
    CheckCircle2,
    ChevronDown,
    CircleDashed,
    Clock3,
    HeartPulse,
    KeyRound,
    MessageSquareText,
    RefreshCw,
    Route,
    ShieldCheck,
    Sparkles,
    Waypoints,
} from 'lucide-vue-next'

import { getAdminAudit, getDiagnostics } from '@/api/admin'
import request from '@/api/request'
import { getSkills } from '@/api/skills'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import { useAuthStore } from '@/stores/auth'

type DashboardRecord = Record<string, any>
type AttentionTone = 'warning' | 'danger'

interface AttentionItem {
    id: string
    title: string
    detail: string
    to: string
    action: string
    tone: AttentionTone
    lines: string[]
}

const authStore = useAuthStore()
const loading = ref(false)
const healthStatus = ref<'loading' | 'ok' | 'error'>('loading')
const diagnosticsStatus = ref<'idle' | 'loading' | 'ok' | 'forbidden' | 'error'>('idle')
const diagnostics = ref<DashboardRecord | null>(null)
const auditItems = ref<DashboardRecord[]>([])
const schedulerTasks = ref<DashboardRecord[]>([])
const schedulerError = ref('')
const skills = ref<DashboardRecord[]>([])
const skillsError = ref('')
const watchlistCount = ref<number | null>(null)
const watchlistError = ref('')
const lastUpdatedAt = ref<Date | null>(null)
const expandedAttention = ref<Set<string>>(new Set())

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

const roleLabel = computed(() => {
    if (authStore.isAdmin) return '管理员'
    if (authStore.isOperator) return '运营员'
    return '观察者'
})

const greeting = computed(() => {
    const hour = new Date().getHours()
    if (hour < 6) return '夜深了'
    if (hour < 12) return '早上好'
    if (hour < 18) return '下午好'
    return '晚上好'
})

const displayName = computed(
    () => authStore.user?.username || authStore.user?.email?.split('@')[0] || roleLabel.value,
)

const platformsMap = computed(() => {
    const root = diagnostics.value || {}
    return (root.platforms || root.runtime_config?.platforms || {}) as Record<string, boolean>
})

const platformEntries = computed(() =>
    Object.entries(platformsMap.value).map(([name, enabled]) => ({
        name,
        enabled: Boolean(enabled),
        configured: Boolean(diagnostics.value?.platform_env?.[name]?.configured),
    })),
)
const enabledPlatforms = computed(() => platformEntries.value.filter((item) => item.enabled))
const configuredPlatforms = computed(() =>
    enabledPlatforms.value.filter((item) => item.configured),
)
const enabledMissingConfig = computed(() =>
    enabledPlatforms.value.filter((item) => !item.configured),
)

const quality = computed(() => diagnostics.value?.runtime_v2_quality || null)
const statusCounts = computed(() => quality.value?.status_counts || {})
const turnSucceeded = computed(() => Number(statusCounts.value.succeeded || 0))
const turnFailed = computed(() => Number(statusCounts.value.failed || 0))
const turnWaiting = computed(() =>
    Number(statusCounts.value.waiting_external || 0)
    + Number(statusCounts.value.waiting_user || 0),
)
const terminalTurns = computed(() => turnSucceeded.value + turnFailed.value)
const recentSuccessRate = computed(() =>
    terminalTurns.value > 0
        ? Math.round((turnSucceeded.value / terminalTurns.value) * 1000) / 10
        : null,
)
const deliveryFailed = computed(() => Number(quality.value?.artifact_delivery_failed || 0))
const recentFailures = computed(() => {
    const turns = Array.isArray(quality.value?.recent_failed_turns)
        ? quality.value.recent_failed_turns
        : []
    const deliveries = Array.isArray(quality.value?.recent_delivery_failures)
        ? quality.value.recent_delivery_failures
        : []
    return { turns: turns.slice(0, 3), deliveries: deliveries.slice(0, 3) }
})

const activeTasks = computed(() => schedulerTasks.value.filter((task) => task.is_active !== false))
const pausedTasks = computed(() => schedulerTasks.value.filter((task) => task.is_active === false))
const tradingDayTasks = computed(
    () => activeTasks.value.filter((task) => task.run_calendar === 'trading_days').length,
)
const enabledSkills = computed(() => skills.value.filter((skill) => skill.enabled !== false).length)

const systemTone = computed<'neutral' | 'good' | 'warning' | 'danger'>(() => {
    if (healthStatus.value === 'loading' || loading.value) return 'neutral'
    if (healthStatus.value === 'error') return 'danger'
    if (turnFailed.value > 0 || deliveryFailed.value > 0 || enabledMissingConfig.value.length) {
        return 'warning'
    }
    return 'good'
})

const systemStatusText = computed(() => {
    if (healthStatus.value === 'loading' || loading.value) return '检查中'
    if (healthStatus.value === 'error') return '连接异常'
    if (systemTone.value === 'warning') return '需要关注'
    if (diagnosticsStatus.value === 'forbidden') return '基础正常'
    return '运行正常'
})

const channelProgress = computed(() => {
    if (!enabledPlatforms.value.length) return 0
    return Math.round((configuredPlatforms.value.length / enabledPlatforms.value.length) * 100)
})

const lastUpdatedText = computed(() => {
    if (!lastUpdatedAt.value) return '尚未更新'
    return lastUpdatedAt.value.toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    })
})

const headerFacts = computed(() => {
    const facts = [roleLabel.value]
    if (!skillsError.value && skills.value.length) facts.push(`${enabledSkills.value} 个技能已启用`)
    if (!watchlistError.value && watchlistCount.value !== null) {
        facts.push(`${watchlistCount.value} 个自选标的`)
    }
    return facts.join(' · ')
})

const metricCards = computed(() => [
    {
        key: 'health',
        label: '系统状态',
        value: systemStatusText.value,
        detail: healthStatus.value === 'ok'
            ? diagnosticsStatus.value === 'forbidden'
                ? 'API 健康检查已通过'
                : `${turnWaiting.value} 个任务正在等待`
            : healthStatus.value === 'loading'
                ? '正在检查控制台连接'
                : 'API 健康检查未通过',
        tone: systemTone.value,
        to: authStore.isOperator ? '/admin/diagnostics' : '/chat',
        icon: HeartPulse,
        progress: null,
    },
    {
        key: 'channels',
        label: '渠道连接',
        value: diagnostics.value ? `${configuredPlatforms.value.length}/${enabledPlatforms.value.length}` : '—',
        detail: diagnostics.value
            ? enabledMissingConfig.value.length
                ? `${enabledMissingConfig.value.length} 个启用渠道缺少凭据`
                : enabledPlatforms.value.length
                    ? enabledPlatforms.value.map((platform) => platform.name).join(' · ')
                    : '当前没有启用的消息渠道'
            : diagnosticsStatus.value === 'forbidden'
                ? '当前账号无诊断权限'
                : '渠道状态尚未获取',
        tone: enabledMissingConfig.value.length ? 'warning' : enabledPlatforms.value.length ? 'good' : 'neutral',
        to: authStore.isAdmin ? '/admin/runtime' : '/bindings',
        icon: Waypoints,
        progress: diagnostics.value ? channelProgress.value : null,
    },
    {
        key: 'tasks',
        label: '活跃任务',
        value: schedulerError.value ? '—' : String(activeTasks.value.length),
        detail: schedulerError.value
            ? schedulerError.value
            : `${pausedTasks.value.length} 个已暂停 · ${tradingDayTasks.value} 个仅交易日`,
        tone: schedulerError.value ? 'warning' : activeTasks.value.length ? 'good' : 'neutral',
        to: '/modules/scheduler',
        icon: CalendarClock,
        progress: null,
    },
    {
        key: 'success',
        label: '近期成功率',
        value: recentSuccessRate.value === null ? '—' : `${recentSuccessRate.value}%`,
        detail: diagnostics.value
            ? `${turnSucceeded.value} 次成功 · ${turnFailed.value} 次失败`
            : diagnosticsStatus.value === 'forbidden'
                ? '当前账号无运行质量权限'
                : '运行质量尚未获取',
        tone: recentSuccessRate.value === null
            ? 'neutral'
            : turnFailed.value > 0
                ? 'warning'
                : 'good',
        to: authStore.isOperator ? '/admin/diagnostics' : '/chat',
        icon: Activity,
        progress: recentSuccessRate.value,
    },
])

const formatAuditTime = (value: unknown) => {
    const raw = String(value || '').trim()
    if (!raw) return '—'
    const date = new Date(raw)
    if (Number.isNaN(date.getTime())) return raw
    return date.toLocaleString('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    })
}

const previewText = (value: unknown, limit = 72) => {
    const text = String(value || '').replace(/\s+/g, ' ').trim()
    if (text.length <= limit) return text || '—'
    return `${text.slice(0, limit).trimEnd()}...`
}

const attentionItems = computed<AttentionItem[]>(() => {
    const items: AttentionItem[] = []

    if (healthStatus.value === 'error') {
        items.push({
            id: 'health',
            title: '控制台无法连接 API',
            detail: '健康检查未通过，部分操作可能暂时不可用。',
            to: authStore.isOperator ? '/admin/diagnostics' : '/chat',
            action: '检查',
            tone: 'danger',
            lines: ['请检查后端服务和反向代理状态。'],
        })
    }

    for (const platform of enabledMissingConfig.value) {
        items.push({
            id: `platform-${platform.name}`,
            title: `${platform.name} 缺少连接凭据`,
            detail: '渠道已启用，但当前还不能收发消息。',
            to: '/admin/runtime',
            action: '配置',
            tone: 'warning',
            lines: [`补齐 ${platform.name} 的 Token 或凭据后即可建立连接。`],
        })
    }

    if (deliveryFailed.value > 0) {
        const lines = recentFailures.value.deliveries.map((item: any) => {
            const target = item.target || item.platform || '未知渠道'
            const file = item.artifact_filename ? ` · ${item.artifact_filename}` : ''
            return `${target}${file} · ${item.error || '投递失败'}`
        })
        items.push({
            id: 'delivery',
            title: `${deliveryFailed.value} 次消息或文件投递失败`,
            detail: lines[0] ? previewText(lines[0], 90) : '近期有内容未能送达目标渠道。',
            to: '/admin/diagnostics#delivery-failures',
            action: '诊断',
            tone: 'danger',
            lines: lines.length ? lines : ['打开诊断中心查看失败记录。'],
        })
    }

    for (const [index, turn] of recentFailures.value.turns.entries()) {
        const session = String(turn.session_id || '')
        const isScheduler = session.startsWith('scheduler-task-')
        const taskId = isScheduler ? session.replace('scheduler-task-', '') : ''
        items.push({
            id: `turn-${turn.turn_id || index}`,
            title: isScheduler ? `定时任务 #${taskId || '?'} 执行失败` : '任务执行失败',
            detail: previewText(turn.error || session, 90),
            to: '/admin/diagnostics#failed-turns',
            action: '查看',
            tone: 'danger',
            lines: [
                `错误：${turn.error || '未知错误'}`,
                `会话：${session || '—'}`,
                `运行编号：${turn.turn_id || '—'}`,
            ],
        })
    }

    if (schedulerError.value) {
        items.push({
            id: 'scheduler-load',
            title: '定时任务暂时无法加载',
            detail: schedulerError.value,
            to: '/bindings',
            action: '处理',
            tone: 'warning',
            lines: ['请确认当前账号已完成消息渠道绑定。'],
        })
    }

    if (watchlistError.value) {
        items.push({
            id: 'watchlist-load',
            title: '自选列表暂时无法加载',
            detail: watchlistError.value,
            to: '/bindings',
            action: '处理',
            tone: 'warning',
            lines: ['请确认当前账号已完成消息渠道绑定。'],
        })
    }

    if (skillsError.value) {
        items.push({
            id: 'skills-load',
            title: '技能状态暂时无法加载',
            detail: skillsError.value,
            to: authStore.isOperator ? '/admin/skills' : '/chat',
            action: '查看',
            tone: 'warning',
            lines: ['稍后刷新页面，或前往技能管理查看状态。'],
        })
    }

    return items.slice(0, 5)
})

const isAttentionOpen = (id: string) => expandedAttention.value.has(id)
const toggleAttention = (id: string) => {
    const next = new Set(expandedAttention.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    expandedAttention.value = next
}

const quickActions = computed(() => [
    {
        title: '新建会话',
        detail: '开始一次新的对话',
        to: '/chat',
        icon: MessageSquareText,
    },
    {
        title: '创建定时任务',
        detail: '安排自动执行与推送',
        to: '/modules/scheduler',
        icon: CalendarClock,
    },
    {
        title: '管理凭据',
        detail: '维护服务访问密钥',
        to: '/credentials',
        icon: KeyRound,
    },
    authStore.isOperator
        ? {
            title: '查看诊断报告',
            detail: '检查运行质量与异常',
            to: '/admin/diagnostics',
            icon: ShieldCheck,
        }
        : {
            title: '管理渠道绑定',
            detail: '连接你的消息账号',
            to: '/bindings',
            icon: Route,
        },
])

const upcomingTasks = computed(() =>
    activeTasks.value
        .slice()
        .sort((a, b) => Number(a.id || 0) - Number(b.id || 0))
        .slice(0, 4)
        .map((task) => ({
            id: task.id,
            crontab: String(task.crontab || '—'),
            calendar: task.run_calendar === 'trading_days'
                ? '仅交易日'
                : task.run_calendar === 'weekdays'
                    ? '仅工作日'
                    : '每天',
            instruction: previewText(task.instruction, 54),
            channel: task.chat_id
                ? `${task.platform || 'telegram'}:${task.chat_id}`
                : '默认推送渠道',
        })),
)

const recentActivities = computed(() =>
    auditItems.value.slice(0, 5).map((item) => ({
        title: String(item.action || '配置变更'),
        detail: previewText(item.summary || item.target || item.actor || '无摘要', 54),
        time: formatAuditTime(item.ts),
        ok: String(item.status || '').toLowerCase() === 'success',
    })),
)

const loadDashboard = async () => {
    loading.value = true
    healthStatus.value = 'loading'
    diagnosticsStatus.value = authStore.isOperator ? 'loading' : 'forbidden'
    schedulerError.value = ''
    skillsError.value = ''
    watchlistError.value = ''

    const healthPromise = request.get('/health')
        .then(() => { healthStatus.value = 'ok' })
        .catch(() => { healthStatus.value = 'error' })

    const schedulerPromise = request.get('/scheduler')
        .then((response) => { schedulerTasks.value = response.data || [] })
        .catch((error: any) => {
            schedulerTasks.value = []
            const detail = error?.response?.data?.detail
            schedulerError.value = typeof detail === 'string'
                ? detail
                : error?.response?.status === 400
                    ? '需要先绑定平台账号'
                    : '加载失败'
        })

    const skillsPromise = authStore.isOperator
        ? getSkills()
            .then((response) => { skills.value = response.data?.skills || response.data || [] })
            .catch(() => {
                skills.value = []
                skillsError.value = '加载失败'
            })
        : Promise.resolve().then(() => {
            skills.value = []
        })

    const watchlistPromise = request.get('/watchlist')
        .then((response) => {
            watchlistCount.value = Array.isArray(response.data) ? response.data.length : 0
        })
        .catch((error: any) => {
            watchlistCount.value = null
            const detail = error?.response?.data?.detail
            watchlistError.value = typeof detail === 'string'
                ? detail
                : error?.response?.status === 400
                    ? '需要先绑定平台账号'
                    : '加载失败'
        })

    const adminPromise = authStore.isOperator
        ? Promise.all([getDiagnostics(), getAdminAudit()])
            .then(([diagnosticsResponse, auditResponse]) => {
                diagnostics.value = diagnosticsResponse.data
                auditItems.value = auditResponse.data.items || []
                diagnosticsStatus.value = 'ok'
            })
            .catch((error: any) => {
                diagnostics.value = null
                auditItems.value = []
                diagnosticsStatus.value = error?.response?.status === 403 ? 'forbidden' : 'error'
            })
        : Promise.resolve().then(() => {
            diagnostics.value = null
            auditItems.value = []
        })

    await Promise.all([
        healthPromise,
        schedulerPromise,
        skillsPromise,
        watchlistPromise,
        adminPromise,
    ])
    lastUpdatedAt.value = new Date()
    loading.value = false
}

onMounted(loadDashboard)
</script>

<template>
  <div class="ikaros-page home-cockpit">
    <header class="home-header">
      <div class="home-heading">
        <p class="ikaros-page-kicker">Motion Cockpit</p>
        <h1 class="ikaros-page-title">{{ greeting }}，{{ displayName }}</h1>
        <p class="home-summary">{{ headerFacts }}</p>
      </div>

      <div class="home-header-actions">
        <span class="home-health" :class="`is-${systemTone}`">
          <span class="home-health-dot" />
          {{ systemStatusText }}
        </span>
        <button type="button" class="home-refresh" :disabled="loading" @click="loadDashboard">
          <RefreshCw :class="{ 'is-spinning': loading }" />
          <span>{{ lastUpdatedText }}</span>
        </button>
      </div>
    </header>

    <section class="metric-grid" aria-label="运行概览">
      <RouterLink
        v-for="card in metricCards"
        :key="card.key"
        :to="card.to"
        class="metric-link"
      >
        <LiquidGlass
          :radius="24"
          :optics="compactOptics"
          interactive
          class="metric-card"
          :class="[`is-${card.tone}`, { 'is-featured': card.key === 'health' }]"
        >
          <div class="metric-card-inner">
            <div class="metric-label">
              <span class="metric-icon"><component :is="card.icon" /></span>
              <span>{{ card.label }}</span>
              <span v-if="card.key === 'health'" class="metric-state">{{ systemStatusText }}</span>
            </div>

            <div class="metric-content">
              <div>
                <strong class="metric-value">{{ card.value }}</strong>
                <p class="metric-detail">{{ card.detail }}</p>
              </div>
              <span v-if="card.key === 'health'" class="pulse-orbit" aria-hidden="true">
                <span />
              </span>
            </div>

            <div v-if="card.progress !== null" class="metric-progress" aria-hidden="true">
              <span :style="{ width: `${Math.max(0, Math.min(100, card.progress))}%` }" />
            </div>
          </div>
        </LiquidGlass>
      </RouterLink>
    </section>

    <section class="home-bento">
      <LiquidGlass :radius="26" :optics="panelOptics" class="home-panel attention-panel">
        <div class="panel-shell">
          <header class="panel-header">
            <div>
              <span class="panel-title-icon is-warning"><AlertTriangle /></span>
              <div>
                <h2>需要关注</h2>
                <p>渠道配置、任务执行与内容投递</p>
              </div>
            </div>
            <RouterLink v-if="authStore.isOperator" to="/admin/diagnostics" class="panel-link">
              查看全部
              <ArrowRight />
            </RouterLink>
          </header>

          <div v-if="attentionItems.length" class="attention-list">
            <article
              v-for="item in attentionItems"
              :key="item.id"
              class="attention-item"
              :class="`is-${item.tone}`"
            >
              <button type="button" class="attention-toggle" @click="toggleAttention(item.id)">
                <span class="attention-symbol"><AlertTriangle /></span>
                <span class="attention-copy">
                  <strong>{{ item.title }}</strong>
                  <small>{{ item.detail }}</small>
                </span>
                <span class="attention-action">{{ item.action }}</span>
                <ChevronDown :class="{ 'is-open': isAttentionOpen(item.id) }" />
              </button>
              <div v-if="isAttentionOpen(item.id)" class="attention-detail">
                <ul>
                  <li v-for="(line, index) in item.lines" :key="index">{{ line }}</li>
                </ul>
                <RouterLink :to="item.to">
                  打开详情
                  <ArrowRight />
                </RouterLink>
              </div>
            </article>
          </div>

          <div v-else class="panel-empty is-success">
            <CheckCircle2 />
            <div>
              <strong>当前没有待处理项</strong>
              <p>健康检查、渠道配置和近期任务均未发现异常。</p>
            </div>
          </div>
        </div>
      </LiquidGlass>

      <LiquidGlass :radius="26" :optics="panelOptics" class="home-panel activity-panel">
        <div class="panel-shell">
          <header class="panel-header">
            <div>
              <span class="panel-title-icon"><Activity /></span>
              <div>
                <h2>近期系统活动</h2>
                <p>管理员配置与权限变更</p>
              </div>
            </div>
          </header>

          <div v-if="recentActivities.length" class="activity-list">
            <article
              v-for="(item, index) in recentActivities"
              :key="`${item.title}-${index}`"
              class="activity-item"
            >
              <span class="activity-dot" :class="{ 'is-ok': item.ok }" />
              <div>
                <strong>{{ item.title }}</strong>
                <p>{{ item.detail }}</p>
              </div>
              <time>{{ item.time }}</time>
            </article>
          </div>

          <div v-else class="panel-empty is-compact">
            <CircleDashed />
            <span>{{ authStore.isOperator ? '暂无近期配置变更' : '当前账号无审计查看权限' }}</span>
          </div>
        </div>
      </LiquidGlass>

      <section class="quick-panel">
        <header class="section-heading">
          <div>
            <Sparkles />
            <h2>快捷操作</h2>
          </div>
          <p>直接进入高频任务</p>
        </header>

        <div class="quick-grid">
          <RouterLink
            v-for="item in quickActions"
            :key="item.title"
            :to="item.to"
            class="quick-link"
          >
            <LiquidGlass :radius="20" :optics="compactOptics" interactive class="quick-card">
              <span class="quick-icon"><component :is="item.icon" /></span>
              <div>
                <strong>{{ item.title }}</strong>
                <small>{{ item.detail }}</small>
              </div>
              <ArrowRight />
            </LiquidGlass>
          </RouterLink>
        </div>
      </section>

      <LiquidGlass :radius="26" :optics="panelOptics" class="home-panel tasks-panel">
        <div class="panel-shell">
          <header class="panel-header">
            <div>
              <span class="panel-title-icon"><CalendarClock /></span>
              <div>
                <h2>即将运行任务</h2>
                <p>当前启用的自动执行计划</p>
              </div>
            </div>
            <RouterLink to="/modules/scheduler" class="panel-link">
              管理
              <ArrowRight />
            </RouterLink>
          </header>

          <div v-if="upcomingTasks.length" class="task-list">
            <article v-for="task in upcomingTasks" :key="task.id" class="task-item">
              <span class="task-icon"><Clock3 /></span>
              <div class="task-copy">
                <strong>{{ task.instruction }}</strong>
                <p>#{{ task.id }} · {{ task.channel }}</p>
              </div>
              <div class="task-time">
                <code>{{ task.crontab }}</code>
                <span>{{ task.calendar }}</span>
              </div>
            </article>
          </div>

          <div v-else class="panel-empty is-compact">
            <CircleDashed />
            <span>{{ schedulerError || '暂无启用中的定时任务' }}</span>
          </div>
        </div>
      </LiquidGlass>
    </section>
  </div>
</template>

<style scoped>
.home-cockpit {
  width: min(1500px, 100%);
  gap: 26px;
}

.home-header,
.home-header-actions,
.metric-label,
.metric-content,
.panel-header,
.panel-header > div,
.section-heading,
.section-heading > div,
.attention-toggle,
.attention-detail > a,
.quick-card,
.task-item,
.panel-link {
  display: flex;
  align-items: center;
}

.home-header {
  justify-content: space-between;
  gap: 24px;
}

.home-heading { min-width: 0; }

.home-summary {
  margin: 9px 0 0;
  color: var(--ikaros-copy);
  font-size: 13px;
  font-weight: 550;
}

.home-header-actions { gap: 10px; }

.home-health,
.home-refresh {
  display: inline-flex;
  min-height: 38px;
  align-items: center;
  gap: 8px;
  padding: 0 13px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 750;
}

.home-health {
  border: 1px solid rgba(47, 125, 74, 0.12);
  background: rgba(47, 125, 74, 0.09);
  color: var(--ikaros-rind);
}

.home-health.is-neutral { border-color: var(--ikaros-line); background: var(--panel-muted); color: var(--ikaros-copy); }
.home-health.is-warning { border-color: rgba(200, 120, 32, 0.16); background: rgba(200, 120, 32, 0.1); color: #b86717; }
.home-health.is-danger { border-color: rgba(198, 55, 65, 0.16); background: rgba(198, 55, 65, 0.09); color: #c63741; }

.home-health-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 0 5px color-mix(in srgb, currentColor 11%, transparent);
}

.home-refresh {
  border: 1px solid var(--ikaros-line);
  background: rgba(255, 255, 255, 0.38);
  color: var(--ikaros-copy);
}

:global(.dark) .home-refresh { background: rgba(255, 255, 255, 0.055); }
.home-refresh:hover { border-color: rgba(232, 93, 142, 0.3); color: var(--ikaros-pink); }
.home-refresh:disabled { cursor: wait; opacity: 0.7; }
.home-refresh svg { width: 15px; height: 15px; }
.home-refresh svg.is-spinning { animation: home-spin 850ms linear infinite; }

.metric-grid {
  display: grid;
  grid-template-columns: 1.12fr repeat(3, minmax(0, 1fr));
  gap: 16px;
  align-items: stretch;
}

.metric-link,
.quick-link {
  min-width: 0;
  color: inherit;
  text-decoration: none;
}

.metric-link {
  display: block;
  height: 100%;
}

.metric-card {
  height: 100%;
  min-height: 174px;
  box-sizing: border-box;
  --ikaros-glass-fill: rgba(255, 249, 252, 0.82);
}

:global(.dark) .metric-card { --ikaros-glass-fill: rgba(43, 34, 40, 0.84); }

.metric-card::after {
  position: absolute;
  z-index: 1;
  right: -38px;
  bottom: -58px;
  width: 150px;
  height: 150px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(232, 93, 142, 0.12), transparent 68%);
  content: '';
  pointer-events: none;
}

.metric-card.is-good::after { background: radial-gradient(circle, rgba(47, 125, 74, 0.1), transparent 68%); }
.metric-card.is-warning::after { background: radial-gradient(circle, rgba(200, 120, 32, 0.12), transparent 68%); }
.metric-card.is-danger::after { background: radial-gradient(circle, rgba(198, 55, 65, 0.11), transparent 68%); }

.metric-card-inner {
  position: relative;
  z-index: 2;
  display: grid;
  height: 100%;
  min-height: 174px;
  box-sizing: border-box;
  align-content: space-between;
  gap: 18px;
  padding: 20px;
}

.metric-label { min-width: 0; gap: 9px; color: var(--ikaros-copy); font-size: 12px; font-weight: 750; }

.metric-icon,
.panel-title-icon,
.attention-symbol,
.quick-icon,
.task-icon {
  display: grid;
  flex: none;
  place-items: center;
}

.metric-icon {
  width: 34px;
  height: 34px;
  border: 1px solid rgba(255, 255, 255, 0.68);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.42);
  color: var(--ikaros-pink);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.72);
}

:global(.dark) .metric-icon { border-color: rgba(255, 255, 255, 0.1); background: rgba(255, 255, 255, 0.06); }
.metric-icon svg { width: 18px; height: 18px; }
.metric-card.is-good .metric-icon { color: var(--ikaros-eye); }
.metric-card.is-warning .metric-icon { color: #c87820; }
.metric-card.is-danger .metric-icon { color: #c63741; }

.metric-state {
  margin-left: auto;
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(47, 125, 74, 0.09);
  color: var(--ikaros-rind);
  font-size: 10px;
}

.metric-card.is-warning .metric-state { background: rgba(200, 120, 32, 0.11); color: #b86717; }
.metric-card.is-danger .metric-state { background: rgba(198, 55, 65, 0.09); color: #c63741; }
.metric-card.is-neutral .metric-state { background: var(--panel-muted); color: var(--ikaros-copy); }

.metric-content { min-width: 0; justify-content: space-between; gap: 14px; }
.metric-content > div { min-width: 0; }

.metric-value {
  display: block;
  color: var(--ikaros-ink);
  font-size: clamp(25px, 2.05vw, 33px);
  font-weight: 800;
  letter-spacing: -0.05em;
  line-height: 1.06;
}

.metric-detail {
  min-height: 34px;
  margin: 10px 0 0;
  overflow: hidden;
  color: var(--ikaros-copy);
  font-size: 11px;
  line-height: 1.5;
}

.pulse-orbit {
  position: relative;
  display: grid;
  width: 52px;
  height: 52px;
  flex: none;
  place-items: center;
  border: 1px solid rgba(42, 140, 138, 0.17);
  border-radius: 50%;
}

.pulse-orbit::before,
.pulse-orbit::after {
  position: absolute;
  inset: 7px;
  border: 1px solid rgba(42, 140, 138, 0.2);
  border-radius: 50%;
  content: '';
  animation: home-pulse 2.4s ease-out infinite;
}

.pulse-orbit::after { animation-delay: 1.2s; }
.pulse-orbit > span { width: 10px; height: 10px; border-radius: 50%; background: var(--ikaros-eye); box-shadow: 0 0 18px rgba(42, 140, 138, 0.42); }
.metric-card.is-warning .pulse-orbit > span { background: #c87820; box-shadow: 0 0 18px rgba(200, 120, 32, 0.35); }
.metric-card.is-danger .pulse-orbit > span { background: #c63741; box-shadow: 0 0 18px rgba(198, 55, 65, 0.34); }

.metric-progress {
  height: 3px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(23, 19, 26, 0.07);
}

:global(.dark) .metric-progress { background: rgba(255, 255, 255, 0.08); }
.metric-progress span { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--ikaros-pink), #f092b3); transition: width 500ms cubic-bezier(0.16, 1, 0.3, 1); }
.metric-card.is-good .metric-progress span { background: linear-gradient(90deg, var(--ikaros-eye), #74bbb9); }
.metric-card.is-warning .metric-progress span { background: linear-gradient(90deg, #c87820, #e0a354); }

.home-bento {
  display: grid;
  grid-template-areas:
    'attention activity'
    'quick tasks';
  grid-template-columns: minmax(0, 1.65fr) minmax(330px, 0.82fr);
  gap: 18px;
  align-items: start;
}

.attention-panel { grid-area: attention; }
.activity-panel { grid-area: activity; }
.quick-panel { grid-area: quick; }
.tasks-panel { min-width: 0; grid-area: tasks; }

.home-panel { --ikaros-glass-fill: rgba(255, 249, 252, 0.84); }
:global(.dark) .home-panel { --ikaros-glass-fill: rgba(43, 34, 40, 0.86); }
.panel-shell { min-width: 0; padding: 22px; }

.panel-header { justify-content: space-between; gap: 16px; }
.panel-header > div { min-width: 0; gap: 11px; }
.panel-header h2,
.section-heading h2 { margin: 0; color: var(--ikaros-ink); font-size: 16px; font-weight: 800; letter-spacing: -0.025em; }
.panel-header p,
.section-heading p { margin: 4px 0 0; color: var(--ikaros-muted); font-size: 11px; line-height: 1.4; }

.panel-title-icon {
  width: 34px;
  height: 34px;
  border-radius: 11px;
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.panel-title-icon.is-warning { background: rgba(200, 120, 32, 0.1); color: #c87820; }
.panel-title-icon svg { width: 17px; height: 17px; }

.panel-link { flex: none; gap: 5px; color: var(--ikaros-copy); font-size: 11px; font-weight: 700; text-decoration: none; }
.panel-link:hover { color: var(--ikaros-pink); }
.panel-link svg { width: 14px; height: 14px; }

.attention-list,
.activity-list,
.task-list { display: grid; margin-top: 18px; }
.attention-list { gap: 9px; }

.attention-item {
  overflow: hidden;
  border: 1px solid rgba(200, 120, 32, 0.12);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.35);
}

.attention-item.is-danger { border-color: rgba(198, 55, 65, 0.12); }
:global(.dark) .attention-item { background: rgba(255, 255, 255, 0.04); }

.attention-toggle {
  width: 100%;
  min-height: 68px;
  gap: 12px;
  padding: 10px 12px;
  border: 0;
  background: transparent;
  color: var(--ikaros-ink);
  text-align: left;
}

.attention-symbol {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  background: rgba(200, 120, 32, 0.1);
  color: #c87820;
}

.is-danger .attention-symbol { background: rgba(198, 55, 65, 0.09); color: #c63741; }
.attention-symbol svg { width: 17px; height: 17px; }
.attention-copy { display: grid; min-width: 0; flex: 1; gap: 3px; }
.attention-copy strong { overflow: hidden; font-size: 13px; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.attention-copy small { overflow: hidden; color: var(--ikaros-copy); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }

.attention-action {
  min-width: 54px;
  padding: 6px 10px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 750;
  text-align: center;
}

.attention-toggle > svg { width: 16px; height: 16px; color: var(--ikaros-muted); transition: transform 180ms ease; }
.attention-toggle > svg.is-open { transform: rotate(180deg); }

.attention-detail {
  padding: 0 14px 13px 60px;
  color: var(--ikaros-copy);
  font-size: 11px;
  line-height: 1.55;
}

.attention-detail ul { display: grid; gap: 4px; margin: 0; padding-left: 16px; }
.attention-detail > a { width: fit-content; gap: 5px; margin-top: 10px; color: var(--ikaros-pink); font-weight: 750; text-decoration: none; }
.attention-detail > a svg { width: 13px; height: 13px; }

.activity-list { gap: 0; }
.activity-item { position: relative; display: grid; grid-template-columns: 12px minmax(0, 1fr) auto; gap: 10px; padding: 11px 0; }
.activity-item:not(:last-child)::after { position: absolute; bottom: 0; left: 22px; right: 0; height: 1px; background: var(--ikaros-line); content: ''; }
.activity-dot { width: 8px; height: 8px; margin-top: 4px; border: 2px solid var(--ikaros-glass-strong); border-radius: 50%; background: var(--ikaros-pink); box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.1); }
.activity-dot.is-ok { background: var(--ikaros-rind); box-shadow: 0 0 0 3px rgba(47, 125, 74, 0.1); }
.activity-item > div { min-width: 0; }
.activity-item strong { display: block; overflow: hidden; color: var(--ikaros-ink); font-size: 12px; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.activity-item p { margin: 4px 0 0; overflow: hidden; color: var(--ikaros-copy); font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.activity-item time { color: var(--ikaros-muted); font-size: 9px; white-space: nowrap; }

.section-heading { justify-content: space-between; gap: 14px; padding: 0 4px; }
.section-heading > div { gap: 8px; }
.section-heading > div > svg { width: 17px; height: 17px; color: var(--ikaros-pink); }
.section-heading > p { margin: 0; }

.quick-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-top: 13px; }
.quick-card { min-height: 98px; gap: 11px; padding: 15px; --ikaros-glass-fill: rgba(255, 249, 252, 0.78); }
:global(.dark) .quick-card { --ikaros-glass-fill: rgba(43, 34, 40, 0.8); }
.quick-icon { width: 36px; height: 36px; border-radius: 12px; background: rgba(232, 93, 142, 0.1); color: var(--ikaros-pink); }
.quick-icon svg { width: 18px; height: 18px; }
.quick-card > div { display: grid; min-width: 0; flex: 1; gap: 3px; }
.quick-card strong { color: var(--ikaros-ink); font-size: 12px; font-weight: 750; }
.quick-card small { overflow: hidden; color: var(--ikaros-muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.quick-card > svg { width: 14px; height: 14px; flex: none; color: var(--ikaros-muted); }
.quick-card:hover > svg { color: var(--ikaros-pink); transform: translateX(2px); }

.task-list { gap: 8px; }
.task-item { min-width: 0; min-height: 57px; gap: 10px; padding: 9px 10px; overflow: hidden; border: 1px solid var(--ikaros-line); border-radius: 14px; background: rgba(255, 255, 255, 0.3); }
:global(.dark) .task-item { background: rgba(255, 255, 255, 0.035); }
.task-icon { width: 32px; height: 32px; border-radius: 10px; background: rgba(232, 93, 142, 0.09); color: var(--ikaros-pink); }
.task-icon svg { width: 15px; height: 15px; }
.task-copy { width: 0; min-width: 0; flex: 1 1 0; overflow: hidden; }
.task-copy strong { display: block; max-width: 100%; overflow: hidden; color: var(--ikaros-ink); font-size: 11px; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.task-copy p { max-width: 100%; margin: 4px 0 0; overflow: hidden; color: var(--ikaros-muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.task-time { display: grid; min-width: 0; max-width: 88px; flex: none; justify-items: end; gap: 4px; overflow: hidden; }
.task-time code,
.task-time span { max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.task-time code { color: var(--ikaros-ink); font-size: 10px; font-weight: 750; }
.task-time span { color: var(--ikaros-muted); font-size: 9px; }

.panel-empty { display: flex; min-height: 154px; align-items: center; justify-content: center; gap: 11px; margin-top: 18px; border: 1px dashed var(--ikaros-line); border-radius: 16px; color: var(--ikaros-copy); text-align: left; }
.panel-empty > svg { width: 21px; height: 21px; flex: none; }
.panel-empty strong { color: var(--ikaros-ink); font-size: 13px; }
.panel-empty p { margin: 4px 0 0; color: var(--ikaros-muted); font-size: 11px; }
.panel-empty.is-success > svg { color: var(--ikaros-rind); }
.panel-empty.is-compact { min-height: 110px; font-size: 11px; text-align: center; }

@keyframes home-spin { to { transform: rotate(360deg); } }
@keyframes home-pulse {
  0% { opacity: 0.72; transform: scale(0.5); }
  75%, 100% { opacity: 0; transform: scale(1.5); }
}

@media (max-width: 1240px) {
  .metric-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .quick-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

@media (max-width: 980px) {
  .home-bento {
    grid-template-areas: 'attention' 'quick' 'activity' 'tasks';
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 680px) {
  .home-cockpit { gap: 20px; }
  .home-header { align-items: flex-start; flex-direction: column; }
  .home-header-actions { width: 100%; justify-content: space-between; }
  .home-refresh span { display: none; }
  .metric-grid,
  .quick-grid { grid-template-columns: minmax(0, 1fr); }
  .metric-card,
  .metric-card-inner { min-height: 154px; }
  .panel-shell { padding: 17px; }
  .panel-header p,
  .section-heading > p { display: none; }
  .attention-action { display: none; }
  .attention-detail { padding-left: 14px; }
  .activity-item { grid-template-columns: 12px minmax(0, 1fr); }
  .activity-item time { grid-column: 2; }
}

@media (prefers-reduced-motion: reduce) {
  .home-refresh svg.is-spinning,
  .pulse-orbit::before,
  .pulse-orbit::after { animation: none; }
  .metric-progress span { transition: none; }
}
</style>
