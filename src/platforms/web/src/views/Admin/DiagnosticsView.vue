<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
    AlertTriangle,
    Lightbulb,
    Loader2,
    MemoryStick,
    Package,
    RefreshCw,
    ShieldCheck,
    Waypoints,
} from 'lucide-vue-next'

import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import { getAdminAudit, getDiagnostics } from '@/api/admin'

const route = useRoute()
const loading = ref(false)
const diagnostics = ref<Record<string, any> | null>(null)
const auditItems = ref<Array<Record<string, any>>>([])

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

const platformsMap = computed(() => {
    const root = diagnostics.value || {}
    return (
        root.platforms
        || root.runtime_config?.platforms
        || {}
    ) as Record<string, boolean>
})

const platformRows = computed(() =>
    Object.entries(platformsMap.value).map(([name, enabled]) => ({
        name,
        enabled: Boolean(enabled),
        configured: Boolean(diagnostics.value?.platform_env?.[name]?.configured),
    })),
)

const enabledPlatformCount = computed(() => platformRows.value.filter(item => item.enabled).length)
const configuredPlatformCount = computed(() => platformRows.value.filter(item => item.configured).length)

const configRows = computed(() =>
    Object.entries(diagnostics.value?.config_files || {}).map(([key, value]) => ({
        key,
        value,
        ok: typeof value === 'boolean' ? value : true,
    })),
)

const quality = computed(() => diagnostics.value?.runtime_v2_quality || null)
const statusCounts = computed(() => (quality.value?.status_counts || {}) as Record<string, number>)
const statusCountRows = computed(() =>
    Object.entries(statusCounts.value)
        .sort((a, b) => Number(b[1] || 0) - Number(a[1] || 0))
        .map(([status, count]) => ({ status, count: Number(count || 0) })),
)
const maxStatusCount = computed(() =>
    Math.max(1, ...statusCountRows.value.map(row => row.count)),
)
const failedTurns = computed(() =>
    Array.isArray(quality.value?.recent_failed_turns)
        ? quality.value.recent_failed_turns
        : [],
)
const deliveryFailures = computed(() =>
    Array.isArray(quality.value?.recent_delivery_failures)
        ? quality.value.recent_delivery_failures
        : [],
)
const deliveryFailureCounts = computed(() =>
    Object.entries(quality.value?.delivery_failure_counts || {}).map(([key, count]) => ({
        key,
        count: Number(count || 0),
    })),
)
const recommendations = computed(() =>
    Array.isArray(quality.value?.recommendations) ? quality.value.recommendations : [],
)

const auditTable = computed(() => auditItems.value.slice(0, 20))

const totalTurns = computed(() =>
    statusCountRows.value.reduce((sum, row) => sum + row.count, 0),
)
const failedTurnCount = computed(() => Number(statusCounts.value.failed || 0))
const deliveryFailedCount = computed(() =>
    Number(quality.value?.artifact_delivery_failed || 0),
)

const scrollToHash = async () => {
    await nextTick()
    const hash = String(route.hash || '').replace(/^#/, '')
    if (!hash) return
    const el = document.getElementById(hash)
    if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
        el.classList.add('ring-highlight')
        window.setTimeout(() => el.classList.remove('ring-highlight'), 1800)
    }
}

const load = async () => {
    loading.value = true
    try {
        const [diagResponse, auditResponse] = await Promise.all([getDiagnostics(), getAdminAudit()])
        diagnostics.value = diagResponse.data
        auditItems.value = auditResponse.data.items || []
    } finally {
        loading.value = false
        await scrollToHash()
    }
}

onMounted(load)
</script>

