<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref } from 'vue'
import {
    CheckCircle2,
    Eye,
    EyeOff,
    KeyRound,
    Loader2,
    Plus,
    RefreshCw,
    SquarePen,
    Star,
    Trash2,
    TriangleAlert,
} from 'lucide-vue-next'

import {
    createMyCredential,
    deleteMyCredential,
    listMyCredentials,
    setMyDefaultCredential,
    updateMyCredential,
    type CredentialEntry,
    type CredentialService,
} from '@/api/credentials'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'

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

type FieldMeta = {
    key: string
    label: string
    placeholder: string
    secret?: boolean
}

type ServiceMeta = {
    value: string
    label: string
    hint: string
    notice: string
    fields: FieldMeta[]
}

type ServiceOption = {
    value: string
    label: string
}

type CredentialFieldState = {
    id: string
    key: string
    value: string
    secret: boolean
}

type CredentialFieldView = {
    key: string
    label: string
    value: unknown
    secret: boolean
}

type CredentialFormState = {
    name: string
    fields: CredentialFieldState[]
    is_default: boolean
}

const servicePresets: ServiceMeta[] = [
    {
        value: 'wechat_official_account',
        label: '微信公众号',
        hint: '这是一个预设模板。你也可以输入任意其他服务类型；article_publisher 会直接读取这个服务下的公众号凭据。',
        notice: 'article_publisher 可直接使用这条公众号凭据。',
        fields: [
            { key: 'app_id', label: 'App ID', placeholder: 'wx1234567890abcdef' },
            { key: 'app_secret', label: 'App Secret', placeholder: '填写公众号 app_secret', secret: true },
            { key: 'author', label: '作者署名', placeholder: '可选，例如：Ikaros 编辑部' },
            { key: 'note', label: '备注', placeholder: '可选，用于标注用途或团队' },
        ],
    },
    {
        value: 'xiaohongshu_publisher',
        label: '小红书发布',
        hint: '这是一个预设模板。你也可以输入任意其他服务类型，按 key/value 自由维护需要的凭据字段。',
        notice: '这条发布通道配置已就绪。',
        fields: [
            { key: 'endpoint', label: 'Endpoint', placeholder: 'https://publisher.example.com/xhs' },
            { key: 'token', label: 'Token', placeholder: '可选 token', secret: true },
            { key: 'api_key', label: 'API Key', placeholder: '可选 api_key', secret: true },
            { key: 'author', label: '作者署名', placeholder: '可选，例如：Ikaros' },
            { key: 'note', label: '备注', placeholder: '可选，用于标注用途或环境' },
        ],
    },
]

const SENSITIVE_KEY_TOKENS = [
    'secret',
    'token',
    'password',
    'passwd',
    'api_key',
    'apikey',
    'private',
    'access_key',
    'refresh_key',
]

const nextFieldId = () => `field_${Math.random().toString(36).slice(2, 10)}`

const normalizeText = (value: unknown) => String(value ?? '').trim()

const createFieldState = (
    key = '',
    value = '',
    secret = false,
): CredentialFieldState => ({
    id: nextFieldId(),
    key,
    value,
    secret,
})

const getServicePreset = (service: string) =>
    servicePresets.find(item => item.value === normalizeText(service)) || null

const guessSecretField = (key: string) => {
    const normalized = normalizeText(key).toLowerCase()
    return SENSITIVE_KEY_TOKENS.some(token => normalized.includes(token))
}

const buildServiceMeta = (service: string): ServiceMeta => {
    const normalized = normalizeText(service)
    const preset = getServicePreset(normalized)
    if (preset) {
        return preset
    }
    return {
        value: normalized,
        label: normalized || '自定义服务',
        hint: normalized
            ? `当前服务类型为 ${normalized}。凭据字段不做限制，你可以按任意 key/value 录入。`
            : '输入任意服务类型，例如：github_app、telegram_bot、aliyun_oss、openai_api。',
        notice: normalized
            ? '这条凭据会按当前服务类型保存，可供对应技能或模块读取。'
            : '先输入服务类型，再保存对应凭据。',
        fields: [],
    }
}

