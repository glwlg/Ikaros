<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref, watch, type Component } from 'vue'
import {
    Briefcase,
    CheckCircle2,
    Loader2,
    MessageCircle,
    MessagesSquare,
    RefreshCw,
    Send,
    Trash2,
    TriangleAlert,
} from 'lucide-vue-next'

import { deleteMyBinding, listMyBindings, saveMyBinding, type ChannelBinding } from '@/api/binding'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'

type PlatformKey = 'telegram' | 'discord' | 'dingtalk' | 'weixin'

const platformOptions: Array<{
    value: PlatformKey
    label: string
    hint: string
    icon: Component
    accent: string
}> = [
    { value: 'telegram', label: 'Telegram', hint: '填写 Telegram 机器人看到的用户 ID。', icon: Send, accent: '#2aabee' },
    { value: 'discord', label: 'Discord', hint: '填写 Discord 渠道中的用户 ID。', icon: MessagesSquare, accent: '#5865f2' },
    { value: 'dingtalk', label: '钉钉', hint: '填写钉钉会话中的用户标识。', icon: Briefcase, accent: '#0089ff' },
    { value: 'weixin', label: '微信 / 企微', hint: '填写微信或企微渠道中的用户标识。', icon: MessageCircle, accent: '#07c160' },
]
const defaultPlatformMeta = platformOptions[0]!

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

const bindings = ref<ChannelBinding[]>([])
const loading = ref(false)
const saving = ref(false)
const deletingId = ref<number | null>(null)
const errorText = ref('')
const successText = ref('')
const form = ref<{ platform: PlatformKey; platform_user_id: string }>({
    platform: 'telegram',
    platform_user_id: '',
})

const bindingsByPlatform = computed(() =>
    new Map(bindings.value.map(item => [item.platform, item]))
)

const selectedMeta = computed(() =>
    platformOptions.find(item => item.value === form.value.platform) || defaultPlatformMeta
)

const platformMeta = (platform: string) =>
    platformOptions.find(item => item.value === platform) || {
        ...defaultPlatformMeta,
        label: platform,
    }

const selectedBinding = computed(() =>
    bindingsByPlatform.value.get(form.value.platform)
)

const submitLabel = computed(() =>
    selectedBinding.value ? '更新绑定' : '保存绑定'
)

const parseErrorMessage = (error: unknown, fallback: string) => {
    if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (Array.isArray(detail) && detail.length > 0) {
            return String(detail[0]?.msg || fallback)
        }
        if (typeof detail === 'string' && detail.trim()) {
            return detail
        }
    }
    return fallback
}

const syncFormFromSelectedBinding = () => {
    form.value.platform_user_id = selectedBinding.value?.platform_user_id || ''
}

const load = async () => {
    loading.value = true
    errorText.value = ''
    try {
        const response = await listMyBindings()
        bindings.value = Array.isArray(response.data) ? response.data : []
        syncFormFromSelectedBinding()
    } catch (error) {
        errorText.value = parseErrorMessage(error, '绑定信息加载失败')
    } finally {
        loading.value = false
    }
}

const submit = async () => {
    errorText.value = ''
    successText.value = ''
    const platform_user_id = form.value.platform_user_id.trim()
    if (!platform_user_id) {
        errorText.value = '请先填写渠道账户 ID。'
        return
    }

    saving.value = true
    try {
        const existed = Boolean(selectedBinding.value)
        await saveMyBinding({
            platform: form.value.platform,
            platform_user_id,
        })
        successText.value = existed ? '渠道绑定已更新。' : '渠道绑定已保存。'
        await load()
    } catch (error) {
        errorText.value = parseErrorMessage(error, '保存绑定失败')
    } finally {
        saving.value = false
    }
}

const removeBinding = async (binding: ChannelBinding) => {
    errorText.value = ''
    successText.value = ''
    deletingId.value = binding.id
    try {
        await deleteMyBinding(binding.id)
        successText.value = `${binding.platform} 绑定已移除。`
        await load()
    } catch (error) {
        errorText.value = parseErrorMessage(error, '移除绑定失败')
    } finally {
        deletingId.value = null
    }
}

