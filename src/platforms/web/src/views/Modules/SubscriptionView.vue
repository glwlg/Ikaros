<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import {
    BellRing,
    CalendarClock,
    CheckCircle2,
    CircleAlert,
    Clock3,
    Loader2,
    Pencil,
    Plus,
    RefreshCw,
    Trash2,
    X,
} from 'lucide-vue-next'

import { listMyBindings, type ChannelBinding } from '@/api/binding'
import {
    createSubscription,
    deleteSubscription,
    listSubscriptions,
    updateSubscription,
} from '@/api/subscriptions'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import type { SubscriptionPayload, SubscriptionRecord } from '@/types/subscription'

type SubscriptionForm = SubscriptionPayload
type StatusFilter = 'all' | 'due' | 'month' | 'expired'

const categoryOptions = ['AI 会员', 'VPS / 云服务', '视频会员', '软件服务', '域名 / 证书', '其他']
const cycleOptions = [
    { months: 1, label: '月' },
    { months: 3, label: '季度' },
    { months: 6, label: '半年' },
    { months: 12, label: '年' },
]
const platformLabels: Record<string, string> = {
    telegram: 'Telegram',
    weixin: '微信 / 企微',
    dingtalk: '钉钉',
    discord: 'Discord',
}

const localDateIso = (value = new Date()) => {
    const year = value.getFullYear()
    const month = String(value.getMonth() + 1).padStart(2, '0')
    const day = String(value.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
}

const addMonths = (source: string, months: number) => {
    const parts = source.split('-').map(Number)
    if (parts.length !== 3 || parts.some(part => !Number.isFinite(part))) return ''
    const [year, month, day] = parts as [number, number, number]
    const targetStart = new Date(year, month - 1 + months, 1)
    const lastDay = new Date(
        targetStart.getFullYear(),
        targetStart.getMonth() + 1,
        0,
    ).getDate()
    return localDateIso(new Date(
        targetStart.getFullYear(),
        targetStart.getMonth(),
        Math.min(day, lastDay),
    ))
}

const emptyForm = (): SubscriptionForm => {
    const start = localDateIso()
    return {
        name: '',
        category: 'AI 会员',
        provider: '',
        cost: '',
        start_date: start,
        cycle_months: 1,
        expiry_date: addMonths(start, 1),
        reminder_enabled: true,
        reminder_days_before: 3,
        delivery_platform: undefined,
        notes: '',
    }
}

const subscriptions = ref<SubscriptionRecord[]>([])
const bindings = ref<ChannelBinding[]>([])
const loading = ref(false)
const refreshing = ref(false)
const saving = ref(false)
const deletingId = ref<number | null>(null)
const showDialog = ref(false)
const editingId = ref<number | null>(null)
const errorText = ref('')
const form = ref<SubscriptionForm>(emptyForm())
const activeFilter = ref<StatusFilter>('all')

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

const preferredPlatform = computed(() => {
    for (const platform of ['telegram', 'weixin', 'dingtalk', 'discord']) {
        if (bindings.value.some(binding => binding.platform === platform)) return platform
    }
    return bindings.value[0]?.platform
})

const totalCount = computed(() => subscriptions.value.length)
const renewalDueCount = computed(() =>
    subscriptions.value.filter(item => item.status === 'renewal_due').length
)
const expiringThirtyCount = computed(() =>
    subscriptions.value.filter(item => item.days_remaining >= 0 && item.days_remaining <= 30).length
)
const expiredCount = computed(() =>
    subscriptions.value.filter(item => item.status === 'expired').length
)

const filterTabs = computed(() => [
    { key: 'all' as StatusFilter, label: '全部', count: totalCount.value },
    { key: 'due' as StatusFilter, label: '到提醒日', count: renewalDueCount.value },
    { key: 'month' as StatusFilter, label: '30 天内', count: expiringThirtyCount.value },
    { key: 'expired' as StatusFilter, label: '已过期', count: expiredCount.value },
])

const filteredSubscriptions = computed(() => {
    if (activeFilter.value === 'due') {
        return subscriptions.value.filter(item => item.status === 'renewal_due')
    }
    if (activeFilter.value === 'month') {
        return subscriptions.value.filter(item => item.days_remaining >= 0 && item.days_remaining <= 30)
    }
    if (activeFilter.value === 'expired') {
        return subscriptions.value.filter(item => item.status === 'expired')
    }
    return subscriptions.value
})

const parseError = (error: unknown, fallback: string) => {
    if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (typeof detail === 'string' && detail.trim()) return detail
        if (Array.isArray(detail) && detail.length) return String(detail[0]?.msg || fallback)
    }
    return fallback
}