const buildFieldStates = (
    service: string,
    data: Record<string, unknown> = {},
): CredentialFieldState[] => {
    const preset = getServicePreset(service)
    const rows: CredentialFieldState[] = []
    const usedKeys = new Set<string>()

    if (preset) {
        for (const field of preset.fields) {
            usedKeys.add(field.key)
            rows.push(
                createFieldState(
                    field.key,
                    String(data[field.key] ?? ''),
                    Boolean(field.secret),
                ),
            )
        }
    }

    for (const [key, rawValue] of Object.entries(data)) {
        if (usedKeys.has(key)) {
            continue
        }
        rows.push(createFieldState(key, String(rawValue ?? ''), guessSecretField(key)))
    }

    if (!rows.length) {
        rows.push(createFieldState('', '', false))
    }

    return rows
}

const describeFields = (
    service: string,
    data: Record<string, unknown>,
): CredentialFieldView[] => {
    const preset = getServicePreset(service)
    const rows: CredentialFieldView[] = []
    const usedKeys = new Set<string>()

    if (preset) {
        for (const field of preset.fields) {
            usedKeys.add(field.key)
            rows.push({
                key: field.key,
                label: field.label,
                value: data[field.key],
                secret: Boolean(field.secret),
            })
        }
    }

    for (const [key, rawValue] of Object.entries(data)) {
        if (usedKeys.has(key)) {
            continue
        }
        rows.push({
            key,
            label: key,
            value: rawValue,
            secret: guessSecretField(key),
        })
    }

    return rows
}

const emptyForm = (service: string, isDefault = false): CredentialFormState => ({
    name: '',
    fields: buildFieldStates(service),
    is_default: isDefault,
})

const services = ref<CredentialService[]>([])
const selectedService = ref('')
const selectedEntryId = ref('')
const form = ref<CredentialFormState>(emptyForm(''))
const loading = ref(false)
const saving = ref(false)
const defaultingKey = ref('')
const deletingKey = ref('')
const errorText = ref('')
const successText = ref('')

const getEntriesByService = (service: string) => {
    const normalized = normalizeText(service)
    const target = services.value.find(item => item.service === normalized)
    return Array.isArray(target?.entries) ? target.entries : []
}

const serviceMeta = computed(() => buildServiceMeta(selectedService.value))

const serviceSuggestions = computed<ServiceOption[]>(() => {
    const seen = new Set<string>()
    const options: ServiceOption[] = []

    for (const preset of servicePresets) {
        if (seen.has(preset.value)) continue
        seen.add(preset.value)
        options.push({ value: preset.value, label: preset.label })
    }

    for (const service of services.value) {
        if (!service.service || seen.has(service.service)) continue
        seen.add(service.service)
        options.push({
            value: service.service,
            label: getServicePreset(service.service)?.label || service.service,
        })
    }

    return options
})

const entries = computed<CredentialEntry[]>(() => getEntriesByService(selectedService.value))

const selectedEntry = computed(() =>
    entries.value.find(item => item.id === selectedEntryId.value) || null,
)

const submitLabel = computed(() => (selectedEntry.value ? '更新凭据' : '新增凭据'))

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

const maskValue = (field: CredentialFieldView) => {
    const text = String(field.value ?? '').trim()
    if (!text) return '未填写'
    if (!field.secret) return text
    if (text.length <= 8) return '••••••••'
    return `${text.slice(0, 4)}••••${text.slice(-4)}`
}

const resetForm = (service = selectedService.value) => {
    selectedEntryId.value = ''
    form.value = emptyForm(service, getEntriesByService(service).length === 0)
}

const applyEntryToForm = (entry: CredentialEntry | null) => {
    if (!entry) {
        resetForm()
        return
    }

    selectedService.value = entry.service
    form.value = {
        name: entry.name,
        fields: buildFieldStates(entry.service, entry.data || {}),
        is_default: Boolean(entry.is_default),
    }
    selectedEntryId.value = entry.id
}

const selectEntry = (entry: CredentialEntry) => {
    errorText.value = ''
    successText.value = ''
    applyEntryToForm(entry)
}

const chooseService = (service: string) => {
    selectedService.value = normalizeText(service)
    errorText.value = ''
    successText.value = ''
    resetForm(selectedService.value)
}

const handleServiceInput = () => {
    errorText.value = ''
    successText.value = ''
    selectedEntryId.value = ''
}

const startCreate = () => {
    errorText.value = ''
    successText.value = ''
    resetForm(selectedService.value)
}

