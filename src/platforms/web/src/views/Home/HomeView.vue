<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import {
    Activity,
    AlertTriangle,
    ArrowRight,
    CalendarDays,
    CheckCircle2,
    CircleDashed,
    Clock3,
    HeartPulse,
    MessageSquareText,
    Puzzle,
    RefreshCw,
    Shield,
    TrendingUp,
    WalletCards,
    Zap,
} from 'lucide-vue-next'

import { getAdminAudit, getDiagnostics } from '@/api/admin'
import { getSkills } from '@/api/skills'
import request from '@/api/request'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const loading = ref(false)
const healthStatus = ref<'loading' | 'ok' | 'error'>('loading')
const diagnosticsStatus = ref<'idle' | 'loading' | 'ok' | 'forbidden' | 'error'>('idle')
const diagnostics = ref<Record<string, any> | null>(null)
const auditItems = ref<Array<Record<string, any>>>([])
const schedulerTasks = ref<Array<Record<string, any>>>([])
const schedulerError = ref('')
const skills = ref<Array<Record<string, any>>>([])
const skillsError = ref('')
const watchlistCount = ref<number | null>(null)
const watchlistError = ref('')
const lastUpdatedAt = ref<Date | null>(null)

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

// /admin/diagnostics puts platforms at the top level (not under runtime_config).
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
    platformEntries.value.filter((item) => item.enabled && item.configured),
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
const deliveryFailed = computed(() => Number(quality.value?.artifact_delivery_failed || 0))
const recentFailures = computed(() => {
    const turns = Array.isArray(quality.value?.recent_failed_turns)
        ? quality.value.recent_failed_turns
        : []
    const deliveries = Array.isArray(quality.value?.recent_delivery_failures)
        ? quality.value.recent_delivery_failures
        : []
    return { turns: turns.slice(0, 4), deliveries: deliveries.slice(0, 3) }
})

const activeTasks = computed(() => schedulerTasks.value.filter((task) => task.is_active !== false))
const pausedTasks = computed(() => schedulerTasks.value.filter((task) => task.is_active === false))
const tradingDayTasks = computed(
    () => activeTasks.value.filter((task) => task.run_calendar === 'trading_days').length,
)
const enabledSkills = computed(() => skills.value.filter((skill) => skill.enabled !== false).length)
const disabledSkills = computed(() => skills.value.filter((skill) => skill.enabled === false).length)

const systemStatusText = computed(() => {
    if (healthStatus.value === 'loading' || loading.value) return '检查中'
    if (healthStatus.value !== 'ok') return '异常'
    if (turnFailed.value > 0 || deliveryFailed.value > 0 || enabledMissingConfig.value.length) {
        return '需关注'
    }
    if (diagnosticsStatus.value === 'forbidden') return '基础正常'
    return '正常'
})

const lastUpdatedText = computed(() => {
    if (!lastUpdatedAt.value) return '尚未更新'
    return lastUpdatedAt.value.toLocaleTimeString('zh-CN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
    })
})