<template>
  <div class="ikaros-page diag-page">
    <header class="ikaros-page-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Admin · Diagnostics</p>
        <h1 class="ikaros-page-title">诊断中心</h1>
        <p class="ikaros-page-description">快速判断系统能不能跑、哪里没配，以及最近失败了什么。</p>
      </div>
      <div class="diag-actions">
        <button type="button" class="ikaros-secondary-action" :disabled="loading" @click="load">
          <Loader2 v-if="loading" class="is-spinning" />
          <RefreshCw v-else />
          刷新
        </button>
      </div>
    </header>

    <div v-if="loading && !diagnostics" class="diag-loading ikaros-surface">
      <Loader2 class="is-spinning" />
      正在加载诊断信息
    </div>

    <template v-else-if="diagnostics">
      <LiquidGlass :radius="20" :optics="compactOptics" class="diag-metrics">
        <div class="diag-metrics-inner">
          <div class="diag-metric">
            <span>已启用平台</span>
            <strong class="is-green">{{ enabledPlatformCount }}</strong>
          </div>
          <i class="diag-metric-divider" aria-hidden="true" />
          <div class="diag-metric">
            <span>已配置平台</span>
            <strong class="is-teal">{{ configuredPlatformCount }}</strong>
          </div>
          <i class="diag-metric-divider" aria-hidden="true" />
          <div class="diag-metric">
            <span>近 {{ quality?.window_days || 7 }} 天失败 Turn</span>
            <strong class="is-red">{{ failedTurnCount }}</strong>
          </div>
          <i class="diag-metric-divider" aria-hidden="true" />
          <div class="diag-metric">
            <span>投递失败</span>
            <strong class="is-orange">{{ deliveryFailedCount }}</strong>
          </div>
        </div>
      </LiquidGlass>

      <div class="diag-bento">
        <LiquidGlass
          id="runtime-failures"
          :radius="24"
          :optics="panelOptics"
          class="diag-panel quality-panel"
        >
          <div class="panel-shell">
            <div class="quality-head">
              <div class="panel-title-row">
                <span class="panel-icon is-red"><AlertTriangle /></span>
                <div class="panel-title-text">
                  <h2>运行质量 / 近期失败</h2>
                  <p>仅统计近 {{ quality?.window_days || 7 }} 天的 turn / delivery，过期失败会自动消失。</p>
                </div>
              </div>
              <div class="quality-chips">
                <span class="q-chip">近 {{ quality?.window_days || 7 }} 天</span>
                <span class="q-chip">采样 turns {{ totalTurns }}</span>
                <span class="q-chip" :class="failedTurnCount ? 'is-bad' : 'is-good'">failed {{ failedTurnCount }}</span>
                <span class="q-chip" :class="deliveryFailedCount ? 'is-bad' : 'is-good'">delivery fail {{ deliveryFailedCount }}</span>
              </div>
            </div>

            <div v-if="!quality && !loading" class="diag-empty">暂无 runtime quality 数据。</div>

            <template v-else-if="quality">
              <div class="status-bars">
                <div v-for="row in statusCountRows" :key="row.status" class="status-bar-row">
                  <span class="status-bar-label">{{ row.status }}</span>
                  <div class="status-bar-track">
                    <i :class="{ 'is-failed': row.status === 'failed' }" :style="{ width: `${Math.max(6, (row.count / maxStatusCount) * 100)}%` }" />
                  </div>
                  <strong>{{ row.count }}</strong>
                </div>
              </div>

              <div v-if="deliveryFailureCounts.length" class="failure-chips">
                <span v-for="item in deliveryFailureCounts" :key="item.key">{{ item.key }} × {{ item.count }}</span>
              </div>

              <div class="failure-lists">
                <section id="failed-turns" class="failure-card">
                  <h3>失败 Turn</h3>
                  <p class="failure-card-desc">例如定时任务无输出、模型执行失败等。</p>
                  <div class="failure-items">
                    <article
                      v-for="(item, index) in failedTurns"
                      :key="`${item.turn_id || item.session_id}-${index}`"
                      class="failure-item"
                    >
                      <strong>{{ item.error || 'failed' }}</strong>
                      <dl>
                        <div v-if="item.updated_at"><span>time</span>{{ item.updated_at }}</div>
                        <div><span>session</span><code>{{ item.session_id || '—' }}</code></div>
                        <div><span>turn</span><code>{{ item.turn_id || '—' }}</code></div>
                        <div><span>kernel</span>{{ item.kernel_provider || '—' }}</div>
                      </dl>
                      <p class="failure-hint">若 session 以 <code>scheduler-task-</code> 开头，对应后台「任务调度」里的定时任务。</p>
                    </article>
                    <div v-if="!failedTurns.length" class="diag-empty">最近采样中没有失败 turn。</div>
                  </div>
                </section>

                <section id="delivery-failures" class="failure-card">
                  <h3>投递失败</h3>
                  <p class="failure-card-desc">消息/图片/文档推送到 Telegram 等渠道失败的记录。</p>
                  <div class="failure-items">
                    <article
                      v-for="(item, index) in deliveryFailures"
                      :key="`${item.turn_id || item.session_id}-${item.artifact_filename}-${index}`"
                      class="failure-item"
                    >
                      <strong>{{ item.error || 'delivery failed' }}</strong>
                      <dl>
                        <div v-if="item.updated_at"><span>time</span>{{ item.updated_at }}</div>
                        <div><span>target</span>{{ item.target || `${item.platform || '—'}` }}</div>
                        <div><span>kind</span>{{ item.artifact_kind || '—' }} · {{ item.artifact_filename || '（无文件名）' }}</div>
                        <div><span>session</span><code>{{ item.session_id || '—' }}</code></div>
                        <div v-if="item.turn_id"><span>turn</span><code>{{ item.turn_id }}</code></div>
                      </dl>
                    </article>
                    <div v-if="!deliveryFailures.length" class="diag-empty">最近没有投递失败记录。</div>
                  </div>
                </section>
              </div>

              <div v-if="recommendations.length" class="recommend-box">
                <div class="recommend-title">
                  <Lightbulb />
                  诊断建议
                </div>
                <ul>
                  <li v-for="(tip, index) in recommendations" :key="index">{{ tip }}</li>
                </ul>
              </div>
            </template>
          </div>
        </LiquidGlass>

        <div class="diag-side">
          <LiquidGlass :radius="24" :optics="panelOptics" class="diag-panel">
            <div class="panel-shell">
              <div class="panel-title-row">
                <span class="panel-icon is-teal"><Waypoints /></span>
                <h2>平台诊断</h2>
              </div>
              <div class="platform-list">
                <div v-for="item in platformRows" :key="item.name" class="platform-row">
                  <div class="platform-meta">
                    <strong>{{ item.name }}</strong>
                    <div class="platform-chips">
                      <span class="p-chip" :class="item.enabled ? 'is-on' : 'is-off'">{{ item.enabled ? 'Enabled' : 'Disabled' }}</span>
                      <span class="p-chip" :class="item.configured ? 'is-configured' : 'is-pending'">{{ item.configured ? 'Configured' : 'Pending' }}</span>
                    </div>
                  </div>
                  <i class="platform-dot" :class="{ on: item.enabled }" aria-hidden="true" />
                </div>
                <div v-if="!platformRows.length" class="diag-empty">暂无平台状态数据</div>
              </div>
            </div>
          </LiquidGlass>

          <LiquidGlass :radius="24" :optics="panelOptics" class="diag-panel">
            <div class="panel-shell">
              <div class="panel-title-row">
                <span class="panel-icon is-pink"><Package /></span>
                <h2>配置与版本</h2>
              </div>
              <div class="config-list">
                <div v-for="item in configRows" :key="item.key" class="config-row">
                  <div class="config-row-head">
                    <strong>{{ item.key }}</strong>
                    <span v-if="typeof item.value === 'boolean'" class="p-chip" :class="item.value ? 'is-on' : 'is-bad'">
                      {{ item.value ? 'ok' : 'missing' }}
                    </span>
                  </div>
                  <p>{{ item.value }}</p>
                </div>
                <div class="config-row">
                  <div class="config-row-head"><strong>Git Head</strong></div>
                  <p>{{ diagnostics.version?.git_head || 'unknown' }}</p>
                </div>
                <div class="config-row">
                  <div class="config-row-head">
                    <strong class="config-memory-title"><MemoryStick /> Memory</strong>
                  </div>
                  <p>
                    provider: {{ diagnostics.memory?.provider || 'unknown' }}
                    <br>
                    providers: {{ (diagnostics.memory?.providers || []).join(', ') || 'none' }}
                  </p>
                </div>
              </div>
            </div>
          </LiquidGlass>
        </div>
      </div>
    </template>

    <LiquidGlass :radius="24" :optics="panelOptics" class="diag-panel audit-panel">
      <div class="panel-shell">
        <div class="panel-title-row">
          <span class="panel-icon is-pink"><ShieldCheck /></span>
          <h2>管理员审计</h2>
        </div>
        <div class="audit-table-wrap">
          <table>
            <thead>
              <tr>
                <th>时间</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Summary</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in auditTable" :key="String(item.ts) + String(item.action)">
                <td class="audit-time">{{ item.ts }}</td>
                <td>{{ item.actor }}</td>
                <td>{{ item.action }}</td>
                <td>{{ item.summary }}</td>
              </tr>
            </tbody>
          </table>

          <div v-if="!auditTable.length && !loading" class="diag-empty">
            暂时还没有管理员审计记录。
          </div>
        </div>
      </div>
    </LiquidGlass>
  </div>