const addField = () => {
    form.value.fields.push(createFieldState('', '', false))
}

const removeField = (fieldId: string) => {
    if (form.value.fields.length <= 1) {
        form.value.fields = [createFieldState('', '', false)]
        return
    }
    form.value.fields = form.value.fields.filter(field => field.id !== fieldId)
}

const toggleFieldSecret = (fieldId: string) => {
    const target = form.value.fields.find(field => field.id === fieldId)
    if (!target) return
    target.secret = !target.secret
}

const fieldPlaceholder = (field: CredentialFieldState) => {
    const preset = getServicePreset(selectedService.value)
    const meta = preset?.fields.find(item => item.key === normalizeText(field.key))
    if (meta) return meta.placeholder
    return '字段值'
}

const buildPayload = (): { data: Record<string, unknown> | null; error: string } => {
    const payload: Record<string, unknown> = {}
    const seenKeys = new Set<string>()

    for (const field of form.value.fields) {
        const key = normalizeText(field.key)
        const value = normalizeText(field.value)

        if (!key && !value) {
            continue
        }
        if (!key) {
            return { data: null, error: '存在未填写字段名的凭据项。' }
        }
        if (!value) {
            return { data: null, error: `字段 ${key} 还没有填写值。` }
        }
        if (seenKeys.has(key)) {
            return { data: null, error: `字段名重复：${key}` }
        }

        seenKeys.add(key)
        payload[key] = value
    }

    if (!Object.keys(payload).length) {
        return { data: null, error: '请至少填写一项凭据内容。' }
    }

    return { data: payload, error: '' }
}

const load = async () => {
    loading.value = true
    errorText.value = ''
    try {
        const response = await listMyCredentials()
        services.value = Array.isArray(response.data) ? response.data : []

        if (!normalizeText(selectedService.value) && services.value.length > 0) {
            selectedService.value = services.value[0]!.service
        }

        if (selectedEntryId.value) {
            const current = getEntriesByService(selectedService.value).find(
                item => item.id === selectedEntryId.value,
            ) || null
            if (current) {
                applyEntryToForm(current)
                return
            }
        }

        resetForm(selectedService.value)
    } catch (error) {
        errorText.value = parseErrorMessage(error, '凭据加载失败')
    } finally {
        loading.value = false
    }
}

const submit = async () => {
    errorText.value = ''
    successText.value = ''

    const service = normalizeText(selectedService.value)
    if (!service) {
        errorText.value = '请先填写服务类型。'
        return
    }

    const name = normalizeText(form.value.name)
    if (!name) {
        errorText.value = '请先填写凭据别名。'
        return
    }

    const payload = buildPayload()
    if (!payload.data) {
        errorText.value = payload.error
        return
    }

    saving.value = true
    try {
        const isDefault = form.value.is_default || getEntriesByService(service).length === 0
        const response = selectedEntry.value
            ? await updateMyCredential(service, selectedEntry.value.id, {
                name,
                data: payload.data,
                is_default: isDefault,
            })
            : await createMyCredential(service, {
                name,
                data: payload.data,
                is_default: isDefault,
            })

        selectedService.value = service
        successText.value = selectedEntry.value ? '凭据已更新。' : '凭据已保存。'
        await load()
        const next = getEntriesByService(service).find(item => item.id === response.data.id) || null
        applyEntryToForm(next)
    } catch (error) {
        errorText.value = parseErrorMessage(error, '凭据保存失败')
    } finally {
        saving.value = false
    }
}

const markDefault = async (entry: CredentialEntry) => {
    errorText.value = ''
    successText.value = ''
    defaultingKey.value = entry.id
    try {
        await setMyDefaultCredential(entry.service, entry.id)
        successText.value = `默认凭据已切换为 ${entry.name}。`
        await load()
        const next = getEntriesByService(entry.service).find(item => item.id === entry.id) || null
        applyEntryToForm(next)
    } catch (error) {
        errorText.value = parseErrorMessage(error, '默认凭据设置失败')
    } finally {
        defaultingKey.value = ''
    }
}

const removeEntry = async (entry: CredentialEntry) => {
    errorText.value = ''
    successText.value = ''
    deletingKey.value = entry.id
    try {
        await deleteMyCredential(entry.service, entry.id)
        successText.value = `${entry.name} 已删除。`
        await load()
    } catch (error) {
        errorText.value = parseErrorMessage(error, '凭据删除失败')
    } finally {
        deletingKey.value = ''
    }
}