const load = async (isRefresh = false) => {
    if (isRefresh) refreshing.value = true
    else loading.value = true
    errorText.value = ''
    try {
        const [subscriptionsResponse, bindingsResponse] = await Promise.all([
            listSubscriptions(),
            listMyBindings(),
        ])
        subscriptions.value = Array.isArray(subscriptionsResponse.data)
            ? subscriptionsResponse.data
            : []
        bindings.value = Array.isArray(bindingsResponse.data) ? bindingsResponse.data : []
    } catch (error) {
        errorText.value = parseError(error, '订阅信息加载失败')
    } finally {
        loading.value = false
        refreshing.value = false
    }
}

const recalculateExpiry = () => {
    const months = Number(form.value.cycle_months)
    if (form.value.start_date && Number.isInteger(months) && months > 0) {
        form.value.expiry_date = addMonths(form.value.start_date, months)
    }
}

const setCycle = (months: number) => {
    form.value.cycle_months = months
    recalculateExpiry()
}

const openCreate = () => {
    editingId.value = null
    form.value = emptyForm()
    form.value.delivery_platform = preferredPlatform.value
    errorText.value = ''
    showDialog.value = true
}

const openEdit = (item: SubscriptionRecord) => {
    editingId.value = item.id
    form.value = {
        name: item.name,
        category: item.category,
        provider: item.provider,
        cost: item.cost,
        start_date: item.start_date,
        cycle_months: item.cycle_months,
        expiry_date: item.expiry_date,
        reminder_enabled: item.reminder_enabled,
        reminder_days_before: item.reminder_days_before,
        delivery_platform: item.delivery_platform || preferredPlatform.value,
        notes: item.notes,
    }
    errorText.value = ''
    showDialog.value = true
}

const closeDialog = () => {
    if (saving.value) return
    showDialog.value = false
    editingId.value = null
    form.value = emptyForm()
}

const save = async () => {
    errorText.value = ''
    const months = Number(form.value.cycle_months)
    const reminderDays = Number(form.value.reminder_days_before)
    if (!form.value.name.trim()) {
        errorText.value = '请填写订阅名称。'
        return
    }
    if (!Number.isInteger(months) || months < 1 || months > 1200) {
        errorText.value = '订阅周期必须是 1 到 1200 之间的整数月。'
        return
    }
    if (!Number.isInteger(reminderDays) || reminderDays < 0 || reminderDays > 3650) {
        errorText.value = '提前提醒天数必须是 0 到 3650 之间的整数。'
        return
    }
    if (!form.value.start_date || !form.value.expiry_date) {
        errorText.value = '请填写开始日期和到期日期。'
        return
    }
    if (form.value.expiry_date < form.value.start_date) {
        errorText.value = '到期日期不能早于开始日期。'
        return
    }

    const payload: SubscriptionPayload = {
        ...form.value,
        name: form.value.name.trim(),
        category: form.value.category.trim() || '其他',
        provider: form.value.provider.trim(),
        cost: form.value.cost.trim(),
        cycle_months: months,
        reminder_days_before: reminderDays,
        delivery_platform: form.value.delivery_platform || undefined,
        notes: form.value.notes.trim(),
    }
    saving.value = true
    try {
        if (editingId.value) await updateSubscription(editingId.value, payload)
        else await createSubscription(payload)
        saving.value = false
        closeDialog()
        await load()
    } catch (error) {
        errorText.value = parseError(error, '订阅保存失败')
    } finally {
        saving.value = false
    }
}

const remove = async (item: SubscriptionRecord) => {
    if (!confirm(`确定删除“${item.name}”吗？`)) return
    deletingId.value = item.id
    errorText.value = ''
    try {
        await deleteSubscription(item.id)
        await load()
    } catch (error) {
        errorText.value = parseError(error, '订阅删除失败')
    } finally {
        deletingId.value = null
    }
}