const formatAuditTime = (value: unknown) => {
    const raw = String(value || '').trim()
    if (!raw) return '-'
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

const kpiCards = computed(() => [
    {
        key: 'health',
        label: 'API 健康',
        value: healthStatus.value === 'ok' ? '正常' : healthStatus.value === 'loading' ? '检查中' : '失败',
        detail: healthStatus.value === 'ok' ? '/health 通过' : '健康检查未通过',
        tone: healthStatus.value === 'ok' ? 'good' : healthStatus.value === 'loading' ? 'neutral' : 'bad',
        to: '/admin/diagnostics',
        icon: HeartPulse,
    },
    {
        key: 'channels',
        label: '消息渠道',
        value: diagnostics.value
            ? `${enabledPlatforms.value.length}/${platformEntries.value.length}`
            : '—',
        detail: diagnostics.value
            ? enabledPlatforms.value.length
                ? `已启用 ${enabledPlatforms.value.map((p) => p.name).join(' · ')}`
                    + (enabledMissingConfig.value.length
                        ? ` · ${enabledMissingConfig.value.length} 个缺凭证`
                        : ` · 已配置 ${configuredPlatforms.value.length}`)
                : '暂无启用渠道'
            : diagnosticsStatus.value === 'forbidden'
                ? '无诊断权限'
                : '未获取',
        tone: enabledMissingConfig.value.length ? 'warn' : enabledPlatforms.value.length ? 'good' : 'neutral',
        to: '/admin/runtime',
        icon: Zap,
    },
    {
        key: 'scheduler',
        label: '定时任务',
        value: schedulerError.value ? '—' : String(activeTasks.value.length),
        detail: schedulerError.value
            ? schedulerError.value
            : `${pausedTasks.value.length} 暂停 · ${tradingDayTasks.value} 仅交易日`,
        tone: schedulerError.value ? 'warn' : 'neutral',
        to: '/modules/scheduler',
        icon: CalendarDays,
    },
    {
        key: 'skills',
        label: '技能',
        value: skillsError.value ? '—' : String(enabledSkills.value),
        detail: skillsError.value
            ? skillsError.value
            : `${disabledSkills.value} 已禁用 / 共 ${skills.value.length}`,
        tone: 'neutral',
        to: authStore.isAdmin ? '/admin/skills' : '/chat',
        icon: Puzzle,
    },
    {
        key: 'watchlist',
        label: '自选股',
        value: watchlistCount.value === null ? '—' : String(watchlistCount.value),
        detail: watchlistError.value || '当前绑定用户的自选列表',
        tone: watchlistError.value ? 'warn' : 'neutral',
        to: '/modules/watchlist',
        icon: TrendingUp,
    },
    {
        key: 'turns',
        label: '近期运行',
        value: diagnostics.value ? String(turnSucceeded.value + turnFailed.value) : '—',
        detail: diagnostics.value
            ? `成功 ${turnSucceeded.value} · 失败 ${turnFailed.value} · 等待 ${turnWaiting.value}`
            : '需诊断权限',
        tone: turnFailed.value > 0 ? 'bad' : 'good',
        to: '/admin/diagnostics',
        icon: Activity,
    },
])

const attentionItems = computed(() => {
    const items: Array<{
        id: string
        title: string
        detail: string
        to: string
        tone: string
        lines?: string[]
    }> = []
    if (healthStatus.value === 'error') {
        items.push({
            id: 'health',
            title: 'API 健康检查失败',
            detail: '控制台可能无法正常调用后端接口',
            to: '/admin/diagnostics',
            tone: 'bad',
            lines: ['请求 /health 未通过，请检查后端进程与反向代理。'],
        })
    }
    for (const platform of enabledMissingConfig.value) {
        items.push({
            id: `platform-${platform.name}`,
            title: `渠道 ${platform.name} 已启用但未配置`,
            detail: '请到运行配置补齐 Token / 凭证',
            to: '/admin/runtime',
            tone: 'warn',
            lines: [`平台 ${platform.name} 在 runtime 中为 enabled，但环境变量/密钥未配置。`],
        })
    }
    if (deliveryFailed.value > 0) {
        const lines = recentFailures.value.deliveries.map((item: any) => {
            const target = item.target || item.platform || 'unknown'
            const kind = item.artifact_kind || 'message'
            const file = item.artifact_filename ? ` · ${item.artifact_filename}` : ''
            const err = item.error || 'delivery failed'
            const session = item.session_id ? ` · ${item.session_id}` : ''
            return `${target} · ${kind}${file} · ${err}${session}`
        })
        items.push({
            id: 'delivery',
            title: `${deliveryFailed.value} 次投递失败`,
            detail: lines[0]
                ? previewText(lines[0], 90)
                : '近期消息/附件推送未成功，检查 Telegram 等渠道',
            to: '/admin/diagnostics#delivery-failures',
            tone: 'bad',
            lines: lines.length
                ? lines
                : ['详见诊断页「运行质量 / 近期失败 → 投递失败」。'],
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
            tone: 'bad',
            lines: [
                `错误：${turn.error || 'unknown'}`,
                `session：${session || '—'}`,
                `turn：${turn.turn_id || '—'}`,
                `kernel：${turn.kernel_provider || '—'}`,
                isScheduler
                    ? '对应后台「任务调度」中的用户定时任务；可到任务调度页查看/暂停。'
                    : '可到系统诊断页查看完整失败列表。',
            ],
        })
    }
    if (schedulerError.value) {
        items.push({
            id: 'scheduler-load',
            title: '无法加载定时任务',
            detail: schedulerError.value,
            to: '/bindings',
            tone: 'warn',
            lines: [schedulerError.value, '通常需要先完成 Telegram 等平台绑定。'],
        })
    }
    if (watchlistError.value) {
        items.push({
            id: 'watchlist-load',
            title: '无法加载自选股',
            detail: watchlistError.value,
            to: '/bindings',
            tone: 'warn',
            lines: [watchlistError.value],
        })
    }
    return items.slice(0, 8)
})

const expandedAttention = ref<Set<string>>(new Set())
const isAttentionOpen = (id: string) => expandedAttention.value.has(id)
const toggleAttention = (id: string) => {
    const next = new Set(expandedAttention.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    expandedAttention.value = next
}

const upcomingTasks = computed(() =>
    activeTasks.value
        .slice()
        .sort((a, b) => String(a.crontab || '').localeCompare(String(b.crontab || '')))
        .slice(0, 5)
        .map((task) => ({
            id: task.id,
            crontab: String(task.crontab || '—'),
            calendar:
                task.run_calendar === 'trading_days'
                    ? '仅交易日'
                    : task.run_calendar === 'weekdays'
                        ? '仅工作日'
                        : '每天',
            instruction: previewText(task.instruction, 56),
            channel: task.chat_id
                ? `${task.platform || 'telegram'}:${task.chat_id}`
                : '默认推送渠道',
        })),
)

const recentActivities = computed(() =>
    auditItems.value.slice(0, 6).map((item) => ({
        title: String(item.action || '审计记录'),
        detail: previewText(item.summary || item.target || item.actor || '无摘要', 64),
        time: formatAuditTime(item.ts),
        ok: String(item.status || '').toLowerCase() === 'success',
    })),
)

const quickActions = computed(() => {
    const items = [
        { title: '开始对话', detail: 'Web Chat', to: '/chat', icon: MessageSquareText },
        { title: '定时任务', detail: '调度与推送', to: '/modules/scheduler', icon: CalendarDays },
        { title: '自选股', detail: '行情与持仓', to: '/modules/watchlist', icon: TrendingUp },
        { title: '智能记账', detail: '收支与资产', to: '/accounting', icon: WalletCards },
    ]
    if (authStore.isOperator) {
        items.push({ title: '系统诊断', detail: '健康与运行质量', to: '/admin/diagnostics', icon: Shield })
    }
    if (authStore.isAdmin) {
        items.push({ title: '运行配置', detail: '渠道与功能开关', to: '/admin/runtime', icon: Zap })
    }
    return items
})

const gitHeadShort = computed(() => {
    const head = String(diagnostics.value?.version?.git_head || '').trim()
    return head ? head.slice(0, 10) : '—'
})

const memoryProvider = computed(() => diagnostics.value?.memory?.provider || '—')

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
        .then((res) => { schedulerTasks.value = res.data || [] })
        .catch((error: any) => {
            schedulerTasks.value = []
            const detail = error?.response?.data?.detail
            schedulerError.value = typeof detail === 'string'
                ? detail
                : error?.response?.status === 400
                    ? '需要先绑定平台账号'
                    : '加载失败'
        })

    const skillsPromise = getSkills()
        .then((res) => { skills.value = res.data?.skills || res.data || [] })
        .catch(() => {
            skills.value = []
            skillsError.value = '加载失败'
        })

    const watchlistPromise = request.get('/watchlist')
        .then((res) => { watchlistCount.value = Array.isArray(res.data) ? res.data.length : 0 })
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
            .then(([diagResponse, auditResponse]) => {
                diagnostics.value = diagResponse.data
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

    await Promise.all([healthPromise, schedulerPromise, skillsPromise, watchlistPromise, adminPromise])
    lastUpdatedAt.value = new Date()
    loading.value = false
}

onMounted(loadDashboard)
</script>

<template>
  <div class="home">
    <section class="hero">
      <div class="hero-copy">
        <p class="eyebrow">IKAROS Console</p>
        <h1>{{ greeting }}，{{ displayName }}</h1>
        <p class="sub">
          这里汇总当前运行状态与需要你留意的事项，而不是再抄一遍侧栏菜单。
        </p>
      </div>
      <div class="hero-aside">
        <div class="status-chip" :class="{ warn: systemStatusText !== '正常', bad: systemStatusText === '异常' }">
          <span class="dot" />
          系统状态：{{ systemStatusText }}
        </div>
        <button type="button" class="refresh-btn" :disabled="loading" @click="loadDashboard">
          <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" />
          刷新 · {{ lastUpdatedText }}
        </button>
      </div>
    </section>

    <section class="kpi-grid">
      <RouterLink
        v-for="card in kpiCards"
        :key="card.key"
        :to="card.to"
        class="kpi-card"
        :class="`tone-${card.tone}`"
      >
        <div class="kpi-top">
          <component :is="card.icon" class="h-4 w-4" />
          <span>{{ card.label }}</span>
        </div>
        <div class="kpi-value">{{ card.value }}</div>
        <p class="kpi-detail">{{ card.detail }}</p>
      </RouterLink>
    </section>

    <section class="main-grid">
      <div class="col">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h2>需要关注</h2>
              <p>近 7 天失败任务、投递问题、渠道配置缺口</p>
            </div>
            <RouterLink to="/admin/diagnostics#runtime-failures" class="link">诊断详情</RouterLink>
          </div>

          <div v-if="attentionItems.length" class="attention-list">
            <article
              v-for="item in attentionItems"
              :key="item.id"
              class="attention-item"
              :class="[item.tone, { open: isAttentionOpen(item.id) }]"
            >
              <button type="button" class="attention-main" @click="toggleAttention(item.id)">
                <AlertTriangle class="h-4 w-4 shrink-0" />
                <div class="min-w-0 text-left">
                  <h3>{{ item.title }}</h3>
                  <p>{{ item.detail }}</p>
                </div>
                <span class="expand-hint">{{ isAttentionOpen(item.id) ? '收起' : '详情' }}</span>
              </button>
              <div v-if="isAttentionOpen(item.id)" class="attention-body">
                <ul v-if="item.lines?.length">
                  <li v-for="(line, index) in item.lines" :key="index">{{ line }}</li>
                </ul>
                <RouterLink :to="item.to" class="attention-link">
                  查看完整诊断
                  <ArrowRight class="h-3.5 w-3.5" />
                </RouterLink>
              </div>
            </article>
          </div>
          <div v-else class="empty good">
            <CheckCircle2 class="h-5 w-5" />
            <div>
              <strong>暂无告警</strong>
              <p>健康检查、渠道配置与近期失败项看起来都正常。</p>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <h2>活跃定时任务</h2>
              <p>按 cron 排序的当前启用任务</p>
            </div>
            <RouterLink to="/modules/scheduler" class="link">管理</RouterLink>
          </div>

          <div v-if="upcomingTasks.length" class="task-list">
            <article v-for="task in upcomingTasks" :key="task.id" class="task-row">
              <div class="task-cron">
                <Clock3 class="h-3.5 w-3.5" />
                <code>{{ task.crontab }}</code>
                <span class="tag">{{ task.calendar }}</span>
              </div>
              <p class="task-text">{{ task.instruction }}</p>
              <p class="task-meta">#{{ task.id }} · {{ task.channel }}</p>
            </article>
          </div>
          <div v-else class="empty">
            <CircleDashed class="h-5 w-5" />
            <div>
              <strong>{{ schedulerError || '暂无启用中的定时任务' }}</strong>
              <p v-if="schedulerError">绑定 Telegram 等平台账号后即可在此查看。</p>
              <p v-else>可在任务调度页添加 cron 任务。</p>
            </div>
          </div>
        </section>
      </div>

      <div class="col side">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h2>快捷入口</h2>
              <p>高频操作，不重复侧栏</p>
            </div>
          </div>
          <div class="quick-grid">
            <RouterLink
              v-for="item in quickActions"
              :key="item.to"
              :to="item.to"
              class="quick-card"
            >
              <component :is="item.icon" class="h-4 w-4" />
              <div>
                <strong>{{ item.title }}</strong>
                <span>{{ item.detail }}</span>
              </div>
            </RouterLink>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <h2>运行摘要</h2>
              <p>版本与 Memory</p>
            </div>
          </div>
          <div class="meta-grid">
            <div>
              <span>角色</span>
              <strong>{{ roleLabel }}</strong>
            </div>
            <div>
              <span>Memory</span>
              <strong>{{ memoryProvider }}</strong>
            </div>
            <div>
              <span>Git</span>
              <strong>{{ gitHeadShort }}</strong>
            </div>
            <div>
              <span>投递失败</span>
              <strong :class="{ bad: deliveryFailed > 0 }">{{ diagnostics ? deliveryFailed : '—' }}</strong>
            </div>
          </div>
        </section>

        <section class="panel grow">
          <div class="panel-head">
            <div>
              <h2>近期活动</h2>
              <p>管理员配置变更审计</p>
            </div>
            <RouterLink to="/admin/diagnostics" class="link">更多</RouterLink>
          </div>
          <div v-if="recentActivities.length" class="activity-list">
            <article v-for="(item, index) in recentActivities" :key="`${item.title}-${index}`" class="activity-row">
              <span class="dot" :class="{ ok: item.ok }" />
              <div class="min-w-0">
                <h3>{{ item.title }}</h3>
                <p>{{ item.detail }}</p>
              </div>
              <time>{{ item.time }}</time>
            </article>
          </div>
          <div v-else class="empty compact">
            {{ authStore.isOperator ? '暂无审计记录。' : '当前账号无权限查看审计记录。' }}
          </div>
        </section>
      </div>
    </section>
  </div>
</template>

<style scoped>
.home {
  display: grid;
  gap: 20px;
}

.hero,
.panel,
.kpi-card,
.quick-card,
.attention-item,
.task-row {
  border: 1px solid var(--panel-border);
  border-radius: 16px;
  background: var(--color-bg-elevated);
}

.hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 24px 26px;
  box-shadow: var(--shadow-card);
}

.eyebrow {
  margin: 0 0 8px;
  color: var(--text-subtle);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
}

.hero h1 {
  margin: 0;
  color: var(--text-strong);
  font-size: 28px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.sub {
  margin: 10px 0 0;
  max-width: 48rem;
  color: var(--text-muted);
  font-size: 14px;
  line-height: 1.6;
}

.hero-aside {
  display: grid;
  justify-items: end;
  gap: 10px;
}

.status-chip,
.refresh-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border-radius: 999px;
  padding: 8px 14px;
  font-size: 13px;
  font-weight: 600;
}

.status-chip {
  background: color-mix(in srgb, var(--success) 12%, transparent);
  color: var(--text-strong);
}

.status-chip.warn {
  background: color-mix(in srgb, var(--warning) 16%, transparent);
}

.status-chip.bad {
  background: color-mix(in srgb, #ef4444 14%, transparent);
}

.status-chip .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--success);
}

.status-chip.warn .dot {
  background: var(--warning);
}

.status-chip.bad .dot {
  background: #ef4444;
}

.refresh-btn {
  border: 1px solid var(--panel-border);
  background: var(--panel-muted);
  color: var(--text-body);
  cursor: pointer;
}

.refresh-btn:disabled {
  opacity: 0.7;
  cursor: default;
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 14px;
}

.kpi-card {
  display: grid;
  gap: 10px;
  min-height: 124px;
  padding: 16px;
  color: inherit;
  text-decoration: none;
  box-shadow: var(--shadow-card);
  transition: border-color 0.15s ease, transform 0.15s ease;
}

.kpi-card:hover {
  border-color: color-mix(in srgb, var(--brand-blue) 45%, var(--panel-border));
  transform: translateY(-1px);
}

.kpi-top {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 700;
}

.kpi-value {
  color: var(--text-strong);
  font-size: 28px;
  font-weight: 800;
  line-height: 1;
}

.kpi-detail {
  margin: 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.tone-good .kpi-value { color: var(--success); }
.tone-warn .kpi-value { color: var(--warning); }
.tone-bad .kpi-value { color: #ef4444; }

.main-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.4fr) minmax(300px, 0.9fr);
  gap: 16px;
  align-items: start;
}

.col {
  display: grid;
  gap: 16px;
}

.side {
  min-width: 0;
}

.panel {
  padding: 18px 18px 16px;
  box-shadow: var(--shadow-card);
}

.panel.grow {
  min-height: 280px;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.panel-head h2 {
  margin: 0;
  color: var(--text-strong);
  font-size: 16px;
  font-weight: 800;
}

.panel-head p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

.link {
  color: var(--brand-blue);
  font-size: 13px;
  font-weight: 700;
  text-decoration: none;
  white-space: nowrap;
}

.attention-list,
.task-list,
.activity-list {
  display: grid;
  gap: 10px;
}

.attention-item {
  overflow: hidden;
  color: inherit;
}

.attention-item.bad {
  border-color: color-mix(in srgb, #ef4444 28%, var(--panel-border));
  background: color-mix(in srgb, #ef4444 6%, var(--color-bg-elevated));
}

.attention-item.warn {
  border-color: color-mix(in srgb, var(--warning) 28%, var(--panel-border));
  background: color-mix(in srgb, var(--warning) 8%, var(--color-bg-elevated));
}

.attention-main {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  width: 100%;
  border: 0;
  background: transparent;
  padding: 12px 14px;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.expand-hint {
  color: var(--text-subtle);
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.attention-body {
  border-top: 1px solid color-mix(in srgb, var(--panel-border) 80%, transparent);
  padding: 0 14px 12px;
}

.attention-body ul {
  margin: 10px 0 0;
  padding-left: 18px;
  color: var(--text-body);
  font-size: 12px;
  line-height: 1.55;
}

.attention-body li {
  margin-top: 4px;
  word-break: break-word;
}

.attention-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  color: var(--brand-blue);
  font-size: 12px;
  font-weight: 700;
  text-decoration: none;
}

.attention-item h3,
.task-text,
.activity-row h3 {
  margin: 0;
  color: var(--text-strong);
  font-size: 14px;
  font-weight: 700;
}

.attention-item p,
.task-meta,
.activity-row p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.45;
}

.task-row {
  padding: 12px 14px;
}

.task-cron {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.task-cron code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--text-strong);
}

.tag {
  border-radius: 999px;
  background: var(--panel-muted);
  padding: 2px 8px;
  color: var(--text-body);
  font-size: 11px;
  font-weight: 700;
}

.quick-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.quick-card {
  display: grid;
  grid-template-columns: 16px minmax(0, 1fr);
  gap: 10px;
  padding: 12px;
  color: inherit;
  text-decoration: none;
  transition: border-color 0.15s ease;
}

.quick-card:hover {
  border-color: color-mix(in srgb, var(--brand-blue) 45%, var(--panel-border));
}

.quick-card strong {
  display: block;
  color: var(--text-strong);
  font-size: 13px;
}

.quick-card span {
  color: var(--text-muted);
  font-size: 12px;
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.meta-grid div {
  display: grid;
  gap: 4px;
  padding: 10px 12px;
  border-radius: 12px;
  background: var(--panel-muted);
}

.meta-grid span {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.meta-grid strong {
  color: var(--text-strong);
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta-grid strong.bad {
  color: #ef4444;
}

.activity-row {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: start;
}

.activity-row .dot {
  width: 8px;
  height: 8px;
  margin-top: 5px;
  border-radius: 50%;
  background: var(--warning);
}

.activity-row .dot.ok {
  background: var(--success);
}

.activity-row time {
  color: var(--text-subtle);
  font-size: 11px;
  white-space: nowrap;
}

.empty {
  display: flex;
  gap: 12px;
  align-items: flex-start;
  padding: 16px;
  border: 1px dashed var(--panel-border);
  border-radius: 14px;
  color: var(--text-muted);
}

.empty.good {
  border-style: solid;
  background: color-mix(in srgb, var(--success) 8%, transparent);
  color: var(--text-strong);
}

.empty.compact {
  justify-content: center;
  text-align: center;
}

.empty strong {
  display: block;
  font-size: 14px;
}

.empty p {
  margin: 4px 0 0;
  color: var(--text-muted);
  font-size: 12px;
}

@media (max-width: 1400px) {
  .kpi-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 1100px) {
  .main-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .hero {
    flex-direction: column;
  }

  .hero-aside {
    justify-items: start;
  }

  .kpi-grid,
  .quick-grid,
  .meta-grid {
    grid-template-columns: 1fr;
  }
}
</style>