const entryNotice = (service: string) => buildServiceMeta(service).notice

onMounted(load)
</script>

<template>
  <div class="ikaros-page credentials-page">
    <header class="ikaros-page-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Credentials</p>
        <h1 class="ikaros-page-title">凭据管理</h1>
        <p class="ikaros-page-description">
          集中维护各服务的访问凭据，技能和发布通道会按服务类型读取对应的默认凭据。
        </p>
      </div>
      <div class="credentials-header-actions">
        <button type="button" class="ikaros-secondary-action" :disabled="loading" @click="load">
          <RefreshCw :class="{ 'is-spinning': loading }" />
          刷新
        </button>
        <button type="button" class="ikaros-primary-action" :disabled="loading" @click="startCreate">
          <Plus />
          新建凭据
        </button>
      </div>
    </header>

    <div class="credentials-layout">
      <LiquidGlass :radius="22" :optics="panelOptics" class="credentials-form-panel">
        <form class="credentials-form" @submit.prevent="submit">
          <header class="credentials-form-head">
            <span class="credentials-form-icon"><KeyRound /></span>
            <div class="credentials-form-title">
              <h2>配置凭据</h2>
              <p>创建或更新服务访问密钥</p>
            </div>
            <span class="credentials-mode-chip" :class="{ 'is-editing': selectedEntry }">
              {{ selectedEntry ? '编辑中' : '新建' }}
            </span>
          </header>

          <div class="credentials-block">
            <div class="credentials-block-label">服务类型</div>

            <input
              v-model="selectedService"
              list="credential-service-options"
              type="text"
              class="credentials-input"
              placeholder="输入服务类型，例如：github_app / telegram_bot / aliyun_oss"
              @input="handleServiceInput"
            >

            <datalist id="credential-service-options">
              <option v-for="service in serviceSuggestions" :key="service.value" :value="service.value">
                {{ service.label }}
              </option>
            </datalist>

            <div class="credentials-suggestions">
              <button
                v-for="service in serviceSuggestions"
                :key="service.value"
                type="button"
                class="credentials-suggestion"
                :class="{ 'is-active': selectedService === service.value }"
                @click="chooseService(service.value)"
              >
                {{ service.label }}
              </button>
            </div>

            <div class="credentials-hint">
              {{ serviceMeta.hint }}
            </div>
          </div>

          <label class="credentials-block">
            <span class="credentials-block-label">凭据别名</span>
            <input
              v-model="form.name"
              type="text"
              class="credentials-input"
              placeholder="凭据别名，例如：主号 / 生产环境 / 研发机器人"
            >
          </label>

          <div class="credentials-block">
            <div class="credentials-block-head">
              <span class="credentials-block-label">凭据字段</span>
              <button type="button" class="credentials-add-field" @click="addField">
                <Plus />
                添加字段
              </button>
            </div>

            <div
              v-for="field in form.fields"
              :key="field.id"
              class="credentials-field-row"
            >
              <input
                v-model="field.key"
                type="text"
                class="credentials-input credentials-field-key"
                placeholder="字段名，例如 app_id / token"
              >

              <input
                v-model="field.value"
                :type="field.secret ? 'password' : 'text'"
                class="credentials-input credentials-field-value"
                :placeholder="fieldPlaceholder(field)"
              >

              <button
                type="button"
                class="credentials-icon-button"
                :title="field.secret ? '显示字段值' : '按敏感字段保存'"
                @click="toggleFieldSecret(field.id)"
              >
                <EyeOff v-if="field.secret" />
                <Eye v-else />
              </button>

              <button
                type="button"
                class="credentials-icon-button is-danger"
                title="移除字段"
                @click="removeField(field.id)"
              >
                <Trash2 />
              </button>
            </div>
          </div>

          <label class="credentials-default-toggle">
            <input v-model="form.is_default" type="checkbox">
            保存后设为默认凭据
          </label>

          <div v-if="errorText" class="credentials-note is-error">
            {{ errorText }}
          </div>

          <div v-if="successText" class="credentials-note is-success">
            {{ successText }}
          </div>

          <div class="credentials-form-actions">
            <button type="submit" class="ikaros-primary-action credentials-submit" :disabled="saving">
              <Loader2 v-if="saving" class="is-spinning" />
              {{ submitLabel }}
            </button>
          </div>
        </form>
      </LiquidGlass>

      <section class="credentials-entries" aria-label="当前凭据">
        <div class="credentials-entries-head">
          <h2 class="credentials-section-label">{{ serviceMeta.label }} · 当前凭据</h2>
          <span class="credentials-count-chip">{{ entries.length }} 条</span>
        </div>

        <div v-if="loading" class="credentials-loading">
          <Loader2 class="is-spinning" />
          正在加载凭据列表
        </div>

        <div v-else-if="!selectedService" class="credentials-empty">
          <TriangleAlert />
          <div>先输入一个服务类型，或点上方预设模板开始配置。</div>
        </div>

        <div v-else-if="!entries.length" class="credentials-empty">
          <TriangleAlert />
          <div>当前服务还没有保存凭据。</div>
        </div>

        <div v-else class="credentials-entry-grid">
          <LiquidGlass
            v-for="entry in entries"
            :key="entry.id"
            :radius="20"
            :optics="compactOptics"
            interactive
            class="credentials-entry"
            :class="{ 'is-selected': selectedEntryId === entry.id }"
          >
            <div class="credentials-entry-inner">
              <header class="credentials-entry-head">
                <span class="credentials-entry-icon"><KeyRound /></span>
                <div class="credentials-entry-title">
                  <strong>{{ entry.name }}</strong>
                  <small>ID: {{ entry.id }}</small>
                </div>
                <span v-if="entry.is_default" class="credentials-default-badge">
                  <Star />
                  默认
                </span>
                <button
                  type="button"
                  class="credentials-entry-edit"
                  @click="selectEntry(entry)"
                >
                  <SquarePen />
                  编辑
                </button>
              </header>

              <div class="credentials-entry-fields">
                <div
                  v-for="field in describeFields(entry.service, entry.data)"
                  :key="field.key"
                  class="credentials-entry-field"
                >
                  <span>{{ field.label }}</span>
                  <span>{{ maskValue(field) }}</span>
                </div>
              </div>

              <footer class="credentials-entry-foot">
                <span class="credentials-entry-notice">
                  <CheckCircle2 />
                  {{ entryNotice(entry.service) }}
                </span>
                <div class="credentials-entry-actions">
                  <button
                    v-if="!entry.is_default"
                    type="button"
                    class="credentials-mini-action"
                    :disabled="defaultingKey === entry.id"
                    @click="markDefault(entry)"
                  >
                    <Loader2 v-if="defaultingKey === entry.id" class="is-spinning" />
                    <Star v-else />
                    设为默认
                  </button>
                  <button
                    type="button"
                    class="credentials-mini-action is-danger"
                    :disabled="deletingKey === entry.id"
                    @click="removeEntry(entry)"
                  >
                    <Loader2 v-if="deletingKey === entry.id" class="is-spinning" />
                    <Trash2 v-else />
                    删除
                  </button>
                </div>
              </footer>
            </div>
          </LiquidGlass>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.credentials-page {
  gap: 22px;
}