watch(() => form.value.platform, () => {
    errorText.value = ''
    successText.value = ''
    syncFormFromSelectedBinding()
})

onMounted(load)
</script>

<template>
  <div class="ikaros-page bindings-page">
    <header class="ikaros-page-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Channels</p>
        <h1 class="ikaros-page-title">渠道绑定</h1>
        <p class="ikaros-page-description">
          把消息渠道中的账户关联到当前 Web 账号，绑定后 Ikaros 才能在对应渠道里识别你并收发消息。
        </p>
      </div>
      <div class="bindings-header-actions">
        <span class="bindings-count-chip">{{ bindings.length }} 个绑定</span>
        <button type="button" class="ikaros-secondary-action" :disabled="loading" @click="load">
          <RefreshCw :class="{ 'is-spinning': loading }" />
          刷新
        </button>
      </div>
    </header>

    <div class="bindings-layout">
      <section class="bindings-platforms" aria-label="可用渠道">
        <h2 class="bindings-section-label">可用渠道</h2>
        <LiquidGlass
          v-for="item in platformOptions"
          :key="item.value"
          as="button"
          type="button"
          :radius="18"
          :optics="compactOptics"
          interactive
          class="bindings-platform-card"
          :class="{
            'is-selected': form.platform === item.value,
            'is-bound': bindingsByPlatform.has(item.value),
          }"
          @click="form.platform = item.value"
        >
          <span
            class="bindings-platform-icon"
            :style="{ color: item.accent, background: `${item.accent}14`, borderColor: `${item.accent}30` }"
          >
            <component :is="item.icon" />
          </span>
          <span class="bindings-platform-copy">
            <strong>{{ item.label }}</strong>
            <small>{{ item.hint }}</small>
          </span>
          <span class="bindings-platform-state" :class="{ 'is-bound': bindingsByPlatform.has(item.value) }">
            {{ bindingsByPlatform.has(item.value) ? '已绑定' : '未绑定' }}
          </span>
        </LiquidGlass>
      </section>

      <div class="bindings-main">
        <LiquidGlass :radius="22" :optics="panelOptics" class="bindings-editor">
          <form class="bindings-form" @submit.prevent="submit">
            <header class="bindings-editor-head">
              <span
                class="bindings-editor-icon"
                :style="{
                  color: selectedMeta.accent,
                  background: `${selectedMeta.accent}14`,
                  borderColor: `${selectedMeta.accent}30`,
                }"
              >
                <component :is="selectedMeta.icon" />
              </span>
              <div class="bindings-editor-title">
                <h2>配置 {{ selectedMeta.label }} 渠道</h2>
                <p>{{ selectedMeta.hint }}</p>
              </div>
              <span class="bindings-state-chip" :class="{ 'is-bound': selectedBinding }">
                {{ selectedBinding ? '已绑定' : '未绑定' }}
              </span>
            </header>

            <label class="bindings-field">
              <span>账户 ID</span>
              <input
                v-model="form.platform_user_id"
                type="text"
                :placeholder="`${selectedMeta.label} 账户 ID`"
              >
            </label>

            <div v-if="selectedBinding" class="bindings-note is-current">
              <CheckCircle2 />
              当前已绑定：{{ selectedBinding.platform_user_id }}
            </div>

            <div v-if="errorText" class="bindings-note is-error">
              {{ errorText }}
            </div>

            <div v-if="successText" class="bindings-note is-success">
              {{ successText }}
            </div>

            <div class="bindings-form-actions">
              <button type="submit" class="ikaros-primary-action bindings-submit" :disabled="saving">
                <Loader2 v-if="saving" class="is-spinning" />
                {{ submitLabel }}
              </button>
            </div>
          </form>
        </LiquidGlass>

        <section class="bindings-list" aria-label="当前绑定">
          <h2 class="bindings-section-label">当前绑定</h2>

          <div v-if="loading" class="bindings-loading">
            <Loader2 class="is-spinning" />
            正在加载绑定信息
          </div>

          <div v-else-if="!bindings.length" class="bindings-empty">
            <TriangleAlert />
            <div>当前还没有渠道绑定。</div>
          </div>

          <div v-else class="bindings-rows">
            <article v-for="binding in bindings" :key="binding.id" class="ikaros-surface bindings-row">
              <span
                class="bindings-row-icon"
                :style="{
                  color: platformMeta(binding.platform).accent,
                  background: `${platformMeta(binding.platform).accent}14`,
                  borderColor: `${platformMeta(binding.platform).accent}30`,
                }"
              >
                <component :is="platformMeta(binding.platform).icon" />
              </span>
              <div class="bindings-row-copy">
                <strong>{{ platformMeta(binding.platform).label }}</strong>
                <small :title="binding.platform_user_id">{{ binding.platform_user_id }}</small>
              </div>
              <span class="bindings-row-status">
                <CheckCircle2 />
                已关联到当前 Web 账号
              </span>
              <button
                type="button"
                class="bindings-row-remove"
                :disabled="deletingId === binding.id"
                @click="removeBinding(binding)"
              >
                <Loader2 v-if="deletingId === binding.id" class="is-spinning" />
                <Trash2 v-else />
                移除
              </button>
            </article>
          </div>
        </section>
      </div>
    </div>
  </div>