const formatDate = (value: string) => {
    const [year, month, day] = value.split('-')
    return year && month && day ? `${year}年${Number(month)}月${Number(day)}日` : value
}

const cycleLabel = (months: number) => {
    const option = cycleOptions.find(item => item.months === months)
    return option ? `每${option.label}` : `每 ${months} 个月`
}

const statusLabel = (item: SubscriptionRecord) => {
    if (item.status === 'expired') return `已过期 ${Math.abs(item.days_remaining)} 天`
    if (item.days_remaining === 0) return '今天到期'
    if (item.status === 'renewal_due') return `${item.days_remaining} 天后到期`
    return `${item.days_remaining} 天后到期`
}

const statusTone = (item: SubscriptionRecord) => {
    if (item.status === 'expired') return 'is-expired'
    if (item.status === 'renewal_due') return 'is-due'
    return 'is-normal'
}

onMounted(load)
</script>

<template>
  <div class="ikaros-page subscription-page">
    <header class="ikaros-page-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Renewals</p>
        <h1 class="ikaros-page-title">续费订阅</h1>
        <p class="ikaros-page-description">记录周期性费用与服务，到期前通过消息渠道提醒你。</p>
      </div>
      <div class="header-actions">
        <button
          type="button"
          class="ikaros-secondary-action refresh-button"
          :disabled="refreshing"
          title="刷新"
          @click="load(true)"
        >
          <RefreshCw :class="{ 'is-spinning': refreshing }" />
          刷新
        </button>
        <button type="button" class="ikaros-primary-action create-button" @click="openCreate">
          <Plus />
          添加订阅
        </button>
      </div>
    </header>

    <div v-if="!bindings.length && !loading" class="notice-banner">
      <CircleAlert />
      <div class="notice-copy">
        <strong>当前未绑定通知渠道，无法接收续费提醒</strong>
        <p>订阅可以正常保存，但到期提醒暂时无法送达。</p>
      </div>
      <RouterLink to="/bindings" class="notice-link">去绑定</RouterLink>
    </div>

    <div v-if="errorText && !showDialog" class="error-banner">
      {{ errorText }}
    </div>

    <div class="filter-tabs" role="tablist">
      <button
        v-for="tab in filterTabs"
        :key="tab.key"
        type="button"
        role="tab"
        class="filter-tab"
        :class="{ 'is-active': activeFilter === tab.key }"
        :aria-selected="activeFilter === tab.key"
        @click="activeFilter = tab.key"
      >
        {{ tab.label }} ({{ tab.count }})
      </button>
    </div>

    <LiquidGlass :radius="24" :optics="panelOptics" class="subscription-panel">
      <div class="panel-shell">
        <header class="panel-header">
          <h2>订阅列表</h2>
          <span class="panel-count">{{ filteredSubscriptions.length }} 项</span>
        </header>

        <div v-if="loading" class="panel-loading">
          <Loader2 class="is-spinning" />
        </div>

        <div v-else-if="!subscriptions.length" class="panel-empty">
          <CalendarClock />
          <div>
            <strong>还没有订阅记录</strong>
            <p>添加第一个周期服务，Ikaros 会根据到期日主动提醒你。</p>
          </div>
        </div>

        <div v-else-if="!filteredSubscriptions.length" class="panel-empty is-compact">
          <span>该分组暂无订阅</span>
        </div>

        <template v-else>
          <div class="sub-head">
            <span>订阅</span>
            <span>费用</span>
            <span>到期日</span>
            <span>周期</span>
            <span>提醒</span>
            <span>状态</span>
            <span class="is-right">操作</span>
          </div>

          <div class="sub-list">
            <article v-for="item in filteredSubscriptions" :key="item.id" class="sub-row">
              <div class="sub-cell sub-name">
                <div class="sub-name-head">
                  <h4>{{ item.name }}</h4>
                  <span class="sub-category">{{ item.category }}</span>
                </div>
                <p class="sub-provider">
                  {{ item.provider || '未填写服务商' }}<template v-if="item.notes"> · {{ item.notes }}</template>
                </p>
              </div>

              <div class="sub-cell sub-cost">
                <span class="cell-strong">{{ item.cost || '—' }}</span>
              </div>

              <div class="sub-cell sub-expiry">
                <span class="cell-strong">{{ formatDate(item.expiry_date) }}</span>
                <span class="cell-sub">始于 {{ item.start_date }}</span>
              </div>

              <div class="sub-cell sub-cycle">
                <span class="cell-strong">{{ cycleLabel(item.cycle_months) }}</span>
              </div>

              <div class="sub-cell sub-reminder">
                <span class="cell-strong">
                  {{ item.reminder_enabled ? `提前 ${item.reminder_days_before} 天` : '已关闭' }}
                </span>
                <span class="cell-sub">
                  {{ item.delivery_configured ? (platformLabels[item.delivery_platform] || item.delivery_platform) : '未配置消息渠道' }}
                </span>
              </div>

              <div class="sub-cell sub-status">
                <span class="status-chip" :class="statusTone(item)">
                  <span class="status-dot" />
                  {{ statusLabel(item) }}
                </span>
                <span class="cell-sub">
                  <span v-if="item.last_reminded_at" class="reminded-flag">
                    <CheckCircle2 />
                    本期已提醒
                  </span>
                  <span v-else>提醒日 {{ item.reminder_date }}</span>
                </span>
              </div>

              <div class="sub-cell row-actions">
                <button type="button" title="编辑" @click="openEdit(item)">
                  <Pencil />
                </button>
                <button
                  type="button"
                  title="删除"
                  class="is-danger"
                  :disabled="deletingId === item.id"
                  @click="remove(item)"
                >
                  <Loader2 v-if="deletingId === item.id" class="is-spinning" />
                  <Trash2 v-else />
                </button>
              </div>
            </article>
          </div>
        </template>
      </div>
    </LiquidGlass>

    <div v-if="showDialog" class="modal-layer" @click.self="closeDialog">
      <LiquidGlass :radius="24" :optics="panelOptics" class="modal-panel">
        <header class="modal-header">
          <h2>{{ editingId ? '编辑订阅' : '添加订阅' }}</h2>
          <button type="button" class="modal-close" title="关闭" @click="closeDialog">
            <X />
          </button>
        </header>

        <form class="modal-body" @submit.prevent="save">
          <div class="form-grid">
            <label class="field-group is-full">
              <span class="field-label">订阅名称 <b class="field-required">*</b></span>
              <input
                v-model="form.name"
                type="text"
                maxlength="120"
                class="field-input"
                placeholder="例如：ChatGPT Plus、搬瓦工 VPS"
                autofocus
              >
            </label>

            <label class="field-group">
              <span class="field-label">分类</span>
              <input
                v-model="form.category"
                type="text"
                maxlength="60"
                list="subscription-categories"
                class="field-input"
              >
              <datalist id="subscription-categories">
                <option v-for="category in categoryOptions" :key="category" :value="category" />
              </datalist>
            </label>

            <label class="field-group">
              <span class="field-label">服务商</span>
              <input
                v-model="form.provider"
                type="text"
                maxlength="120"
                class="field-input"
                placeholder="可选"
              >
            </label>

            <label class="field-group is-full">
              <span class="field-label">费用</span>
              <input
                v-model="form.cost"
                type="text"
                maxlength="64"
                class="field-input"
                placeholder="例如：¥98 / 月、20 USD / 月（可选）"
              >
            </label>
          </div>

          <div class="form-section">
            <div class="section-title">
              <RefreshCw />
              订阅周期
            </div>
            <div class="cycle-row">
              <button
                v-for="option in cycleOptions"
                :key="option.months"
                type="button"
                class="cycle-option"
                :class="{ 'is-active': form.cycle_months === option.months }"
                @click="setCycle(option.months)"
              >
                {{ option.label }}
              </button>
              <label class="cycle-custom">
                每
                <input
                  v-model.number="form.cycle_months"
                  type="number"
                  min="1"
                  max="1200"
                  step="1"
                  class="field-input cycle-input"
                  @change="recalculateExpiry"
                >
                个月
              </label>
            </div>
          </div>

          <div class="form-grid">
            <label class="field-group">
              <span class="field-label">开始日期</span>
              <input
                v-model="form.start_date"
                type="date"
                class="field-input"
                @change="recalculateExpiry"
              >
            </label>
            <label class="field-group">
              <span class="field-label is-split">
                <span>到期日期</span>
                <button type="button" class="inline-action" @click="recalculateExpiry">按周期重算</button>
              </span>
              <input v-model="form.expiry_date" type="date" class="field-input is-expiry">
              <span class="field-hint">可直接修改，以服务商给出的实际日期为准。</span>
            </label>
          </div>

          <div class="form-section">
            <label class="reminder-toggle">
              <div>
                <div class="section-title">
                  <BellRing />
                  到期提醒
                </div>
                <p class="field-hint">同一个到期日只会成功推送一次。</p>
              </div>
              <input v-model="form.reminder_enabled" type="checkbox" class="reminder-checkbox">
            </label>

            <div v-if="form.reminder_enabled" class="form-grid reminder-fields">
              <label class="field-group">
                <span class="field-label">提前多少天</span>
                <span class="days-input">
                  <input
                    v-model.number="form.reminder_days_before"
                    type="number"
                    min="0"
                    max="3650"
                    step="1"
                    class="field-input"
                  >
                  <span class="days-suffix">天</span>
                </span>
              </label>
              <label class="field-group">
                <span class="field-label">消息渠道</span>
                <select v-model="form.delivery_platform" :disabled="!bindings.length" class="field-input">
                  <option v-if="!bindings.length" :value="undefined">尚未绑定渠道</option>
                  <option v-for="binding in bindings" :key="binding.id" :value="binding.platform">
                    {{ platformLabels[binding.platform] || binding.platform }}
                  </option>
                </select>
              </label>
            </div>
          </div>

          <label class="field-group">
            <span class="field-label">备注</span>
            <textarea
              v-model="form.notes"
              rows="3"
              maxlength="1000"
              class="field-textarea"
              placeholder="套餐、账号、续费注意事项等（可选）"
            />
          </label>

          <div v-if="errorText" class="form-error">
            <CircleAlert />
            {{ errorText }}
          </div>

          <footer class="modal-footer">
            <button type="button" class="ikaros-secondary-action" @click="closeDialog">取消</button>
            <button type="submit" class="ikaros-primary-action submit-button" :disabled="saving">
              <Loader2 v-if="saving" class="is-spinning" />
              <Clock3 v-else />
              {{ saving ? '保存中' : '保存订阅' }}
            </button>
          </footer>
        </form>
      </LiquidGlass>
    </div>
  </div>
