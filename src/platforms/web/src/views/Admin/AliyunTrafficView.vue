<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref } from 'vue'
import {
    CalendarDays,
    CircleAlert,
    Cloud,
    Database,
    Gauge,
    Loader2,
    MapPin,
    RefreshCw,
} from 'lucide-vue-next'

import { getAliyunTraffic, type AliyunTrafficSummary } from '@/api/aliyunTraffic'
import { LiquidGlass } from '@/components/liquid-glass'

const summary = ref<AliyunTrafficSummary | null>(null)
const loading = ref(false)
const errorText = ref('')

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

const parseErrorMessage = (error: unknown) => {
    if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (typeof detail === 'string' && detail.trim()) return detail
    }
    if (error instanceof Error && error.message.trim()) return error.message
    return '阿里云流量查询失败'
}

const formatGb = (value: number) => new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 3,
}).format(Number(value || 0))

const formatPercent = (value: number) => new Intl.NumberFormat('zh-CN', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
}).format(Number(value || 0))

const formatDateTime = (value: string) => {
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return value || '—'
    return new Intl.DateTimeFormat('zh-CN', {
        timeZone: 'Asia/Shanghai',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    }).format(date)
}

const progressPercent = computed(() => Math.min(100, Math.max(0, summary.value?.usage_percent || 0)))
const progressStyle = computed<Record<string, string>>(() => ({
    '--traffic-progress': `${progressPercent.value}%`,
}))
const isOverQuota = computed(() => Number(summary.value?.overage_gb || 0) > 0)
const quotaStatus = computed(() => {
    if (!summary.value) return ''
    if (isOverQuota.value) return `已超出免费额度 ${formatGb(summary.value.overage_gb)} GB`
    return `剩余 ${formatGb(summary.value.remaining_gb)} GB`
})

const load = async () => {
    loading.value = true
    errorText.value = ''
    try {
        const response = await getAliyunTraffic()
        summary.value = response.data
    } catch (error) {
        errorText.value = parseErrorMessage(error)
    } finally {
        loading.value = false
    }
}

onMounted(load)
</script>