.credentials-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.credentials-header-actions svg {
  width: 15px;
  height: 15px;
}

.credentials-header-actions .ikaros-primary-action {
  border: 0;
  cursor: pointer;
}

.credentials-layout {
  display: grid;
  min-width: 0;
  gap: 20px;
  align-items: start;
}

.credentials-form-panel {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .credentials-form-panel {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.86);
}

.credentials-form {
  display: grid;
  gap: 16px;
  padding: 22px;
}

.credentials-form-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 15px;
  border-bottom: 1px solid var(--ikaros-line);
}

.credentials-form-icon,
.credentials-entry-icon {
  display: grid;
  flex: none;
  place-items: center;
  border: 1px solid rgba(232, 93, 142, 0.22);
  background: rgba(232, 93, 142, 0.09);
  color: var(--ikaros-pink);
}

.credentials-form-icon {
  width: 44px;
  height: 44px;
  border-radius: 15px;
}

.credentials-form-icon svg {
  width: 21px;
  height: 21px;
}

.credentials-form-title {
  min-width: 0;
  flex: 1;
}

.credentials-form-title h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.credentials-form-title p {
  margin: 3px 0 0;
  color: var(--ikaros-muted);
  font-size: 12px;
}

.credentials-mode-chip {
  flex: none;
  padding: 5px 10px;
  border-radius: 999px;
  background: var(--panel-muted);
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 750;
}