</template>

<style scoped>
.subscription-page {
  width: min(1440px, 100%);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-actions svg,
.submit-button svg {
  width: 16px;
  height: 16px;
}

.refresh-button .is-spinning,
.submit-button .is-spinning,
.row-actions .is-spinning {
  animation: subscription-spin 850ms linear infinite;
}

.notice-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 16px;
  border: 1px solid rgba(200, 120, 32, 0.2);
  border-radius: 16px;
  background: rgba(200, 120, 32, 0.08);
  color: #b86717;
}

.notice-banner > svg {
  width: 19px;
  height: 19px;
  flex: none;
}

.notice-copy {
  min-width: 0;
  flex: 1;
}

.notice-copy strong {
  font-size: 13px;
  font-weight: 750;
}

.notice-copy p {
  margin: 3px 0 0;
  font-size: 12px;
  opacity: 0.85;
}

.notice-link {
  flex: none;
  color: var(--ikaros-pink);
  font-size: 13px;
  font-weight: 750;
  text-decoration: none;
}

.notice-link:hover {
  text-decoration: underline;
}

.error-banner {
  padding: 13px 16px;
  border: 1px solid rgba(198, 55, 65, 0.18);
  border-radius: 16px;
  background: rgba(198, 55, 65, 0.08);
  color: #c63741;
  font-size: 13px;
}