<template>
  <div class="ikaros-page aliyun-traffic-page">
    <header class="ikaros-page-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Admin · Cloud Traffic</p>
        <h1 class="ikaros-page-title">阿里云流量</h1>
        <p class="ikaros-page-description">查看 CDT 本月流量与 20 GB 免费额度使用情况。</p>
      </div>
      <button type="button" class="ikaros-secondary-action" :disabled="loading" @click="load">
        <Loader2 v-if="loading" class="is-spinning" />
        <RefreshCw v-else />
        刷新账单
      </button>
    </header>

    <div v-if="loading && !summary" class="traffic-loading ikaros-surface">
      <Loader2 class="is-spinning" />
      正在读取阿里云 CDT 账单
    </div>

    <LiquidGlass
      v-else-if="errorText && !summary"
      :radius="22"
      :optics="panelOptics"
      class="traffic-error"
    >
      <div class="traffic-error-content">
        <span class="traffic-error-icon"><CircleAlert /></span>
        <div>
          <h2>暂时无法查询流量</h2>
          <p>{{ errorText }}</p>
          <small>请确认运行 Ikaros 的系统用户可通过 Aliyun CLI 读取 Billing 明细。</small>
        </div>
      </div>
    </LiquidGlass>

    <template v-if="summary">
      <div v-if="errorText" class="traffic-inline-error">
        <CircleAlert />
        <span>{{ errorText }}</span>
      </div>

      <section class="traffic-overview">
        <LiquidGlass :radius="26" :optics="panelOptics" class="quota-panel">
          <div class="quota-panel-content">
            <div class="quota-copy">
              <span class="quota-chip"><Cloud /> CDT 免费额度</span>
              <p>本月剩余</p>
              <div class="quota-number" :class="{ 'is-over': isOverQuota }">
                <strong>{{ formatGb(summary.remaining_gb) }}</strong>
                <span>GB</span>
              </div>
              <small :class="{ 'is-over': isOverQuota }">{{ quotaStatus }}</small>
            </div>

            <div
              class="quota-ring"
              :class="{ 'is-over': isOverQuota }"
              :style="progressStyle"
              role="progressbar"
              aria-label="CDT 免费额度使用比例"
              :aria-valuenow="Math.round(summary.usage_percent)"
              aria-valuemin="0"
              aria-valuemax="100"
            >
              <div class="quota-ring-core">
                <strong>{{ formatPercent(summary.usage_percent) }}%</strong>
                <span>已使用</span>
              </div>
            </div>
          </div>

          <div class="quota-progress" :class="{ 'is-over': isOverQuota }">
            <i :style="{ width: `${progressPercent}%` }" />
          </div>
          <div class="quota-scale">
            <span>0 GB</span>
            <span>{{ formatGb(summary.quota_gb) }} GB</span>
          </div>
        </LiquidGlass>

        <div class="traffic-metrics">
          <LiquidGlass :radius="20" :optics="panelOptics" class="metric-card">
            <div class="metric-card-content">
              <span class="metric-icon is-pink"><Gauge /></span>
              <div>
                <p>本月已用</p>
                <strong>{{ formatGb(summary.used_gb) }} <small>GB</small></strong>
              </div>
            </div>
          </LiquidGlass>
          <LiquidGlass :radius="20" :optics="panelOptics" class="metric-card">
            <div class="metric-card-content">
              <span class="metric-icon is-green"><Database /></span>
              <div>
                <p>免费额度</p>
                <strong>{{ formatGb(summary.quota_gb) }} <small>GB</small></strong>
              </div>
            </div>
          </LiquidGlass>
          <LiquidGlass :radius="20" :optics="panelOptics" class="metric-card">
            <div class="metric-card-content">
              <span class="metric-icon is-teal"><CalendarDays /></span>
              <div>
                <p>账期</p>
                <strong class="metric-cycle">{{ summary.billing_cycle }}</strong>
              </div>
            </div>
          </LiquidGlass>
        </div>
      </section>

      <LiquidGlass :radius="24" :optics="panelOptics" class="traffic-detail-panel">
        <div class="traffic-detail-content">
          <div class="detail-heading">
            <div>
              <h2>流量明细</h2>
              <p>按计费项和地域汇总</p>
            </div>
            <span>更新于 {{ formatDateTime(summary.queried_at) }}</span>
          </div>

          <div v-if="summary.items.length" class="traffic-list">
            <article v-for="item in summary.items" :key="`${item.billing_item_code}:${item.region}`" class="traffic-item">
              <span class="traffic-item-icon"><MapPin /></span>
              <div class="traffic-item-copy">
                <strong>{{ item.billing_item }}</strong>
                <small>
                  {{ item.region === 'global' ? '全局' : item.region }}
                  <template v-if="item.billing_item_code"> · {{ item.billing_item_code }}</template>
                </small>
              </div>
              <div class="traffic-item-value">
                <strong>{{ formatGb(item.usage_gb) }}</strong>
                <span>GB</span>
              </div>
            </article>
          </div>
          <div v-else class="traffic-empty">本月尚无 CDT 流量账单明细。</div>
        </div>
      </LiquidGlass>
    </template>
  </div>
</template>

<style scoped>
.aliyun-traffic-page {
  width: min(1180px, 100%);
}

.ikaros-secondary-action:disabled {
  cursor: wait;
  opacity: 0.65;
}

.ikaros-secondary-action svg,
.traffic-inline-error svg {
  width: 17px;
  height: 17px;
}

.is-spinning {
  animation: traffic-spin 900ms linear infinite;
}

.traffic-loading {
  display: flex;
  min-height: 180px;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--ikaros-copy);
  font-size: 14px;
}

.traffic-loading svg {
  width: 20px;
  height: 20px;
  color: var(--ikaros-pink);
}

.traffic-error {
  --ikaros-glass-fill: rgba(255, 247, 247, 0.84);
}

