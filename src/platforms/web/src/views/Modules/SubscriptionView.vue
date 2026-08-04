<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref } from 'vue'
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
import type { SubscriptionPayload, SubscriptionRecord } from '@/types/subscription'

type SubscriptionForm = SubscriptionPayload

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

const statusClass = (item: SubscriptionRecord) => {
    if (item.status === 'expired') return 'border-rose-200 bg-rose-50 text-rose-700'
    if (item.status === 'renewal_due') return 'border-amber-200 bg-amber-50 text-amber-700'
    return 'border-emerald-200 bg-emerald-50 text-emerald-700'
}

onMounted(load)
</script>

<template>
  <div class="space-y-6 p-6 md:p-8">
    <section class="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
      <div class="grid grid-cols-2 gap-px bg-slate-200 xl:grid-cols-4">
        <div class="bg-white p-2.5 sm:p-4">
          <div class="text-[11px] uppercase tracking-[0.16em] text-slate-400 sm:text-xs sm:tracking-[0.22em]">全部订阅</div>
          <div class="mt-0.5 text-lg font-semibold text-slate-950 sm:mt-1 sm:text-2xl">{{ totalCount }}</div>
        </div>
        <div class="bg-white p-2.5 sm:p-4">
          <div class="text-[11px] uppercase tracking-[0.16em] text-slate-400 sm:text-xs sm:tracking-[0.22em]">已到提醒日</div>
          <div class="mt-0.5 text-lg font-semibold text-amber-600 sm:mt-1 sm:text-2xl">{{ renewalDueCount }}</div>
        </div>
        <div class="bg-white p-2.5 sm:p-4">
          <div class="text-[11px] uppercase tracking-[0.16em] text-slate-400 sm:text-xs sm:tracking-[0.22em]">30 天内到期</div>
          <div class="mt-0.5 text-lg font-semibold text-indigo-600 sm:mt-1 sm:text-2xl">{{ expiringThirtyCount }}</div>
        </div>
        <div class="bg-white p-2.5 sm:p-4">
          <div class="text-[11px] uppercase tracking-[0.16em] text-slate-400 sm:text-xs sm:tracking-[0.22em]">已过期</div>
          <div class="mt-0.5 text-lg font-semibold text-rose-600 sm:mt-1 sm:text-2xl">{{ expiredCount }}</div>
        </div>
      </div>
    </section>

    <div
      v-if="!bindings.length && !loading"
      class="flex items-start gap-3 rounded-[22px] border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-800"
    >
      <CircleAlert class="mt-0.5 h-5 w-5 shrink-0" />
      <div>
        <div class="font-medium">尚未绑定消息渠道</div>
        <div class="mt-1 text-amber-700">订阅可以正常保存，但到期提醒暂时无法送达。请先到“模块绑定”中绑定 Telegram、微信、钉钉或 Discord。</div>
      </div>
    </div>

    <div
      v-if="errorText && !showDialog"
      class="rounded-[22px] border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-700"
    >
      {{ errorText }}
    </div>

    <section class="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
      <div class="flex flex-wrap items-center justify-between gap-3 p-3.5 sm:p-5 md:px-6">
        <div>
          <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Subscriptions</div>
          <h3 class="mt-0.5 text-lg font-semibold text-slate-950 sm:mt-1 sm:text-xl">续期时间线</h3>
        </div>
        <div class="flex items-center gap-2">
          <span class="mr-1 hidden rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-sm text-slate-600 sm:inline-flex">{{ totalCount }} 项</span>
          <button
            type="button"
            class="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-2.5 py-2 text-sm text-slate-600 transition hover:bg-slate-50 disabled:opacity-60 sm:px-3"
            :disabled="refreshing"
            @click="load(true)"
          >
            <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': refreshing }" />
            <span class="hidden sm:inline">刷新</span>
          </button>
          <button
            type="button"
            class="inline-flex items-center gap-1.5 rounded-xl bg-indigo-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-indigo-500 sm:gap-2"
            @click="openCreate"
          >
            <Plus class="h-4 w-4" />
            添加订阅
          </button>
        </div>
      </div>

      <div v-if="loading" class="flex min-h-[240px] items-center justify-center border-t border-slate-200 text-slate-400">
        <Loader2 class="h-8 w-8 animate-spin text-indigo-500" />
      </div>

      <div v-else-if="!subscriptions.length" class="flex min-h-[280px] flex-col items-center justify-center border-t border-slate-200 text-center text-slate-400">
        <div class="flex h-20 w-20 items-center justify-center rounded-[28px] bg-slate-100">
          <CalendarClock class="h-9 w-9 text-slate-300" />
        </div>
        <div class="mt-5 text-lg font-medium text-slate-600">还没有订阅记录</div>
        <div class="mt-2 max-w-sm text-sm">添加第一个周期服务，Ikaros 会根据到期日主动提醒你。</div>
      </div>

      <div v-else class="border-t border-slate-200">
        <div class="hidden grid-cols-[minmax(180px,1.6fr)_100px_145px_80px_130px_120px_76px] gap-4 border-b border-slate-200 bg-slate-50 px-5 py-2.5 text-xs font-medium uppercase tracking-[0.12em] text-slate-400 xl:grid md:px-6">
          <span>订阅</span>
          <span>费用</span>
          <span>到期日</span>
          <span>周期</span>
          <span>提醒</span>
          <span>状态</span>
          <span class="text-right">操作</span>
        </div>

        <article
          v-for="item in subscriptions"
          :key="item.id"
          class="border-b border-slate-100 px-4 py-2.5 transition last:border-b-0 hover:bg-slate-50 md:px-5 xl:px-5 xl:py-3.5"
        >
          <div class="xl:hidden">
            <div class="flex min-w-0 items-center gap-1.5">
              <h4 class="min-w-0 truncate text-sm font-semibold text-slate-950">{{ item.name }}</h4>
              <span class="shrink-0 rounded-full border border-slate-200 bg-slate-50 px-1.5 py-px text-[10px] leading-4 text-slate-500">{{ item.category }}</span>
              <div class="ml-auto flex shrink-0 items-center gap-1">
                <button type="button" class="rounded-md border border-slate-200 bg-white p-1 text-slate-500 transition hover:border-indigo-200 hover:text-indigo-600" title="编辑" @click="openEdit(item)">
                  <Pencil class="h-3 w-3" />
                </button>
                <button type="button" class="rounded-md border border-slate-200 bg-white p-1 text-slate-500 transition hover:border-rose-200 hover:text-rose-600 disabled:opacity-50" title="删除" :disabled="deletingId === item.id" @click="remove(item)">
                  <Loader2 v-if="deletingId === item.id" class="h-3 w-3 animate-spin" />
                  <Trash2 v-else class="h-3 w-3" />
                </button>
              </div>
            </div>
            <div class="mt-1 flex min-w-0 items-center gap-1.5 text-xs">
              <span class="inline-flex shrink-0 rounded-full border px-1.5 py-px text-[10px] leading-4 font-medium" :class="statusClass(item)">{{ statusLabel(item) }}</span>
              <span class="shrink-0 font-medium text-slate-900">{{ formatDate(item.expiry_date) }}</span>
              <span class="shrink-0 text-slate-500">{{ item.cost || '—' }}</span>
              <span class="shrink-0 text-slate-400">{{ cycleLabel(item.cycle_months) }}</span>
            </div>
            <div class="mt-0.5 flex min-w-0 items-center gap-1.5 text-[11px] text-slate-400">
              <span class="min-w-0 truncate">{{ item.provider || '未填写服务商' }}<template v-if="item.notes"> · {{ item.notes }}</template></span>
              <span class="shrink-0">·</span>
              <span class="shrink-0">{{ item.reminder_enabled ? `提前 ${item.reminder_days_before} 天` : '提醒已关' }}</span>
              <span class="shrink-0">·</span>
              <span class="shrink-0">{{ item.delivery_configured ? (platformLabels[item.delivery_platform] || item.delivery_platform) : '未配置渠道' }}</span>
              <span v-if="item.last_reminded_at" class="ml-auto inline-flex shrink-0 items-center gap-0.5 text-emerald-600"><CheckCircle2 class="h-3 w-3" />已提醒</span>
              <span v-else-if="item.reminder_enabled" class="ml-auto shrink-0">提醒日 {{ item.reminder_date }}</span>
            </div>
          </div>

          <div class="hidden gap-4 xl:grid xl:grid-cols-[minmax(180px,1.6fr)_100px_145px_80px_130px_120px_76px] xl:items-center">
            <div class="min-w-0">
              <div class="flex min-w-0 items-center gap-2">
                <h4 class="truncate font-semibold text-slate-950">{{ item.name }}</h4>
                <span class="shrink-0 rounded-full border border-slate-200 bg-white px-2 py-0.5 text-xs text-slate-500">{{ item.category }}</span>
              </div>
              <div class="mt-1 truncate text-xs text-slate-400">
                {{ item.provider || '未填写服务商' }}<template v-if="item.notes"> · {{ item.notes }}</template>
              </div>
            </div>

            <div>
              <div class="text-sm font-medium text-slate-700">{{ item.cost || '—' }}</div>
            </div>

            <div>
              <div class="font-medium text-slate-900">{{ formatDate(item.expiry_date) }}</div>
              <div class="mt-0.5 text-xs text-slate-400">始于 {{ item.start_date }}</div>
            </div>

            <div>
              <div class="text-sm font-medium text-slate-700">{{ cycleLabel(item.cycle_months) }}</div>
            </div>

            <div>
              <div class="text-sm font-medium text-slate-700">
                {{ item.reminder_enabled ? `提前 ${item.reminder_days_before} 天` : '已关闭' }}
              </div>
              <div class="mt-0.5 text-xs text-slate-400">
                {{ item.delivery_configured ? (platformLabels[item.delivery_platform] || item.delivery_platform) : '未配置消息渠道' }}
              </div>
            </div>

            <div>
              <span class="inline-flex rounded-full border px-2.5 py-1 text-xs font-medium" :class="statusClass(item)">
                {{ statusLabel(item) }}
              </span>
              <div class="mt-1 text-xs text-slate-400">
                <span v-if="item.last_reminded_at" class="inline-flex items-center gap-1 text-emerald-600"><CheckCircle2 class="h-3.5 w-3.5" /> 本期已提醒</span>
                <span v-else>提醒日 {{ item.reminder_date }}</span>
              </div>
            </div>

            <div class="flex items-center justify-end gap-2 self-center">
              <button type="button" class="rounded-xl border border-slate-200 bg-white p-2 text-slate-500 transition hover:border-indigo-200 hover:text-indigo-600" title="编辑" @click="openEdit(item)">
                <Pencil class="h-4 w-4" />
              </button>
              <button type="button" class="rounded-xl border border-slate-200 bg-white p-2 text-slate-500 transition hover:border-rose-200 hover:text-rose-600 disabled:opacity-50" title="删除" :disabled="deletingId === item.id" @click="remove(item)">
                <Loader2 v-if="deletingId === item.id" class="h-4 w-4 animate-spin" />
                <Trash2 v-else class="h-4 w-4" />
              </button>
            </div>
          </div>
        </article>
      </div>
    </section>

    <div v-if="showDialog" class="fixed inset-0 z-[70] flex items-center justify-center bg-slate-950/60 p-4 backdrop-blur-sm">
      <div class="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-[28px] border border-slate-200 bg-white shadow-[0_28px_80px_rgba(15,23,42,0.3)]">
        <div class="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white/95 px-6 py-5 backdrop-blur">
          <div>
            <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Subscription form</div>
            <h3 class="mt-1 text-xl font-semibold text-slate-950">{{ editingId ? '编辑订阅' : '添加订阅' }}</h3>
          </div>
          <button type="button" class="rounded-xl border border-slate-200 p-2 text-slate-500 hover:bg-slate-50" @click="closeDialog"><X class="h-4 w-4" /></button>
        </div>

        <form class="space-y-5 p-6" @submit.prevent="save">
          <div class="grid gap-4 sm:grid-cols-2">
            <label class="sm:col-span-2">
              <span class="mb-1.5 block text-sm text-slate-600">订阅名称 <b class="text-rose-500">*</b></span>
              <input v-model="form.name" type="text" maxlength="120" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-slate-900 outline-none transition focus:border-indigo-400 focus:bg-white focus:ring-2 focus:ring-indigo-100" placeholder="例如：ChatGPT Plus、搬瓦工 VPS" autofocus>
            </label>

            <label>
              <span class="mb-1.5 block text-sm text-slate-600">分类</span>
              <input v-model="form.category" type="text" maxlength="60" list="subscription-categories" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none focus:border-indigo-400 focus:bg-white">
              <datalist id="subscription-categories">
                <option v-for="category in categoryOptions" :key="category" :value="category" />
              </datalist>
            </label>

            <label>
              <span class="mb-1.5 block text-sm text-slate-600">服务商</span>
              <input v-model="form.provider" type="text" maxlength="120" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none focus:border-indigo-400 focus:bg-white" placeholder="可选">
            </label>

            <label class="sm:col-span-2">
              <span class="mb-1.5 block text-sm text-slate-600">费用</span>
              <input v-model="form.cost" type="text" maxlength="64" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none focus:border-indigo-400 focus:bg-white" placeholder="例如：¥98 / 月、20 USD / 月（可选）">
            </label>
          </div>

          <div class="rounded-[22px] border border-slate-200 bg-slate-50 p-4">
            <div class="flex items-center gap-2 font-medium text-slate-800"><RefreshCw class="h-4 w-4 text-indigo-500" /> 订阅周期</div>
            <div class="mt-4 flex flex-wrap gap-2">
              <button
                v-for="option in cycleOptions"
                :key="option.months"
                type="button"
                class="rounded-xl border px-3 py-2 text-sm transition"
                :class="form.cycle_months === option.months ? 'border-indigo-500 bg-indigo-500 text-white' : 'border-slate-200 bg-white text-slate-600 hover:border-indigo-200'"
                @click="setCycle(option.months)"
              >
                {{ option.label }}
              </button>
              <label class="ml-auto flex items-center gap-2 text-sm text-slate-500">
                每
                <input v-model.number="form.cycle_months" type="number" min="1" max="1200" step="1" class="w-24 rounded-xl border border-slate-200 bg-white px-3 py-2 text-center text-slate-900 outline-none focus:border-indigo-400" @change="recalculateExpiry">
                个月
              </label>
            </div>
          </div>

          <div class="grid gap-4 sm:grid-cols-2">
            <label>
              <span class="mb-1.5 block text-sm text-slate-600">开始日期</span>
              <input v-model="form.start_date" type="date" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none focus:border-indigo-400 focus:bg-white" @change="recalculateExpiry">
            </label>
            <label>
              <span class="mb-1.5 flex items-center justify-between text-sm text-slate-600">
                <span>到期日期</span>
                <button type="button" class="text-xs text-indigo-600 hover:text-indigo-500" @click="recalculateExpiry">按周期重算</button>
              </span>
              <input v-model="form.expiry_date" type="date" class="w-full rounded-2xl border border-indigo-200 bg-indigo-50 px-4 py-3 font-medium text-slate-900 outline-none focus:border-indigo-400 focus:bg-white">
              <span class="mt-1.5 block text-xs text-slate-400">可直接修改，以服务商给出的实际日期为准。</span>
            </label>
          </div>

          <div class="rounded-[22px] border border-slate-200 p-4">
            <label class="flex cursor-pointer items-center justify-between gap-4">
              <div>
                <div class="flex items-center gap-2 font-medium text-slate-800"><BellRing class="h-4 w-4 text-indigo-500" /> 到期提醒</div>
                <div class="mt-1 text-xs text-slate-400">同一个到期日只会成功推送一次。</div>
              </div>
              <input v-model="form.reminder_enabled" type="checkbox" class="h-5 w-5 accent-indigo-600">
            </label>

            <div v-if="form.reminder_enabled" class="mt-4 grid gap-4 border-t border-slate-100 pt-4 sm:grid-cols-2">
              <label>
                <span class="mb-1.5 block text-sm text-slate-600">提前多少天</span>
                <div class="relative">
                  <input v-model.number="form.reminder_days_before" type="number" min="0" max="3650" step="1" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 pr-12 outline-none focus:border-indigo-400 focus:bg-white">
                  <span class="absolute right-4 top-3 text-sm text-slate-400">天</span>
                </div>
              </label>
              <label>
                <span class="mb-1.5 block text-sm text-slate-600">消息渠道</span>
                <select v-model="form.delivery_platform" :disabled="!bindings.length" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none focus:border-indigo-400 focus:bg-white disabled:opacity-60">
                  <option v-if="!bindings.length" :value="undefined">尚未绑定渠道</option>
                  <option v-for="binding in bindings" :key="binding.id" :value="binding.platform">{{ platformLabels[binding.platform] || binding.platform }}</option>
                </select>
              </label>
            </div>
          </div>

          <label>
            <span class="mb-1.5 block text-sm text-slate-600">备注</span>
            <textarea v-model="form.notes" rows="3" maxlength="1000" class="w-full resize-none rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none focus:border-indigo-400 focus:bg-white" placeholder="套餐、账号、续费注意事项等（可选）" />
          </label>

          <div v-if="errorText" class="flex items-start gap-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            <CircleAlert class="mt-0.5 h-4 w-4 shrink-0" />
            {{ errorText }}
          </div>

          <div class="flex gap-3 border-t border-slate-100 pt-5">
            <button type="button" class="flex-1 rounded-2xl border border-slate-200 bg-white px-4 py-3 font-medium text-slate-600 transition hover:bg-slate-50" @click="closeDialog">取消</button>
            <button type="submit" class="inline-flex flex-1 items-center justify-center gap-2 rounded-2xl bg-indigo-600 px-4 py-3 font-medium text-white shadow-lg shadow-indigo-600/20 transition hover:bg-indigo-500 disabled:opacity-60" :disabled="saving">
              <Loader2 v-if="saving" class="h-4 w-4 animate-spin" />
              <Clock3 v-else class="h-4 w-4" />
              {{ saving ? '保存中' : '保存订阅' }}
            </button>
          </div>
        </form>
      </div>
    </div>
  </div>
</template>