</template>

<style scoped>
.bindings-page {
  gap: 22px;
}

.bindings-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.bindings-count-chip {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  padding: 0 14px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: var(--panel-muted);
  color: var(--ikaros-copy);
  font-size: 13px;
  font-weight: 700;
}

.bindings-header-actions svg {
  width: 15px;
  height: 15px;
}

.bindings-layout {
  display: grid;
  min-width: 0;
  gap: 20px;
  align-items: start;
}

.bindings-platforms {
  display: grid;
  min-width: 0;
  gap: 10px;
  align-content: start;
}

.bindings-section-label {
  margin: 0;
  padding: 0 4px;
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.bindings-platform-card {
  position: relative;
  display: flex;
  width: 100%;
  align-items: center;
  gap: 12px;
  padding: 14px;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.bindings-platform-card.is-selected {
  border-color: rgba(232, 93, 142, 0.38);
  box-shadow:
    0 16px 40px rgba(232, 93, 142, 0.12),
    inset 0 0 22px rgba(255, 255, 255, 0.28);
}

.bindings-platform-card.is-selected::before {
  position: absolute;
  top: 14px;
  bottom: 14px;
  left: 0;
  width: 3px;
  border-radius: 999px;
  background: var(--ikaros-pink);
  content: '';
}

.bindings-platform-icon,
.bindings-editor-icon,
.bindings-row-icon {
  display: grid;
  flex: none;
  place-items: center;
  border: 1px solid;
}

.bindings-platform-icon {
  width: 40px;
  height: 40px;
  border-radius: 14px;
}

.bindings-platform-icon svg {
  width: 19px;
  height: 19px;
}

.bindings-platform-copy {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 2px;
}

.bindings-platform-copy strong {
  color: var(--ikaros-ink);
  font-size: 14px;
  font-weight: 750;
}

.bindings-platform-copy small {
  overflow: hidden;
  color: var(--ikaros-muted);
  font-size: 11px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bindings-platform-state {
  flex: none;
  padding: 4px 9px;
  border-radius: 999px;
  background: var(--panel-muted);
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
}

.bindings-platform-state.is-bound {
  background: rgba(42, 140, 138, 0.1);
  color: var(--ikaros-eye);
}

.bindings-main {
  display: grid;
  min-width: 0;
  gap: 20px;
  align-content: start;
}

.bindings-editor {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .bindings-editor {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.86);
}

.bindings-form {
  display: grid;
  gap: 15px;
  padding: 22px;
}

.bindings-editor-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 15px;
  border-bottom: 1px solid var(--ikaros-line);
}

.bindings-editor-icon {
  width: 44px;
  height: 44px;
  border-radius: 15px;
}

.bindings-editor-icon svg {
  width: 21px;
  height: 21px;
}

.bindings-editor-title {
  min-width: 0;
  flex: 1;
}

.bindings-editor-title h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.bindings-editor-title p {
  margin: 3px 0 0;
  color: var(--ikaros-muted);
  font-size: 12px;
  line-height: 1.5;
}

.bindings-state-chip {
  flex: none;
  padding: 5px 10px;
  border-radius: 999px;
  background: var(--panel-muted);
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 750;
}

.bindings-state-chip.is-bound {
  background: rgba(42, 140, 138, 0.1);
  color: var(--ikaros-eye);
}

.bindings-field {
  display: grid;
  gap: 7px;
}

.bindings-field span {
  color: var(--ikaros-copy);
  font-size: 13px;
  font-weight: 650;
}

.bindings-field input {
  width: 100%;
  padding: 11px 14px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.55);
  color: var(--ikaros-ink);
  font-size: 14px;
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease, background-color 160ms ease;
}

:global(.dark) .bindings-field input {
  background: rgba(255, 255, 255, 0.06);
}

.bindings-field input:focus {
  border-color: rgba(232, 93, 142, 0.45);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.12);
}