.filter-tabs {
  display: inline-flex;
  flex-wrap: wrap;
  gap: 4px;
  width: fit-content;
  padding: 4px;
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 13px;
  background: var(--ikaros-glass-fill);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(16px) saturate(140%);
  -webkit-backdrop-filter: blur(16px) saturate(140%);
}

.filter-tab {
  min-height: 32px;
  padding: 0 13px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 650;
}

.filter-tab:hover {
  color: var(--ikaros-ink);
}

.filter-tab.is-active {
  background: #fff;
  color: var(--ikaros-ink);
  box-shadow: 0 2px 8px rgba(23, 19, 26, 0.08);
  font-weight: 750;
}

:global(.dark) .filter-tab.is-active {
  background: rgba(255, 255, 255, 0.1);
}

.subscription-panel {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .subscription-panel {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.86);
}

.panel-shell {
  padding: 20px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.panel-header h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.panel-count {
  flex: none;
  padding: 4px 10px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 750;
}

.panel-loading {
  display: flex;
  min-height: 220px;
  align-items: center;
  justify-content: center;
  color: var(--ikaros-pink);
}

.panel-loading svg {
  width: 26px;
  height: 26px;
}

.panel-loading .is-spinning {
  animation: subscription-spin 850ms linear infinite;
}

.panel-empty {
  display: flex;
  min-height: 200px;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-top: 18px;
  border: 1px dashed var(--ikaros-line);
  border-radius: 16px;
  color: var(--ikaros-copy);
}

.panel-empty > svg {
  width: 22px;
  height: 22px;
  flex: none;
  color: var(--ikaros-muted);
}

.panel-empty strong {
  color: var(--ikaros-ink);
  font-size: 13px;
}

.panel-empty p {
  margin: 4px 0 0;
  color: var(--ikaros-muted);
  font-size: 12px;
}

.panel-empty.is-compact {
  min-height: 120px;
  font-size: 12px;
}

.sub-head,
.sub-row {
  display: grid;
  grid-template-columns: minmax(180px, 1.6fr) 100px 145px 80px 130px 120px 76px;
  align-items: center;
  gap: 14px;
}

.sub-head {
  margin-top: 18px;
  padding: 0 14px 9px;
  border-bottom: 1px solid var(--ikaros-line);
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
}

.sub-head .is-right {
  text-align: right;
}

.sub-list {
  display: grid;
}

.sub-row {
  padding: 11px 14px;
  border-bottom: 1px solid var(--ikaros-line);
}

.sub-row:last-child {
  border-bottom: 0;
}

.sub-cell {
  min-width: 0;
}

.sub-name-head {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.sub-name-head h4 {
  margin: 0;
  overflow: hidden;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sub-category {
  flex: none;
  padding: 2px 8px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  color: var(--ikaros-copy);
  font-size: 10px;
  font-weight: 650;
}

.sub-provider {
  margin: 4px 0 0;
  overflow: hidden;
  color: var(--ikaros-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cell-strong {
  display: block;
  overflow: hidden;
  color: var(--ikaros-ink);
  font-size: 12px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.cell-sub {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: var(--ikaros-muted);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  font-weight: 700;
  white-space: nowrap;
}

.status-chip.is-normal {
  color: var(--ikaros-rind);
}

.status-chip.is-due {
  color: #b86717;
}

.status-chip.is-expired {
  color: #c63741;
}

.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.status-chip.is-normal .status-dot {
  box-shadow: 0 0 0 3px rgba(47, 125, 74, 0.12);
}

.reminded-flag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--ikaros-rind);
}

.reminded-flag svg {
  width: 12px;
  height: 12px;
}

.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}

.row-actions button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--ikaros-muted);
}

.row-actions button:hover {
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.row-actions button.is-danger:hover {
  background: rgba(198, 55, 65, 0.1);
  color: #c63741;
}

.row-actions button:disabled {
  opacity: 0.55;
}

.row-actions svg {
  width: 15px;
  height: 15px;
}

.modal-layer {
  position: fixed;
  z-index: 100;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(23, 19, 26, 0.24);
  backdrop-filter: blur(7px);
  -webkit-backdrop-filter: blur(7px);
}

.modal-panel {
  width: min(640px, 100%);
  max-height: calc(100vh - 40px);
  --ikaros-glass-fill: rgba(255, 249, 252, 0.93);
}

:global(.dark) .modal-panel {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.95);
}

.modal-panel :global(.liquid-glass__content) {
  display: flex;
  max-height: calc(100vh - 40px);
  flex-direction: column;
}

.modal-header {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--ikaros-line);
}