</template>

<style scoped>
.diag-page {
  gap: 22px;
}

.diag-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 10px;
}

.diag-actions svg { width: 15px; height: 15px; }

.is-spinning { animation: diag-spin 850ms linear infinite; }

.diag-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 18px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.diag-loading svg { width: 16px; height: 16px; }

.diag-metrics {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.8);
}

:global(.dark) .diag-metrics { --ikaros-glass-fill: rgba(43, 34, 40, 0.82); }

.diag-metrics-inner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 22px;
  padding: 16px 24px;
}

.diag-metric {
  display: grid;
  gap: 3px;
}

.diag-metric span {
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
}

.diag-metric strong {
  color: var(--ikaros-ink);
  font-size: 21px;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.diag-metric strong.is-green { color: var(--ikaros-rind); }
.diag-metric strong.is-teal { color: var(--ikaros-eye); }
.diag-metric strong.is-red { color: #c63741; }
.diag-metric strong.is-orange { color: #c87820; }

.diag-metric-divider {
  width: 1px;
  height: 30px;
  background: var(--ikaros-line);
}

.diag-bento {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(320px, 0.9fr);
  gap: 18px;
  align-items: start;
}

.diag-panel {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .diag-panel { --ikaros-glass-fill: rgba(43, 34, 40, 0.86); }

.panel-shell {
  padding: 20px;
}

.panel-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.panel-title-row h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.panel-title-text p {
  margin: 4px 0 0;
  color: var(--ikaros-muted);
  font-size: 12px;
  line-height: 1.55;
}

.panel-icon {
  display: grid;
  width: 36px;
  height: 36px;
  flex: none;
  place-items: center;
  border-radius: 12px;
}

.panel-icon svg { width: 18px; height: 18px; }
.panel-icon.is-pink { background: rgba(232, 93, 142, 0.1); color: var(--ikaros-pink); }
.panel-icon.is-teal { background: rgba(42, 140, 138, 0.1); color: var(--ikaros-eye); }
.panel-icon.is-red { background: rgba(198, 55, 65, 0.1); color: #c63741; }

.quality-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.quality-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.q-chip {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.5);
  padding: 0 10px;
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 700;
}

:global(.dark) .q-chip { background: rgba(255, 255, 255, 0.06); }
.q-chip.is-good { border-color: rgba(47, 125, 74, 0.25); background: rgba(47, 125, 74, 0.08); color: var(--ikaros-rind); }
.q-chip.is-bad { border-color: rgba(198, 55, 65, 0.25); background: rgba(198, 55, 65, 0.08); color: #c63741; }

.diag-empty {
  border: 1px dashed var(--ikaros-line);
  border-radius: 12px;
  padding: 26px 16px;
  color: var(--ikaros-muted);
  font-size: 12px;
  text-align: center;
}

.quality-head + .diag-empty { margin-top: 16px; }

.status-bars {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}

.status-bar-row {
  display: grid;
  grid-template-columns: 96px minmax(0, 1fr) 42px;
  align-items: center;
  gap: 12px;
}

.status-bar-label {
  overflow: hidden;
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.status-bar-track {
  height: 8px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(23, 19, 26, 0.07);
}

:global(.dark) .status-bar-track { background: rgba(255, 255, 255, 0.08); }

.status-bar-track i {
  display: block;
  height: 100%;
  border-radius: 999px;
  background: var(--ikaros-pink);
  transition: width 240ms ease;
}

.status-bar-track i.is-failed { background: #c63741; }

.status-bar-row strong {
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 800;
  text-align: right;
}

.failure-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 14px;
}

.failure-chips span {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  border: 1px solid rgba(198, 55, 65, 0.2);
  border-radius: 999px;
  background: rgba(198, 55, 65, 0.07);
  padding: 0 10px;
  color: #c63741;
  font-size: 11px;
  font-weight: 650;
}

.failure-lists {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 16px;
}

.failure-card {
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.42);
  padding: 16px;
}

:global(.dark) .failure-card { background: rgba(255, 255, 255, 0.05); }

.failure-card h3 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 800;
}

.failure-card-desc {
  margin: 4px 0 0;
  color: var(--ikaros-muted);
  font-size: 11px;
}

.failure-items {
  display: grid;
  gap: 10px;
  margin-top: 12px;
}

.failure-item {
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.55);
  padding: 12px 14px;
}

:global(.dark) .failure-item { background: rgba(255, 255, 255, 0.06); }

.failure-item > strong {
  color: #c63741;
  font-size: 12px;
  font-weight: 750;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.failure-item dl {
  display: grid;
  gap: 3px;
  margin: 8px 0 0;
}

.failure-item dl div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  color: var(--ikaros-copy);
  font-size: 11px;
  line-height: 1.55;
}

.failure-item dl span {
  color: var(--ikaros-muted);
}

.failure-item dl span::after {
  content: '·';
  margin-left: 6px;
}

.failure-item code {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 10.5px;
  overflow-wrap: anywhere;
}

.failure-hint {
  margin: 8px 0 0;
  color: var(--ikaros-muted);
  font-size: 11px;
  line-height: 1.55;
}

.recommend-box {
  margin-top: 16px;
  border: 1px solid rgba(232, 93, 142, 0.2);
  border-radius: 14px;
  background: rgba(232, 93, 142, 0.06);
  padding: 14px 16px;
}

.recommend-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ikaros-pink-dark);
  font-size: 13px;
  font-weight: 800;
}

:global(.dark) .recommend-title { color: #f3a1c1; }
.recommend-title svg { width: 15px; height: 15px; }

.recommend-box ul {
  display: grid;
  gap: 6px;
  margin: 10px 0 0;
  padding-left: 18px;
}

.recommend-box li {
  color: var(--ikaros-copy);
  font-size: 12px;
  line-height: 1.6;
}

.recommend-box li::marker { color: var(--ikaros-pink); }

.diag-side {
  display: grid;
  gap: 18px;
}

.platform-list {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.platform-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.42);
  padding: 12px 14px;
}

:global(.dark) .platform-row { background: rgba(255, 255, 255, 0.05); }

.platform-meta {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.platform-meta strong {
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 750;
}

.platform-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.p-chip {
  display: inline-flex;
  min-height: 20px;
  align-items: center;
  border-radius: 999px;
  padding: 0 8px;
  font-size: 10.5px;
  font-weight: 700;
}

.p-chip.is-on { background: rgba(47, 125, 74, 0.1); color: var(--ikaros-rind); }
.p-chip.is-off { background: rgba(23, 19, 26, 0.07); color: var(--ikaros-muted); }
:global(.dark) .p-chip.is-off { background: rgba(255, 255, 255, 0.08); }
.p-chip.is-configured { background: rgba(42, 140, 138, 0.1); color: var(--ikaros-eye); }
.p-chip.is-pending { background: rgba(200, 120, 32, 0.12); color: #b86717; }
.p-chip.is-bad { background: rgba(198, 55, 65, 0.09); color: #c63741; }

.platform-dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  background: rgba(23, 19, 26, 0.2);
}

:global(.dark) .platform-dot { background: rgba(255, 255, 255, 0.22); }

.platform-dot.on {
  background: var(--ikaros-rind);
  box-shadow: 0 0 0 3px rgba(47, 125, 74, 0.12);
}

.config-list {
  display: grid;
  gap: 10px;
  margin-top: 16px;
}

.config-row {
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.42);
  padding: 12px 14px;
}

:global(.dark) .config-row { background: rgba(255, 255, 255, 0.05); }

.config-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.config-row-head strong {
  color: var(--ikaros-ink);
  font-size: 12px;
  font-weight: 750;
}

.config-memory-title {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.config-memory-title svg {
  width: 14px;
  height: 14px;
  color: var(--ikaros-pink);
}

.config-row p {
  margin: 6px 0 0;
  color: var(--ikaros-muted);
  font-size: 11px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.audit-table-wrap {
  margin-top: 16px;
  overflow-x: auto;
}

.audit-table-wrap table {
  width: 100%;
  min-width: 560px;
  border-collapse: collapse;
}

.audit-table-wrap th {
  border-bottom: 0.5px solid var(--ikaros-glass-hairline);
  padding: 9px 12px;
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-align: left;
  text-transform: uppercase;
}

.audit-table-wrap td {
  border-bottom: 0.5px solid var(--ikaros-glass-hairline);
  padding: 11px 12px;
  color: var(--ikaros-copy);
  font-size: 12px;
  line-height: 1.55;
}

.audit-table-wrap tbody tr:last-child td { border-bottom: 0; }

.audit-table-wrap td.audit-time {
  color: var(--ikaros-muted);
  white-space: nowrap;
}

.audit-table-wrap .diag-empty { margin-top: 12px; }

#runtime-failures,
#failed-turns,
#delivery-failures {
  scroll-margin-top: 90px;
}

.ring-highlight {
  box-shadow: 0 0 0 3px rgba(198, 55, 65, 0.25);
  transition: box-shadow 0.3s ease;
}

@keyframes diag-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1200px) {
  .diag-bento {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .failure-lists {
    grid-template-columns: 1fr;
  }

  .diag-metric-divider { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning { animation: none; }
  .status-bar-track i { transition: none; }
}
</style>