.dark .traffic-error {
  --ikaros-glass-fill: rgba(54, 31, 35, 0.84);
}

.traffic-error-content {
  display: flex;
  gap: 16px;
  padding: 24px;
}

.traffic-error-icon {
  display: grid;
  width: 42px;
  height: 42px;
  flex: none;
  place-items: center;
  border-radius: 13px;
  background: rgba(198, 55, 65, 0.11);
  color: #c63741;
}

.traffic-error-icon svg {
  width: 21px;
  height: 21px;
}

.traffic-error h2,
.traffic-detail-panel h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 17px;
  font-weight: 780;
}

.traffic-error p {
  margin: 7px 0 0;
  color: #c63741;
  font-size: 14px;
}

.traffic-error small {
  display: block;
  margin-top: 8px;
  color: var(--ikaros-muted);
  font-size: 12px;
  line-height: 1.6;
}

.traffic-inline-error {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 11px 14px;
  border: 1px solid rgba(198, 55, 65, 0.18);
  border-radius: 13px;
  background: rgba(198, 55, 65, 0.08);
  color: #c63741;
  font-size: 13px;
  font-weight: 650;
}

.traffic-overview {
  display: grid;
  grid-template-columns: minmax(0, 1.8fr) minmax(260px, 0.8fr);
  gap: 18px;
}

.quota-panel {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.88);
}

.dark .quota-panel {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.9);
}

.quota-panel-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 28px;
  padding: 28px 30px 24px;
}

.quota-copy {
  min-width: 0;
}

.quota-chip {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  gap: 7px;
  padding: 0 10px;
  border-radius: 999px;
  background: rgba(232, 93, 142, 0.11);
  color: var(--ikaros-pink-dark);
  font-size: 12px;
  font-weight: 760;
}

.quota-chip svg {
  width: 15px;
  height: 15px;
}

.quota-copy > p {
  margin: 24px 0 4px;
  color: var(--ikaros-muted);
  font-size: 13px;
  font-weight: 650;
}

.quota-number {
  display: flex;
  align-items: baseline;
  gap: 8px;
  color: var(--ikaros-ink);
}

.quota-number strong {
  font-size: clamp(46px, 6vw, 72px);
  font-weight: 780;
  letter-spacing: -0.065em;
  line-height: 1;
}

.quota-number span {
  color: var(--ikaros-muted);
  font-size: 16px;
  font-weight: 750;
}

.quota-number.is-over,
.quota-copy > small.is-over {
  color: #c63741;
}

.quota-copy > small {
  display: block;
  margin-top: 10px;
  color: var(--ikaros-rind);
  font-size: 13px;
  font-weight: 720;
}

.quota-ring {
  display: grid;
  width: 154px;
  height: 154px;
  flex: none;
  place-items: center;
  border-radius: 50%;
  background: conic-gradient(var(--ikaros-pink) var(--traffic-progress), rgba(232, 93, 142, 0.12) 0);
  box-shadow: 0 16px 34px rgba(232, 93, 142, 0.13);
}

.quota-ring.is-over {
  background: conic-gradient(#c63741 var(--traffic-progress), rgba(198, 55, 65, 0.12) 0);
  box-shadow: 0 16px 34px rgba(198, 55, 65, 0.13);
}

.quota-ring-core {
  display: grid;
  width: 116px;
  height: 116px;
  place-content: center;
  border: 1px solid var(--ikaros-line);
  border-radius: 50%;
  background: var(--ikaros-glass-strong);
  text-align: center;
}

.quota-ring-core strong {
  color: var(--ikaros-ink);
  font-size: 24px;
  font-weight: 780;
  letter-spacing: -0.035em;
}

.quota-ring-core span {
  margin-top: 3px;
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 650;
}

.quota-progress {
  height: 7px;
  margin: 0 30px;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(232, 93, 142, 0.1);
}

.quota-progress i {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--ikaros-pink), #c94f7b);
  transition: width 360ms ease;
}

.quota-progress.is-over i {
  background: #c63741;
}