.modal-header h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.modal-close {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--ikaros-muted);
}

.modal-close:hover {
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.modal-close svg {
  width: 16px;
  height: 16px;
}

.modal-body {
  display: grid;
  gap: 18px;
  padding: 20px;
  overflow-y: auto;
}

.form-grid {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.field-group {
  display: grid;
  min-width: 0;
  gap: 8px;
}

.field-group.is-full {
  grid-column: 1 / -1;
}

.field-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 750;
}

.field-required {
  color: #c63741;
}

.field-input,
.field-textarea {
  width: 100%;
  border: 1px solid var(--ikaros-line);
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.55);
  padding: 10px 13px;
  color: var(--ikaros-ink);
  font-size: 13px;
  line-height: 1.5;
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

:global(.dark) .field-input,
:global(.dark) .field-textarea {
  background: rgba(255, 255, 255, 0.06);
}

.field-textarea {
  resize: none;
}

.field-input:focus,
.field-textarea:focus {
  border-color: rgba(232, 93, 142, 0.45);
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.12);
}

.field-input.is-expiry {
  border-color: rgba(232, 93, 142, 0.3);
  background: rgba(232, 93, 142, 0.05);
  font-weight: 650;
}

.field-hint {
  margin: 0;
  color: var(--ikaros-muted);
  font-size: 11px;
  line-height: 1.5;
}