.credentials-mode-chip.is-editing {
  background: rgba(42, 140, 138, 0.1);
  color: var(--ikaros-eye);
}

.credentials-block {
  display: grid;
  gap: 10px;
}

.credentials-block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.credentials-block-label {
  color: var(--ikaros-copy);
  font-size: 13px;
  font-weight: 700;
}

.credentials-input {
  width: 100%;
  min-width: 0;
  padding: 10px 13px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.55);
  color: var(--ikaros-ink);
  font-size: 13px;
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease, background-color 160ms ease;
}

:global(.dark) .credentials-input {
  background: rgba(255, 255, 255, 0.06);
}

.credentials-input:focus {
  border-color: rgba(232, 93, 142, 0.45);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.12);
}

:global(.dark) .credentials-input:focus {
  background: rgba(255, 255, 255, 0.09);
}

.credentials-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.credentials-suggestion {
  padding: 6px 12px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.4);
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 650;
  transition: border-color 160ms ease, color 160ms ease, background-color 160ms ease;
}

:global(.dark) .credentials-suggestion {
  background: rgba(255, 255, 255, 0.05);
}

.credentials-suggestion:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.credentials-suggestion.is-active {
  border-color: rgba(232, 93, 142, 0.4);
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
  font-weight: 750;
}

.credentials-hint {
  padding: 11px 13px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: var(--panel-muted);
  color: var(--ikaros-copy);
  font-size: 12px;
  line-height: 1.6;
}

.credentials-add-field {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 11px;
  border: 1px dashed rgba(232, 93, 142, 0.35);
  border-radius: 999px;
  background: rgba(232, 93, 142, 0.05);
  color: var(--ikaros-pink);
  font-size: 12px;
  font-weight: 700;
  transition: background-color 160ms ease, border-color 160ms ease;
}

.credentials-add-field:hover {
  border-color: rgba(232, 93, 142, 0.55);
  background: rgba(232, 93, 142, 0.1);
}

.credentials-add-field svg {
  width: 13px;
  height: 13px;
}

.credentials-field-row {
  display: grid;
  grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr) auto auto;
  gap: 8px;
  align-items: center;
}

.credentials-icon-button {
  display: grid;
  width: 38px;
  height: 38px;
  flex: none;
  place-items: center;
  border: 1px solid var(--ikaros-line);
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.45);
  color: var(--ikaros-copy);
  transition: border-color 160ms ease, color 160ms ease, background-color 160ms ease;
}

:global(.dark) .credentials-icon-button {
  background: rgba(255, 255, 255, 0.05);
}

.credentials-icon-button:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.credentials-icon-button.is-danger:hover {
  border-color: rgba(198, 55, 65, 0.3);
  background: rgba(198, 55, 65, 0.07);
  color: #c63741;
}

.credentials-icon-button svg {
  width: 15px;
  height: 15px;
}

.credentials-default-toggle {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 13px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: var(--panel-muted);
  color: var(--ikaros-copy);
  font-size: 13px;
  cursor: pointer;
}

.credentials-default-toggle input {
  width: 15px;
  height: 15px;
  accent-color: var(--ikaros-pink);
}

.credentials-note {
  padding: 11px 14px;
  border: 1px solid;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.5;
}

.credentials-note.is-error {
  border-color: rgba(198, 55, 65, 0.18);
  background: rgba(198, 55, 65, 0.07);
  color: #c63741;
}

.credentials-note.is-success {
  border-color: rgba(47, 125, 74, 0.2);
  background: rgba(47, 125, 74, 0.08);
  color: var(--ikaros-rind);
}

.credentials-form-actions {
  display: flex;
  gap: 10px;
}

.credentials-submit {
  flex: 1;
  border: 0;
  cursor: pointer;
}

.credentials-submit:disabled {
  cursor: wait;
  opacity: 0.7;
}

.credentials-submit svg {
  width: 15px;
  height: 15px;
}

.credentials-entries {
  display: grid;
  min-width: 0;
  gap: 12px;
  align-content: start;
}