:global(.dark) .bindings-field input:focus {
  background: rgba(255, 255, 255, 0.09);
}

.bindings-note {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 11px 14px;
  border: 1px solid;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.5;
}

.bindings-note svg {
  width: 16px;
  height: 16px;
  flex: none;
}

.bindings-note.is-current {
  border-color: rgba(42, 140, 138, 0.22);
  background: rgba(42, 140, 138, 0.08);
  color: var(--ikaros-eye);
}

.bindings-note.is-error {
  border-color: rgba(198, 55, 65, 0.18);
  background: rgba(198, 55, 65, 0.07);
  color: #c63741;
}

.bindings-note.is-success {
  border-color: rgba(47, 125, 74, 0.2);
  background: rgba(47, 125, 74, 0.08);
  color: var(--ikaros-rind);
}

.bindings-form-actions {
  display: flex;
  gap: 10px;
}

.bindings-submit {
  flex: 1;
  border: 0;
  cursor: pointer;
}

.bindings-submit:disabled {
  cursor: wait;
  opacity: 0.7;
}

.bindings-submit svg {
  width: 15px;
  height: 15px;
}

.bindings-list {
  display: grid;
  gap: 10px;
  align-content: start;
}

.bindings-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 4px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.bindings-loading svg {
  width: 16px;
  height: 16px;
}

.bindings-empty {
  display: flex;
  min-height: 200px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border: 1px dashed var(--ikaros-line);
  border-radius: 18px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.bindings-empty svg {
  width: 22px;
  height: 22px;
}

.bindings-rows {
  display: grid;
  gap: 10px;
}

.bindings-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 13px 14px;
  border-radius: 16px;
}

.bindings-row-icon {
  width: 36px;
  height: 36px;
  border-radius: 12px;
}

.bindings-row-icon svg {
  width: 17px;
  height: 17px;
}

.bindings-row-copy {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 2px;
}

.bindings-row-copy strong {
  color: var(--ikaros-ink);
  font-size: 14px;
  font-weight: 750;
}

.bindings-row-copy small {
  overflow: hidden;
  color: var(--ikaros-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.bindings-row-status {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 6px;
  color: var(--ikaros-rind);
  font-size: 12px;
  font-weight: 650;
}

.bindings-row-status svg {
  width: 15px;
  height: 15px;
}

.bindings-row-remove {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 6px;
  padding: 7px 12px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.45);
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 700;
  transition: border-color 160ms ease, color 160ms ease, background-color 160ms ease;
}

:global(.dark) .bindings-row-remove {
  background: rgba(255, 255, 255, 0.06);
}

.bindings-row-remove:hover {
  border-color: rgba(198, 55, 65, 0.3);
  background: rgba(198, 55, 65, 0.07);
  color: #c63741;
}

.bindings-row-remove:disabled {
  cursor: wait;
  opacity: 0.7;
}

.bindings-row-remove svg {
  width: 13px;
  height: 13px;
}

.is-spinning {
  animation: bindings-spin 850ms linear infinite;
}

@keyframes bindings-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (min-width: 1024px) {
  .bindings-layout {
    grid-template-columns: 340px minmax(0, 1fr);
  }
}

@media (max-width: 720px) {
  .bindings-row {
    flex-wrap: wrap;
  }

  .bindings-row-status {
    order: 3;
    width: 100%;
    padding-left: 48px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning {
    animation: none;
  }
}
</style>