.inline-action {
  border: 0;
  background: transparent;
  color: var(--ikaros-pink);
  font-size: 11px;
  font-weight: 700;
  padding: 0;
}

.inline-action:hover {
  color: var(--ikaros-pink-dark);
}

.form-section {
  display: grid;
  gap: 14px;
  padding: 14px;
  border: 1px solid var(--ikaros-line);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.32);
}

:global(.dark) .form-section {
  background: rgba(255, 255, 255, 0.04);
}

.section-title {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 750;
}

.section-title svg {
  width: 15px;
  height: 15px;
  color: var(--ikaros-pink);
}

.cycle-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.cycle-option {
  min-height: 34px;
  padding: 0 14px;
  border: 1px solid var(--ikaros-line);
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.55);
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 650;
}

:global(.dark) .cycle-option {
  background: rgba(255, 255, 255, 0.06);
}

.cycle-option:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.cycle-option.is-active {
  border-color: var(--ikaros-pink);
  background: var(--ikaros-pink);
  color: #fff;
}

.cycle-custom {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  margin-left: auto;
  color: var(--ikaros-copy);
  font-size: 12px;
}

.cycle-input {
  width: 84px;
  text-align: center;
}

.reminder-toggle {
  display: flex;
  cursor: pointer;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.reminder-checkbox {
  width: 18px;
  height: 18px;
  flex: none;
  accent-color: var(--ikaros-pink);
}

.reminder-fields {
  padding-top: 14px;
  border-top: 1px solid var(--ikaros-line);
}

.days-input {
  position: relative;
  display: block;
}

.days-suffix {
  position: absolute;
  top: 50%;
  right: 13px;
  color: var(--ikaros-muted);
  font-size: 12px;
  transform: translateY(-50%);
}

.form-error {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 11px 13px;
  border: 1px solid rgba(198, 55, 65, 0.18);
  border-radius: 13px;
  background: rgba(198, 55, 65, 0.08);
  color: #c63741;
  font-size: 12px;
  line-height: 1.5;
}

.form-error svg {
  width: 15px;
  height: 15px;
  flex: none;
  margin-top: 1px;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding-top: 4px;
}

@keyframes subscription-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1180px) {
  .sub-head {
    display: none;
  }

  .sub-row {
    grid-template-columns: minmax(0, 1fr) 145px 120px 76px;
  }

  .sub-cost,
  .sub-cycle,
  .sub-reminder {
    display: none;
  }
}

@media (max-width: 720px) {
  .form-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .sub-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .sub-expiry,
  .sub-status {
    display: none;
  }

  .cycle-custom {
    margin-left: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .refresh-button .is-spinning,
  .submit-button .is-spinning,
  .row-actions .is-spinning,
  .panel-loading .is-spinning {
    animation: none;
  }

  .field-input,
  .field-textarea {
    transition: none;
  }
}
</style>