.credentials-entries-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 4px;
}

.credentials-section-label {
  margin: 0;
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.credentials-count-chip {
  padding: 5px 10px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: var(--panel-muted);
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 700;
}

.credentials-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 4px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.credentials-loading svg {
  width: 16px;
  height: 16px;
}

.credentials-empty {
  display: flex;
  min-height: 220px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border: 1px dashed var(--ikaros-line);
  border-radius: 18px;
  color: var(--ikaros-muted);
  font-size: 13px;
  text-align: center;
}

.credentials-empty svg {
  width: 22px;
  height: 22px;
}

.credentials-entry-grid {
  display: grid;
  gap: 14px;
}

.credentials-entry {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.8);
}

:global(.dark) .credentials-entry {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.82);
}

.credentials-entry.is-selected {
  border-color: rgba(232, 93, 142, 0.4);
  box-shadow:
    0 16px 40px rgba(232, 93, 142, 0.12),
    inset 0 0 22px rgba(255, 255, 255, 0.28);
}

.credentials-entry-inner {
  display: grid;
  gap: 13px;
  padding: 17px;
}

.credentials-entry-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.credentials-entry-icon {
  width: 36px;
  height: 36px;
  border-radius: 12px;
}

.credentials-entry-icon svg {
  width: 17px;
  height: 17px;
}

.credentials-entry-title {
  display: grid;
  min-width: 0;
  flex: 1;
  gap: 2px;
}

.credentials-entry-title strong {
  overflow: hidden;
  color: var(--ikaros-ink);
  font-size: 14px;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.credentials-entry-title small {
  color: var(--ikaros-muted);
  font-size: 10px;
}

.credentials-default-badge {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 4px;
  padding: 4px 9px;
  border-radius: 999px;
  background: var(--ikaros-pink);
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  box-shadow: 0 4px 12px rgba(232, 93, 142, 0.28);
}

.credentials-default-badge svg {
  width: 11px;
  height: 11px;
}

.credentials-entry-edit {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 5px;
  padding: 6px 11px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.45);
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 700;
  transition: border-color 160ms ease, color 160ms ease;
}

:global(.dark) .credentials-entry-edit {
  background: rgba(255, 255, 255, 0.06);
}

.credentials-entry-edit:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.credentials-entry-edit svg {
  width: 12px;
  height: 12px;
}

.credentials-entry-fields {
  display: grid;
  gap: 7px;
  padding: 11px 13px;
  border: 1px solid var(--ikaros-line);
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.4);
}

:global(.dark) .credentials-entry-fields {
  background: rgba(255, 255, 255, 0.04);
}

.credentials-entry-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  font-size: 12px;
}

.credentials-entry-field > span:first-child {
  flex: none;
  color: var(--ikaros-muted);
}

.credentials-entry-field > span:last-child {
  overflow: hidden;
  color: var(--ikaros-ink);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.credentials-entry-foot {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.credentials-entry-notice {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 6px;
  color: var(--ikaros-rind);
  font-size: 12px;
  font-weight: 650;
}

.credentials-entry-notice svg {
  width: 14px;
  height: 14px;
  flex: none;
}

.credentials-entry-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.credentials-mini-action {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 11px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.45);
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 700;
  transition: border-color 160ms ease, color 160ms ease, background-color 160ms ease;
}

:global(.dark) .credentials-mini-action {
  background: rgba(255, 255, 255, 0.06);
}

.credentials-mini-action:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.credentials-mini-action.is-danger:hover {
  border-color: rgba(198, 55, 65, 0.3);
  background: rgba(198, 55, 65, 0.07);
  color: #c63741;
}

.credentials-mini-action:disabled {
  cursor: wait;
  opacity: 0.7;
}

.credentials-mini-action svg {
  width: 12px;
  height: 12px;
}

.is-spinning {
  animation: credentials-spin 850ms linear infinite;
}

@keyframes credentials-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (min-width: 1100px) {
  .credentials-layout {
    grid-template-columns: minmax(380px, 460px) minmax(0, 1fr);
  }

  .credentials-form-panel {
    position: sticky;
    top: 26px;
  }

  .credentials-entry-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .credentials-field-row {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto auto;
  }

  .credentials-entry-foot {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning {
    animation: none;
  }
}
</style>
