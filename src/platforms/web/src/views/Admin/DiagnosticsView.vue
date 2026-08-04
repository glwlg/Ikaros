<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
    Activity,
    AlertTriangle,
    Loader2,
    MemoryStick,
    Package,
    ShieldCheck,
    Waypoints,
} from 'lucide-vue-next'

import { getAdminAudit, getDiagnostics } from '@/api/admin'

const route = useRoute()
const loading = ref(false)
const diagnostics = ref<Record<string, any> | null>(null)
const auditItems = ref<Array<Record<string, any>>>([])

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
  <div class="space-y-6 p-6 md:p-8">
    <section class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex items-center justify-between">
        <div>
          <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Diagnostics</div>
          <h2 class="mt-1 text-2xl font-semibold text-slate-900">运行诊断</h2>
          <p class="mt-2 text-sm leading-7 text-slate-500">
            这里不是原始 JSON 倾倒区，而是给管理员快速判断“当前能不能跑、哪里没配、最近谁改过、最近失败了什么”的入口。
          </p>
        </div>
        <button class="rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100" @click="load">
          刷新
        </button>
      </div>

      <div v-if="loading" class="mt-6 flex items-center gap-2 text-sm text-slate-500">
        <Loader2 class="h-4 w-4 animate-spin" />
        正在加载诊断信息
      </div>

      <template v-else-if="diagnostics">
        <div class="mt-6 grid gap-4 xl:grid-cols-4">
          <div class="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <div class="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <Activity class="h-4 w-4 text-cyan-600" />
              平台状态
            </div>
            <div class="mt-4 text-3xl font-semibold text-slate-950">
              {{ platformRows.filter(item => item.enabled).length }}
            </div>
            <div class="mt-1 text-sm text-slate-500">已启用平台</div>
          </div>

          <div class="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <div class="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <ShieldCheck class="h-4 w-4 text-emerald-600" />
              环境配置
            </div>
            <div class="mt-4 text-3xl font-semibold text-slate-950">
              {{ platformRows.filter(item => item.configured).length }}
            </div>
            <div class="mt-1 text-sm text-slate-500">已配置平台</div>
          </div>

          <div class="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
            <div class="flex items-center gap-2 text-sm font-semibold text-slate-900">
              <AlertTriangle class="h-4 w-4 text-rose-600" />
              失败 Turn
            </div>
            <div class="mt-4 text-3xl font-semibold text-slate-950">
              {{ failedTurnCount }}
            </div>
            <div class="mt-1 text-sm text-slate-500">最近采样 {{ totalTurns }} 次</div>
          </div>

          <div class="rounded-[24px] border border-slate-200 bg-slate-950 p-4 text-slate-100">
            <div class="flex items-center gap-2 text-sm font-semibold">
              <Package class="h-4 w-4 text-violet-300" />
              投递失败
            </div>
            <div class="mt-4 text-2xl font-semibold">{{ deliveryFailedCount }}</div>
            <div class="mt-1 text-sm text-slate-300">附件 / 消息 delivery</div>
          </div>
        </div>

        <div class="mt-6 grid gap-6 xl:grid-cols-2">
          <section class="rounded-[24px] border border-slate-200 bg-slate-50 p-5">
            <div class="text-sm font-semibold text-slate-900">平台诊断</div>
            <div class="mt-4 space-y-3">
              <div
                v-for="item in platformRows"
                :key="item.name"
                class="flex items-center justify-between rounded-2xl border border-slate-200 bg-white px-4 py-3"
              >
                <div>
                  <div class="text-sm font-medium text-slate-900">{{ item.name }}</div>
                  <div class="text-xs text-slate-500">
                    {{ item.configured ? '环境已配置' : '环境未配置' }}
                  </div>
                </div>
                <span class="rounded-full px-2.5 py-1 text-xs" :class="item.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'">
                  {{ item.enabled ? 'enabled' : 'disabled' }}
                </span>
              </div>
              <div v-if="!platformRows.length" class="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-6 text-center text-sm text-slate-500">
                暂无平台状态数据
              </div>
            </div>
          </section>

          <section class="rounded-[24px] border border-slate-200 bg-slate-50 p-5">
            <div class="text-sm font-semibold text-slate-900">配置与版本</div>
            <div class="mt-4 space-y-3">
              <div
                v-for="item in configRows"
                :key="item.key"
                class="rounded-2xl border border-slate-200 bg-white px-4 py-3"
              >
                <div class="flex items-center justify-between gap-3">
                  <div class="text-sm font-medium text-slate-900">{{ item.key }}</div>
                  <span
                    v-if="typeof item.value === 'boolean'"
                    class="rounded-full px-2.5 py-1 text-xs"
                    :class="item.value ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'"
                  >
                    {{ item.value ? 'ok' : 'missing' }}
                  </span>
                </div>
                <div class="mt-2 break-all text-xs leading-6 text-slate-500">{{ item.value }}</div>
              </div>

              <div class="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                <div class="text-sm font-medium text-slate-900">Git Head</div>
                <div class="mt-2 break-all text-xs leading-6 text-slate-500">{{ diagnostics.version?.git_head || 'unknown' }}</div>
              </div>

              <div class="rounded-2xl border border-slate-200 bg-white px-4 py-3">
                <div class="flex items-center gap-2 text-sm font-medium text-slate-900">
                  <MemoryStick class="h-4 w-4 text-violet-500" />
                  Memory
                </div>
                <div class="mt-2 text-xs leading-6 text-slate-500">
                  provider: {{ diagnostics.memory?.provider || 'unknown' }}
                  <br>
                  providers: {{ (diagnostics.memory?.providers || []).join(', ') || 'none' }}
                </div>
              </div>
            </div>
          </section>
        </div>
      </template>
    </section>

    <section
      id="runtime-failures"
      class="scroll-mt-24 rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm"
    >
      <div class="flex items-start justify-between gap-4">
        <div>
          <div class="flex items-center gap-2 text-sm font-semibold text-slate-900">
            <AlertTriangle class="h-4 w-4 text-rose-600" />
            运行质量 / 近期失败
          </div>
          <p class="mt-2 text-sm leading-6 text-slate-500">
            仅统计近 {{ quality?.window_days || 7 }} 天的 turn / delivery。首页「需要关注」与这里共用同一窗口，过期失败会自动消失。
          </p>
        </div>
        <div class="flex flex-wrap gap-2 text-xs">
          <span class="rounded-full bg-slate-100 px-3 py-1 text-slate-600">近 {{ quality?.window_days || 7 }} 天</span>
          <span class="rounded-full bg-slate-100 px-3 py-1 text-slate-600">采样 turns {{ totalTurns }}</span>
          <span class="rounded-full px-3 py-1" :class="failedTurnCount ? 'bg-rose-50 text-rose-700' : 'bg-emerald-50 text-emerald-700'">
            failed {{ failedTurnCount }}
          </span>
          <span class="rounded-full px-3 py-1" :class="deliveryFailedCount ? 'bg-rose-50 text-rose-700' : 'bg-emerald-50 text-emerald-700'">
            delivery fail {{ deliveryFailedCount }}
          </span>
        </div>
      </div>

      <div v-if="!quality && !loading" class="mt-6 rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-8 text-center text-sm text-slate-500">
        暂无 runtime quality 数据。
      </div>

      <template v-else-if="quality">
        <div class="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <div
            v-for="row in statusCountRows"
            :key="row.status"
            class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
          >
            <div class="text-xs uppercase tracking-wide text-slate-400">{{ row.status }}</div>
            <div class="mt-1 text-2xl font-semibold text-slate-900">{{ row.count }}</div>
          </div>
        </div>

        <div v-if="deliveryFailureCounts.length" class="mt-4 flex flex-wrap gap-2">
          <span
            v-for="item in deliveryFailureCounts"
            :key="item.key"
            class="rounded-full border border-rose-100 bg-rose-50 px-3 py-1 text-xs font-medium text-rose-700"
          >
            {{ item.key }} × {{ item.count }}
          </span>
        </div>

        <div class="mt-6 grid gap-6 xl:grid-cols-2">
          <section id="failed-turns" class="scroll-mt-24 rounded-[24px] border border-slate-200 bg-slate-50 p-5">
            <div class="text-sm font-semibold text-slate-900">失败 Turn</div>
            <p class="mt-1 text-xs text-slate-500">例如定时任务无输出、模型执行失败等。</p>
            <div class="mt-4 space-y-3">
              <article
                v-for="(item, index) in failedTurns"
                :key="`${item.turn_id || item.session_id}-${index}`"
                class="rounded-2xl border border-rose-100 bg-white px-4 py-3"
              >
                <div class="text-sm font-semibold text-rose-700">{{ item.error || 'failed' }}</div>
                <dl class="mt-2 grid gap-1 text-xs leading-6 text-slate-500">
                  <div v-if="item.updated_at"><span class="text-slate-400">time</span> · {{ item.updated_at }}</div>
                  <div><span class="text-slate-400">session</span> · <code class="break-all">{{ item.session_id || '—' }}</code></div>
                  <div><span class="text-slate-400">turn</span> · <code class="break-all">{{ item.turn_id || '—' }}</code></div>
                  <div><span class="text-slate-400">kernel</span> · {{ item.kernel_provider || '—' }}</div>
                </dl>
                <p class="mt-2 text-[11px] leading-5 text-slate-400">
                  若 session 以 <code>scheduler-task-</code> 开头，对应后台「任务调度」里的定时任务。
                </p>
              </article>
              <div v-if="!failedTurns.length" class="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-500">
                最近采样中没有失败 turn。
              </div>
            </div>
          </section>

          <section id="delivery-failures" class="scroll-mt-24 rounded-[24px] border border-slate-200 bg-slate-50 p-5">
            <div class="text-sm font-semibold text-slate-900">投递失败</div>
            <p class="mt-1 text-xs text-slate-500">消息/图片/文档推送到 Telegram 等渠道失败的记录。</p>
            <div class="mt-4 space-y-3">
              <article
                v-for="(item, index) in deliveryFailures"
                :key="`${item.turn_id || item.session_id}-${item.artifact_filename}-${index}`"
                class="rounded-2xl border border-rose-100 bg-white px-4 py-3"
              >
                <div class="text-sm font-semibold text-rose-700">{{ item.error || 'delivery failed' }}</div>
                <dl class="mt-2 grid gap-1 text-xs leading-6 text-slate-500">
                  <div v-if="item.updated_at"><span class="text-slate-400">time</span> · {{ item.updated_at }}</div>
                  <div><span class="text-slate-400">target</span> · {{ item.target || `${item.platform || '—'}` }}</div>
                  <div><span class="text-slate-400">kind</span> · {{ item.artifact_kind || '—' }} · {{ item.artifact_filename || '（无文件名）' }}</div>
                  <div><span class="text-slate-400">session</span> · <code class="break-all">{{ item.session_id || '—' }}</code></div>
                  <div v-if="item.turn_id"><span class="text-slate-400">turn</span> · <code class="break-all">{{ item.turn_id }}</code></div>
                </dl>
              </article>
              <div v-if="!deliveryFailures.length" class="rounded-2xl border border-dashed border-slate-200 bg-white px-4 py-8 text-center text-sm text-slate-500">
                最近没有投递失败记录。
              </div>
            </div>
          </section>
        </div>

        <div v-if="recommendations.length" class="mt-6 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-4">
          <div class="text-sm font-semibold text-slate-900">建议</div>
          <ul class="mt-2 list-disc space-y-1 pl-5 text-sm leading-6 text-slate-600">
            <li v-for="(tip, index) in recommendations" :key="index">{{ tip }}</li>
          </ul>
        </div>
      </template>
    </section>

    <section class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <Waypoints class="h-4 w-4 text-cyan-600" />
        管理员审计
      </div>
      <div class="mt-6 overflow-hidden rounded-[24px] border border-slate-200">
        <table class="min-w-full divide-y divide-slate-200 text-sm">
          <thead class="bg-slate-50 text-left text-slate-500">
            <tr>
              <th class="px-4 py-3 font-medium">时间</th>
              <th class="px-4 py-3 font-medium">Actor</th>
              <th class="px-4 py-3 font-medium">Action</th>
              <th class="px-4 py-3 font-medium">Summary</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 bg-white">
            <tr v-for="item in auditTable" :key="String(item.ts) + String(item.action)">
              <td class="px-4 py-4 text-slate-500">{{ item.ts }}</td>
              <td class="px-4 py-4 text-slate-700">{{ item.actor }}</td>
              <td class="px-4 py-4 text-slate-700">{{ item.action }}</td>
              <td class="px-4 py-4 text-slate-700">{{ item.summary }}</td>
            </tr>
          </tbody>
        </table>

        <div v-if="!auditTable.length && !loading" class="px-6 py-12 text-center text-sm text-slate-500">
          暂时还没有管理员审计记录。
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.ring-highlight {
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.25);
  transition: box-shadow 0.3s ease;
}
</style>