.quota-scale {
  display: flex;
  justify-content: space-between;
  padding: 8px 30px 25px;
  color: var(--ikaros-muted);
  font-size: 11px;
}

.traffic-metrics {
  display: grid;
  gap: 12px;
}

.metric-card {
  min-height: 0;
}

.metric-card-content {
  display: flex;
  height: 100%;
  align-items: center;
  gap: 14px;
  padding: 18px;
}

.metric-icon {
  display: grid;
  width: 40px;
  height: 40px;
  flex: none;
  place-items: center;
  border-radius: 12px;
}

.metric-icon svg {
  width: 19px;
  height: 19px;
}

.metric-icon.is-pink { background: rgba(232, 93, 142, 0.11); color: var(--ikaros-pink); }
.metric-icon.is-green { background: rgba(47, 125, 74, 0.11); color: var(--ikaros-rind); }
.metric-icon.is-teal { background: rgba(42, 140, 138, 0.11); color: var(--ikaros-eye); }

.metric-card p {
  margin: 0 0 4px;
  color: var(--ikaros-muted);
  font-size: 12px;
  font-weight: 650;
}

.metric-card strong {
  color: var(--ikaros-ink);
  font-size: 22px;
  font-weight: 770;
  letter-spacing: -0.03em;
}

.metric-card strong small {
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 680;
}

.metric-card .metric-cycle {
  font-size: 18px;
  letter-spacing: -0.01em;
}

.traffic-detail-content {
  padding: 24px;
}

.detail-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--ikaros-line);
}

.detail-heading p {
  margin: 5px 0 0;
  color: var(--ikaros-muted);
  font-size: 12px;
}

.detail-heading > span {
  color: var(--ikaros-muted);
  font-size: 12px;
}

.traffic-list {
  display: grid;
}

.traffic-item {
  display: flex;
  align-items: center;
  gap: 13px;
  min-height: 70px;
  border-bottom: 1px solid var(--ikaros-line);
}

.traffic-item:last-child {
  border-bottom: 0;
}

.traffic-item-icon {
  display: grid;
  width: 36px;
  height: 36px;
  flex: none;
  place-items: center;
  border-radius: 11px;
  background: rgba(42, 140, 138, 0.1);
  color: var(--ikaros-eye);
}

.traffic-item-icon svg {
  width: 17px;
  height: 17px;
}

.traffic-item-copy {
  display: grid;
  min-width: 0;
  flex: 1;
}

.traffic-item-copy strong {
  overflow: hidden;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 720;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.traffic-item-copy small {
  margin-top: 4px;
  overflow: hidden;
  color: var(--ikaros-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.traffic-item-value {
  display: flex;
  align-items: baseline;
  gap: 5px;
  color: var(--ikaros-ink);
}

.traffic-item-value strong {
  font-size: 17px;
  font-weight: 770;
}

.traffic-item-value span {
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 650;
}

.traffic-empty {
  padding: 42px 16px 24px;
  color: var(--ikaros-muted);
  font-size: 13px;
  text-align: center;
}

@keyframes traffic-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 900px) {
  .traffic-overview {
    grid-template-columns: 1fr;
  }

  .traffic-metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .quota-panel-content {
    align-items: flex-start;
    padding: 23px 20px 20px;
  }

  .quota-ring {
    width: 118px;
    height: 118px;
  }

  .quota-ring-core {
    width: 88px;
    height: 88px;
  }

  .quota-ring-core strong {
    font-size: 19px;
  }

  .quota-number strong {
    font-size: 48px;
  }

  .quota-progress {
    margin: 0 20px;
  }

  .quota-scale {
    padding: 8px 20px 21px;
  }

  .traffic-metrics {
    grid-template-columns: 1fr;
  }

  .metric-card-content {
    min-height: 72px;
  }

  .detail-heading {
    display: grid;
  }
}

@media (max-width: 460px) {
  .quota-panel-content {
    display: grid;
  }

  .quota-ring {
    justify-self: center;
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning { animation-duration: 1ms; }
  .quota-progress i { transition-duration: 1ms; }
}
</style>
