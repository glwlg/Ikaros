<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref, watch } from 'vue'
import { Bot, Loader2, Plus, Save, Trash2 } from 'lucide-vue-next'

import { getRuntimeSnapshot, patchRuntimeSnapshot, type RuntimeSnapshot } from '@/api/admin'

const snapshot = ref<RuntimeSnapshot | null>(null)
const modelConfigForm = ref<ModelConfigForm | null>(null)
const loading = ref(false)
const saving = ref(false)
const errorText = ref('')
const successText = ref('')
const corsInput = ref('')
const modelsConfigError = ref('')

const roleOrder = ['primary', 'routing', 'vision', 'image_generation', 'voice'] as const
const inputTypeOptions = ['text', 'image', 'voice'] as const
const outputTypeOptions = ['text', 'image', 'voice', 'video'] as const

type RoleKey = (typeof roleOrder)[number]
type InputType = (typeof inputTypeOptions)[number]
type OutputType = (typeof outputTypeOptions)[number]
type NumericValue = number | ''

interface CostForm {
    input: NumericValue
    output: NumericValue
    cacheRead: NumericValue
    cacheWrite: NumericValue
    extras: Record<string, unknown>
}

interface ModelForm {
    uid: string
    id: string
    name: string
    reasoning: boolean
    input: InputType[]
    output: OutputType[]
    cost: CostForm
    contextWindow: NumericValue
    maxTokens: NumericValue
    extras: Record<string, unknown>
}

interface ProviderForm {
    uid: string
    name: string
    baseUrl: string
    apiKey: string
    api: string
    models: ModelForm[]
    extras: Record<string, unknown>
}

interface RoleConfigForm {
    bindingUid: string
    bindingKey: string
    poolKey: string
    poolUids: string[]
    poolMetaByUid: Record<string, Record<string, unknown>>
}

interface ModelConfigForm {
    mode: string
    topLevelExtras: Record<string, unknown>
    modelExtras: Record<string, unknown>
    poolExtras: Record<string, unknown>
    providers: ProviderForm[]
    roles: Record<RoleKey, RoleConfigForm>
}

interface ModelOption {
    uid: string
    key: string
    providerName: string
    modelId: string
    name: string
    input: InputType[]
    output: OutputType[]
    reasoning: boolean
}

const roleLabels: Record<RoleKey, string> = {
    primary: 'Primary',
    routing: 'Routing',
    vision: 'Vision',
    image_generation: 'Image Generation',
    voice: 'Voice',
}

const roleStorageKeys: Record<RoleKey, string[]> = {
    primary: ['primary'],
    routing: ['routing'],
    vision: ['vision', 'image'],
    image_generation: ['image_generation', 'image_gen'],
    voice: ['voice'],
}

const managedRoleKeys = new Set(Object.values(roleStorageKeys).flat())
const primaryRoleStorageKey = (role: RoleKey) => roleStorageKeys[role][0] || role
const roleRequiredInputs: Record<RoleKey, InputType[]> = {
    primary: ['text'],
    routing: ['text'],
    vision: ['image'],
    image_generation: [],
    voice: ['voice'],
}
const roleRequiredOutputs: Record<RoleKey, OutputType[]> = {
    primary: [],
    routing: [],
    vision: [],
    image_generation: ['image'],
    voice: [],
}
const roleCapabilityText: Record<RoleKey, string> = {
    primary: '至少支持 text 输入',
    routing: '至少支持 text 输入',
    vision: '至少支持 image 输入',
    image_generation: '至少支持 image 输出',
    voice: '至少支持 voice 输入',
}

let uidCounter = 0

const nextUid = (prefix: string) => `${prefix}-${uidCounter++}`

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

const asObject = (value: unknown): Record<string, unknown> | null => {
    if (!value || Array.isArray(value) || typeof value !== 'object') {
        return null
    }
    return { ...(value as Record<string, unknown>) }
}

const omitKeys = (source: Record<string, unknown>, keys: string[]) =>
    Object.fromEntries(Object.entries(source).filter(([key]) => !keys.includes(key)))

const normalizeInputTypes = (value: unknown): InputType[] => {
    const normalized: InputType[] = []
    if (!Array.isArray(value)) {
        return normalized
    }
    for (const item of value) {
        const token = String(item || '').trim().toLowerCase() as InputType
        if (inputTypeOptions.includes(token) && !normalized.includes(token)) {
            normalized.push(token)
        }
    }
    return normalized
}

const normalizeOutputTypes = (value: unknown): OutputType[] => {
    const normalized: OutputType[] = []
    if (!Array.isArray(value)) {
        return normalized
    }
    for (const item of value) {
        const token = String(item || '').trim().toLowerCase() as OutputType
        if (outputTypeOptions.includes(token) && !normalized.includes(token)) {
            normalized.push(token)
        }
    }
    return normalized
}

const coerceNumber = (value: unknown, fallback: number, minimum = 0) => {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) {
        return fallback
    }
    return Math.max(minimum, parsed)
}

const coerceInteger = (value: unknown, fallback: number, minimum = 1) =>
    Math.max(minimum, Math.round(coerceNumber(value, fallback, minimum)))

const buildModelKey = (providerName: string, modelId: string) =>
    `${providerName.trim()}/${modelId.trim()}`

const createEmptyModel = (): ModelForm => ({
    uid: nextUid('model'),
    id: '',
    name: '',
    reasoning: false,
    input: ['text'],
    output: ['text'],
    cost: {
        input: 0,
        output: 0,
        cacheRead: 0,
        cacheWrite: 0,
        extras: {},
    },
    contextWindow: 1000000,
    maxTokens: 65536,
    extras: {},
})

const createEmptyProvider = (): ProviderForm => ({
    uid: nextUid('provider'),
    name: '',
    baseUrl: '',
    apiKey: '',
    api: 'openai-completions',
    models: [],
    extras: {},
})

const availableModelOptions = computed<ModelOption[]>(() => {
    const form = modelConfigForm.value
    if (!form) {
        return []
    }
    return form.providers.flatMap(provider =>
        provider.models
            .map(model => {
                const providerName = provider.name.trim()
                const modelId = model.id.trim()
                if (!providerName || !modelId) {
                    return null
                }
                return {
                    uid: model.uid,
                    key: buildModelKey(providerName, modelId),
                    providerName,
                    modelId,
                    name: model.name.trim() || modelId,
                    input: [...model.input],
                    output: [...model.output],
                    reasoning: Boolean(model.reasoning),
                }
            })
            .filter((item): item is ModelOption => Boolean(item))
    )
})

const availableModelMap = computed<Record<string, ModelOption>>(() =>
    Object.fromEntries(availableModelOptions.value.map(option => [option.uid, option]))
)

const platformEntries = computed(() => Object.entries(snapshot.value?.runtime_config.platforms || {}))
const featureEntries = computed(() => Object.entries(snapshot.value?.runtime_config.features || {}))

const roleCards = computed(() =>
    roleOrder.map(role => {
        const roleConfig = modelConfigForm.value?.roles[role]
        const selectedOption = roleConfig ? availableModelMap.value[roleConfig.bindingUid] : null
        const poolOptions = rolePoolOptions(role)
        return {
            role,
            label: roleLabels[role],
            currentKey: selectedOption?.key || '',
            poolCount: poolOptions.length,
            bindingOptions: poolOptions,
            candidateOptions: roleCandidateOptions(role),
            capabilityText: roleCapabilityText[role],
        }
    })
)

const roleCompatibilityStatus = (role: RoleKey, option: ModelOption | null | undefined) => {
    if (!option) {
        return 'ineligible' as const
    }
    const requiredInputs = roleRequiredInputs[role]
    const requiredOutputs = roleRequiredOutputs[role]
    for (const inputType of requiredInputs) {
        if (!option.input.includes(inputType)) {
            return 'ineligible' as const
        }
    }
    for (const outputType of requiredOutputs) {
        if (!option.output.length) {
            return 'legacy' as const
        }
        if (!option.output.includes(outputType)) {
            return 'ineligible' as const
        }
    }
    return 'eligible' as const
}

const roleCandidateOptions = (role: RoleKey) =>
    availableModelOptions.value.filter(option => roleCompatibilityStatus(role, option) === 'eligible')

const rolePoolOptions = (role: RoleKey) => {
    const roleConfig = modelConfigForm.value?.roles[role]
    if (!roleConfig) {
        return []
    }
    return roleConfig.poolUids
        .map(uid => availableModelMap.value[uid])
        .filter((option): option is ModelOption => roleCompatibilityStatus(role, option) !== 'ineligible')
}

const normalizeRoleSelections = () => {
    const form = modelConfigForm.value
    if (!form) {
        return
    }
    for (const role of roleOrder) {
        const roleConfig = form.roles[role]
        const compatibleUids = new Set(
            availableModelOptions.value
                .filter(option => roleCompatibilityStatus(role, option) !== 'ineligible')
                .map(option => option.uid)
        )
        const filteredPoolUids = roleConfig.poolUids.filter(uid => compatibleUids.has(uid))
        if (filteredPoolUids.length !== roleConfig.poolUids.length) {
            roleConfig.poolUids = filteredPoolUids
        }
        for (const uid of Object.keys(roleConfig.poolMetaByUid)) {
            if (!compatibleUids.has(uid)) {
                delete roleConfig.poolMetaByUid[uid]
            }
        }
        if (roleConfig.bindingUid && !compatibleUids.has(roleConfig.bindingUid)) {
            roleConfig.bindingUid = ''
        }
        if (roleConfig.bindingUid && !roleConfig.poolUids.includes(roleConfig.bindingUid)) {
            roleConfig.poolUids = [...roleConfig.poolUids, roleConfig.bindingUid]
            roleConfig.poolMetaByUid[roleConfig.bindingUid] = roleConfig.poolMetaByUid[roleConfig.bindingUid] || {}
        }
    }
}

const hydrateModelsConfigForm = (payload: Record<string, unknown>) => {
    uidCounter = 0
    const rawProviders = asObject(payload.providers) || {}
    const providers: ProviderForm[] = []
    const modelUidByKey: Record<string, string> = {}

    for (const [providerName, rawProviderValue] of Object.entries(rawProviders)) {
        const rawProvider = asObject(rawProviderValue)
        if (!rawProvider) {
            continue
        }
        const provider: ProviderForm = {
            uid: nextUid('provider'),
            name: providerName,
            baseUrl: String(rawProvider.baseUrl || '').trim(),
            apiKey: String(rawProvider.apiKey || ''),
            api: String(rawProvider.api || '').trim() || 'openai-completions',
            models: [],
            extras: omitKeys(rawProvider, ['baseUrl', 'apiKey', 'api', 'models']),
        }

        const rawModels = Array.isArray(rawProvider.models) ? rawProvider.models : []
        for (const item of rawModels) {
            const rawModel = asObject(item)
            if (!rawModel) {
                continue
            }
            const cost = asObject(rawModel.cost) || {}
            const model: ModelForm = {
                uid: nextUid('model'),
                id: String(rawModel.id || '').trim(),
                name: String(rawModel.name || rawModel.id || '').trim(),
                reasoning: Boolean(rawModel.reasoning),
                input: normalizeInputTypes(rawModel.input),
                output: normalizeOutputTypes(rawModel.output),
                cost: {
                    input: coerceNumber(cost.input, 0, 0),
                    output: coerceNumber(cost.output, 0, 0),
                    cacheRead: coerceNumber(cost.cacheRead, 0, 0),
                    cacheWrite: coerceNumber(cost.cacheWrite, 0, 0),
                    extras: omitKeys(cost, ['input', 'output', 'cacheRead', 'cacheWrite']),
                },
                contextWindow: coerceInteger(rawModel.contextWindow, 1000000, 1),
                maxTokens: coerceInteger(rawModel.maxTokens, 65536, 1),
                extras: omitKeys(rawModel, ['id', 'name', 'reasoning', 'input', 'output', 'cost', 'contextWindow', 'maxTokens']),
            }
            provider.models.push(model)
            if (provider.name && model.id) {
                modelUidByKey[buildModelKey(provider.name, model.id)] = model.uid
            }
        }

        providers.push(provider)
    }

    const rawModelBindings = asObject(payload.model) || {}
    const rawPools = asObject(payload.models) || {}
    const roles = {} as Record<RoleKey, RoleConfigForm>

    for (const role of roleOrder) {
        const bindingKey =
            roleStorageKeys[role].find(key => typeof rawModelBindings[key] === 'string' && String(rawModelBindings[key]).trim()) ||
            primaryRoleStorageKey(role)
        const selectedModelKey = String(rawModelBindings[bindingKey] || '').trim()
        const poolKey =
            roleStorageKeys[role].find(key => Object.prototype.hasOwnProperty.call(rawPools, key)) ||
            primaryRoleStorageKey(role)
        const rawPool = rawPools[poolKey]
        const poolUids: string[] = []
        const poolMetaByUid: Record<string, Record<string, unknown>> = {}

        if (Array.isArray(rawPool)) {
            for (const item of rawPool) {
                const modelKey = String(item || '').trim()
                const uid = modelUidByKey[modelKey]
                if (uid && !poolUids.includes(uid)) {
                    poolUids.push(uid)
                }
            }
        } else {
            const poolObject = asObject(rawPool)
            if (poolObject) {
                for (const [modelKey, rawMeta] of Object.entries(poolObject)) {
                    const uid = modelUidByKey[String(modelKey || '').trim()]
                    if (!uid || poolUids.includes(uid)) {
                        continue
                    }
                    poolUids.push(uid)
                    poolMetaByUid[uid] = asObject(rawMeta) || {}
                }
            }
        }

        roles[role] = {
            bindingUid: modelUidByKey[selectedModelKey] || '',
            bindingKey,
            poolKey,
            poolUids,
            poolMetaByUid,
        }
    }

    modelConfigForm.value = {
        mode: String(payload.mode || '').trim() || 'merge',
        topLevelExtras: omitKeys(payload, ['mode', 'model', 'models', 'providers']),
        modelExtras: Object.fromEntries(
            Object.entries(rawModelBindings).filter(([key]) => !managedRoleKeys.has(key))
        ),
        poolExtras: Object.fromEntries(
            Object.entries(rawPools).filter(([key]) => !managedRoleKeys.has(key))
        ),
        providers,
        roles,
    }
    normalizeRoleSelections()
    modelsConfigError.value = ''
}

const hydrate = (payload: RuntimeSnapshot) => {
    snapshot.value = payload
    corsInput.value = (payload.runtime_config.cors.allowed_origins || []).join('\n')
    hydrateModelsConfigForm(payload.models_config.payload || {})
    errorText.value = ''
    successText.value = ''
}

const load = async () => {
    loading.value = true
    errorText.value = ''
    successText.value = ''
    try {
        const response = await getRuntimeSnapshot()
        hydrate(response.data)
    } catch (error) {
        errorText.value = parseErrorMessage(error, '运行配置加载失败')
    } finally {
        loading.value = false
    }
}

const resetModelsConfigForm = () => {
    if (!snapshot.value) {
        return
    }
    hydrateModelsConfigForm(snapshot.value.models_config.payload || {})
    modelsConfigError.value = ''
    successText.value = ''
}

const togglePlatform = (name: string, value: boolean) => {
    if (!snapshot.value) return
    snapshot.value.runtime_config.platforms[name] = value
}

const toggleFeature = (name: string, value: boolean) => {
    if (!snapshot.value) return
    snapshot.value.runtime_config.features[name] = value
}

const addProvider = () => {
    if (!modelConfigForm.value) {
        return
    }
    modelConfigForm.value.providers.push(createEmptyProvider())
}

const addProviderModel = (providerUid: string) => {
    const provider = modelConfigForm.value?.providers.find(item => item.uid === providerUid)
    if (!provider) {
        return
    }
    provider.models.push(createEmptyModel())
}

const detachModelFromRoles = (modelUid: string) => {
    const form = modelConfigForm.value
    if (!form) {
        return
    }
    for (const role of roleOrder) {
        const roleConfig = form.roles[role]
        if (roleConfig.bindingUid === modelUid) {
            roleConfig.bindingUid = ''
        }
        roleConfig.poolUids = roleConfig.poolUids.filter(uid => uid !== modelUid)
        delete roleConfig.poolMetaByUid[modelUid]
    }
}

const removeProviderModel = (providerUid: string, modelUid: string) => {
    const provider = modelConfigForm.value?.providers.find(item => item.uid === providerUid)
    if (!provider) {
        return
    }
    detachModelFromRoles(modelUid)
    provider.models = provider.models.filter(model => model.uid !== modelUid)
}

const removeProvider = (providerUid: string) => {
    if (!modelConfigForm.value) {
        return
    }
    const provider = modelConfigForm.value.providers.find(item => item.uid === providerUid)
    if (!provider) {
        return
    }
    for (const model of provider.models) {
        detachModelFromRoles(model.uid)
    }
    modelConfigForm.value.providers = modelConfigForm.value.providers.filter(provider => provider.uid !== providerUid)
}

const isModelInRolePool = (role: RoleKey, modelUid: string) =>
    Boolean(modelConfigForm.value?.roles[role].poolUids.includes(modelUid))

const toggleRolePoolModel = (role: RoleKey, modelUid: string) => {
    const roleConfig = modelConfigForm.value?.roles[role]
    if (!roleConfig) {
        return
    }
    const option = availableModelMap.value[modelUid]
    if (roleCompatibilityStatus(role, option) !== 'eligible') {
        return
    }
    if (roleConfig.poolUids.includes(modelUid)) {
        roleConfig.poolUids = roleConfig.poolUids.filter(uid => uid !== modelUid)
        delete roleConfig.poolMetaByUid[modelUid]
        if (roleConfig.bindingUid === modelUid) {
            roleConfig.bindingUid = ''
        }
        return
    }
    roleConfig.poolUids = [...roleConfig.poolUids, modelUid]
    roleConfig.poolMetaByUid[modelUid] = roleConfig.poolMetaByUid[modelUid] || {}
}

const setRoleBinding = (role: RoleKey, modelUid: string) => {
    const roleConfig = modelConfigForm.value?.roles[role]
    if (!roleConfig) {
        return
    }
    const option = availableModelMap.value[modelUid]
    if (modelUid && roleCompatibilityStatus(role, option) !== 'eligible') {
        return
    }
    roleConfig.bindingUid = modelUid
    if (modelUid && !roleConfig.poolUids.includes(modelUid)) {
        roleConfig.poolUids = [...roleConfig.poolUids, modelUid]
        roleConfig.poolMetaByUid[modelUid] = roleConfig.poolMetaByUid[modelUid] || {}
    }
}

const buildModelsConfigSubmission = () => {
    const form = modelConfigForm.value
    if (!form) {
        return null
    }

    modelsConfigError.value = ''
    const providersPayload: Record<string, unknown> = {}
    const modelKeyByUid: Record<string, string> = {}
    const seenProviderNames = new Set<string>()

    for (const provider of form.providers) {
        const providerName = provider.name.trim()
        if (!providerName) {
            modelsConfigError.value = 'Provider 名称不能为空'
            return null
        }
        if (seenProviderNames.has(providerName)) {
            modelsConfigError.value = `Provider 名称重复：${providerName}`
            return null
        }
        seenProviderNames.add(providerName)

        const seenModelIds = new Set<string>()
        const modelsPayload = []
        for (const model of provider.models) {
            const modelId = model.id.trim()
            if (!modelId) {
                modelsConfigError.value = `${providerName} 下存在空的模型 ID`
                return null
            }
            if (seenModelIds.has(modelId)) {
                modelsConfigError.value = `${providerName} 下模型 ID 重复：${modelId}`
                return null
            }
            seenModelIds.add(modelId)
            modelKeyByUid[model.uid] = buildModelKey(providerName, modelId)
            modelsPayload.push({
                ...model.extras,
                id: modelId,
                name: model.name.trim() || modelId,
                reasoning: Boolean(model.reasoning),
                input: [...model.input],
                output: [...model.output],
                cost: {
                    ...model.cost.extras,
                    input: coerceNumber(model.cost.input, 0, 0),
                    output: coerceNumber(model.cost.output, 0, 0),
                    cacheRead: coerceNumber(model.cost.cacheRead, 0, 0),
                    cacheWrite: coerceNumber(model.cost.cacheWrite, 0, 0),
                },
                contextWindow: coerceInteger(model.contextWindow, 1000000, 1),
                maxTokens: coerceInteger(model.maxTokens, 65536, 1),
            })
        }

        providersPayload[providerName] = {
            ...provider.extras,
            baseUrl: provider.baseUrl.trim(),
            apiKey: provider.apiKey,
            api: provider.api.trim() || 'openai-completions',
            models: modelsPayload,
        }
    }

    const modelPayload: Record<string, unknown> = { ...form.modelExtras }
    const poolsPayload: Record<string, unknown> = { ...form.poolExtras }
    const modelRoles: Record<string, string> = {}

    for (const role of roleOrder) {
        const roleConfig = form.roles[role]
        const bindingKey = roleConfig.bindingKey || primaryRoleStorageKey(role)
        const poolKey = roleConfig.poolKey || primaryRoleStorageKey(role)
        const selectedModelKey = roleConfig.bindingUid ? modelKeyByUid[roleConfig.bindingUid] : ''

        if (roleConfig.bindingUid && !selectedModelKey) {
            modelsConfigError.value = `${roleLabels[role]} 绑定了一个未完整配置的模型`
            return null
        }
        if (selectedModelKey) {
            modelPayload[bindingKey] = selectedModelKey
            modelRoles[role] = selectedModelKey
        }

        const poolPayload: Record<string, Record<string, unknown>> = {}
        for (const modelUid of roleConfig.poolUids) {
            const modelKey = modelKeyByUid[modelUid]
            if (!modelKey || poolPayload[modelKey]) {
                continue
            }
            poolPayload[modelKey] = { ...(roleConfig.poolMetaByUid[modelUid] || {}) }
        }
        if (Object.keys(poolPayload).length > 0) {
            poolsPayload[poolKey] = poolPayload
        }
    }

    return {
        modelRoles,
        modelsConfig: {
            ...form.topLevelExtras,
            mode: form.mode.trim() || 'merge',
            model: modelPayload,
            models: poolsPayload,
            providers: providersPayload,
        },
    }
}

const save = async () => {
    if (!snapshot.value) {
        return
    }
    errorText.value = ''
    successText.value = ''
    const submission = buildModelsConfigSubmission()
    if (!submission) {
        return
    }
    saving.value = true
    try {
        const response = await patchRuntimeSnapshot({
            platforms: snapshot.value.runtime_config.platforms,
            features: snapshot.value.runtime_config.features,
            cors_allowed_origins: corsInput.value.split('\n').map(item => item.trim()).filter(Boolean),
            model_roles: submission.modelRoles,
            models_config: submission.modelsConfig,
            memory_provider: snapshot.value.memory.provider,
        })
        hydrate(response.data)
        successText.value = '运行配置已保存'
    } catch (error) {
        errorText.value = parseErrorMessage(error, '运行配置保存失败')
    } finally {
        saving.value = false
    }
}

watch(
    () =>
        roleOrder.map(role => ({
            role,
            compatibility: availableModelOptions.value.map(option => ({
                uid: option.uid,
                status: roleCompatibilityStatus(role, option),
            })),
        })),
    () => {
        normalizeRoleSelections()
    },
    { deep: true }
)

onMounted(load)
</script>

<template>
  <div class="space-y-6 p-6 md:p-8">
    <section class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Runtime</div>
          <h2 class="mt-1 text-2xl font-semibold text-slate-900">运行配置</h2>
          <p class="mt-2 max-w-3xl text-sm leading-7 text-slate-500">
            模型配置已经展开为结构化表单，直接在这里维护 `mode`、角色绑定、角色池、provider 和模型参数，不再要求手改 `models.json`。
          </p>
        </div>
        <button
          class="inline-flex items-center gap-2 rounded-2xl bg-slate-950 px-4 py-3 text-sm font-medium text-white transition hover:bg-slate-800 disabled:opacity-60"
          :disabled="saving || loading || !snapshot || !modelConfigForm"
          @click="save"
        >
          <Loader2 v-if="saving" class="h-4 w-4 animate-spin" />
          <Save v-else class="h-4 w-4" />
          保存变更
        </button>
      </div>

      <div v-if="errorText" class="mt-5 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
        {{ errorText }}
      </div>
      <div v-if="successText" class="mt-4 rounded-2xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700">
        {{ successText }}
      </div>
      <div v-if="modelsConfigError" class="mt-4 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
        {{ modelsConfigError }}
      </div>
    </section>

    <div v-if="loading" class="flex items-center gap-2 rounded-[28px] border border-slate-200 bg-white px-5 py-4 text-sm text-slate-500 shadow-sm">
      <Loader2 class="h-4 w-4 animate-spin" />
      正在加载配置
    </div>

    <template v-else-if="snapshot && modelConfigForm">
      <section class="grid gap-6 xl:grid-cols-2">
        <div class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
          <div class="text-sm font-semibold text-slate-900">平台开关</div>
          <div class="mt-4 space-y-3">
            <label v-for="[name, enabled] in platformEntries" :key="name" class="flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div>
                <div class="text-sm text-slate-700">{{ name }}</div>
                <div class="text-xs text-slate-500">控制对应 channel 是否注册和启动</div>
              </div>
              <input :checked="enabled" type="checkbox" class="h-4 w-4" @change="togglePlatform(name, ($event.target as HTMLInputElement).checked)">
            </label>
          </div>
        </div>

        <div class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
          <div class="text-sm font-semibold text-slate-900">功能开关</div>
          <div class="mt-4 space-y-3">
            <label v-for="[name, enabled] in featureEntries" :key="name" class="flex items-center justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3">
              <div>
                <div class="text-sm text-slate-700">{{ name }}</div>
                <div class="text-xs text-slate-500">控制 Web console 与后台功能入口</div>
              </div>
              <input :checked="enabled" type="checkbox" class="h-4 w-4" @change="toggleFeature(name, ($event.target as HTMLInputElement).checked)">
            </label>
          </div>
        </div>
      </section>

      <section class="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_360px]">
        <div class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
          <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div class="text-sm font-semibold text-slate-900">模型配置</div>
                    <div class="mt-1 text-sm text-slate-500">
                        在同一块里同时维护角色绑定、角色池、provider 和具体模型参数。删除 provider 或模型时，相关角色引用会一起清理。
                    </div>
              <div class="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-6 text-slate-600">
                <div>路径：{{ snapshot.models_config.path }}</div>
                <div>文件状态：{{ snapshot.models_config.exists ? '已存在' : '将首次创建' }}</div>
                <div>Provider：{{ modelConfigForm.providers.length }} 个</div>
                <div>模型：{{ availableModelOptions.length }} 个</div>
              </div>
            </div>
            <div class="flex flex-wrap gap-3">
              <button
                type="button"
                class="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 transition hover:bg-slate-100"
                @click="resetModelsConfigForm"
              >
                还原当前加载值
              </button>
              <button
                type="button"
                class="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 transition hover:bg-slate-100"
                @click="addProvider"
              >
                <Plus class="h-4 w-4" />
                新增 Provider
              </button>
            </div>
          </div>

          <div class="mt-6 grid gap-4 md:grid-cols-[220px_minmax(0,1fr)]">
            <label class="space-y-2">
              <div class="text-sm font-medium text-slate-700">Mode</div>
              <input
                v-model="modelConfigForm.mode"
                type="text"
                placeholder="merge"
                class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none transition focus:border-cyan-400 focus:bg-white"
              >
            </label>
            <div class="rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-7 text-slate-600">
              默认模型通过下拉指定，角色池通过标签按钮维护。选中某个默认模型时，它会自动加入对应角色池；从角色池移除时，也会同时清掉该角色的默认模型绑定。
            </div>
          </div>

          <div class="mt-6 grid gap-4 2xl:grid-cols-2">
            <article
              v-for="card in roleCards"
              :key="card.role"
              class="rounded-[24px] border border-slate-200 bg-slate-50 p-5"
            >
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-3">
                  <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-white text-slate-700">
                    <Bot class="h-4 w-4" />
                  </div>
                  <div>
                    <div class="text-xs uppercase tracking-[0.2em] text-slate-400">{{ card.label }}</div>
                    <div class="mt-1 text-sm text-slate-500">当前池 {{ card.poolCount }} 个模型，{{ card.capabilityText }}</div>
                  </div>
                </div>
                <span class="rounded-full bg-white px-2.5 py-1 text-xs text-slate-500">{{ card.role }}</span>
              </div>

              <label class="mt-4 block space-y-2">
                <div class="text-sm font-medium text-slate-700">默认模型</div>
                <select
                  :value="modelConfigForm.roles[card.role].bindingUid"
                  class="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 outline-none focus:border-cyan-400"
                  @change="setRoleBinding(card.role, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">未绑定</option>
                  <option v-for="option in card.bindingOptions" :key="option.uid" :value="option.uid">
                    {{ option.key }}
                  </option>
                </select>
              </label>

              <div class="mt-3 text-xs leading-6 text-slate-500">
                当前绑定：{{ card.currentKey || '未设置' }}
              </div>

              <div class="mt-4">
                <div class="text-sm font-medium text-slate-700">角色池</div>
                <div class="mt-2 flex flex-wrap gap-2" v-if="card.candidateOptions.length">
                  <button
                    v-for="option in card.candidateOptions"
                    :key="`${card.role}-${option.uid}`"
                    type="button"
                    class="rounded-full border px-3 py-2 text-left text-xs transition"
                    :class="isModelInRolePool(card.role, option.uid)
                        ? 'border-cyan-300 bg-cyan-50 text-cyan-800'
                        : 'border-slate-200 bg-white text-slate-600 hover:border-slate-300 hover:bg-slate-100'"
                    @click="toggleRolePoolModel(card.role, option.uid)"
                  >
                    <div class="font-medium">{{ option.key }}</div>
                    <div class="mt-1 text-[11px] uppercase tracking-[0.12em] opacity-75">
                      IN {{ option.input.join(' / ') || '-' }} · OUT {{ option.output.join(' / ') || '-' }}{{ option.reasoning ? ' · reasoning' : '' }}
                    </div>
                  </button>
                </div>
                <div v-else class="mt-2 rounded-2xl border border-dashed border-slate-300 bg-white px-4 py-3 text-sm text-slate-500">
                  当前没有满足该角色能力要求的模型。先在下方补充 {{ card.capabilityText }} 的模型。
                </div>
              </div>
            </article>
          </div>

          <div class="mt-8 flex items-center justify-between gap-4">
            <div>
              <div class="text-sm font-semibold text-slate-900">Provider 与模型明细</div>
              <div class="mt-1 text-sm text-slate-500">完整维护 `baseUrl`、`apiKey`、`api`、输入类型、reasoning、cost`、`contextWindow`、`maxTokens`。</div>
            </div>
            <button
              type="button"
              class="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 transition hover:bg-slate-100"
              @click="addProvider"
            >
              <Plus class="h-4 w-4" />
              新增 Provider
            </button>
          </div>

          <div v-if="!modelConfigForm.providers.length" class="mt-4 rounded-[24px] border border-dashed border-slate-300 bg-slate-50 px-5 py-6 text-sm text-slate-500">
            还没有 Provider。点击“新增 Provider”后，可以继续在每个 Provider 下添加模型。
          </div>

          <div v-else class="mt-4 space-y-5">
            <article
              v-for="provider in modelConfigForm.providers"
              :key="provider.uid"
              class="rounded-[24px] border border-slate-200 bg-slate-50 p-5"
            >
              <div class="flex items-center justify-between gap-3">
                <div>
                  <div class="text-xs uppercase tracking-[0.2em] text-slate-400">Provider</div>
                  <div class="mt-1 text-lg font-semibold text-slate-900">{{ provider.name || '未命名 Provider' }}</div>
                </div>
                <button
                  type="button"
                  class="inline-flex items-center gap-2 rounded-2xl border border-rose-200 bg-white px-3 py-2 text-sm text-rose-600 transition hover:bg-rose-50"
                  @click="removeProvider(provider.uid)"
                >
                  <Trash2 class="h-4 w-4" />
                  删除 Provider
                </button>
              </div>

              <div class="mt-5 grid gap-4 md:grid-cols-2">
                <label class="space-y-2">
                  <div class="text-sm font-medium text-slate-700">Provider 名称</div>
                  <input v-model="provider.name" type="text" placeholder="例如 proxy" class="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 outline-none transition focus:border-cyan-400">
                </label>
                <label class="space-y-2">
                  <div class="text-sm font-medium text-slate-700">API 形式</div>
                  <input v-model="provider.api" type="text" placeholder="openai-completions" class="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 outline-none transition focus:border-cyan-400">
                </label>
                <label class="space-y-2 md:col-span-2">
                  <div class="text-sm font-medium text-slate-700">Base URL</div>
                  <input v-model="provider.baseUrl" type="text" placeholder="https://api.example.com/v1" class="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 outline-none transition focus:border-cyan-400">
                </label>
                <label class="space-y-2 md:col-span-2">
                  <div class="text-sm font-medium text-slate-700">API Key</div>
                  <input v-model="provider.apiKey" type="text" placeholder="sk-..." class="w-full rounded-2xl border border-slate-200 bg-white px-4 py-3 outline-none transition focus:border-cyan-400">
                </label>
              </div>

              <div class="mt-6 flex items-center justify-between gap-4">
                <div>
                  <div class="text-sm font-semibold text-slate-900">模型列表</div>
                  <div class="mt-1 text-sm text-slate-500">模型键会实时使用 `provider/model_id` 生成。</div>
                </div>
                <button
                  type="button"
                  class="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 transition hover:bg-slate-100"
                  @click="addProviderModel(provider.uid)"
                >
                  <Plus class="h-4 w-4" />
                  新增模型
                </button>
              </div>

              <div v-if="!provider.models.length" class="mt-4 rounded-2xl border border-dashed border-slate-300 bg-white px-4 py-4 text-sm text-slate-500">
                该 Provider 还没有模型。
              </div>

              <div v-else class="mt-4 space-y-4">
                <div
                  v-for="model in provider.models"
                  :key="model.uid"
                  class="rounded-2xl border border-slate-200 bg-white p-4"
                >
                  <div class="flex items-center justify-between gap-3">
                    <div>
                      <div class="text-xs uppercase tracking-[0.18em] text-slate-400">Model</div>
                      <div class="mt-1 text-sm font-medium text-slate-900">
                        {{ provider.name && model.id ? `${provider.name}/${model.id}` : '未完成的模型配置' }}
                      </div>
                    </div>
                    <button
                      type="button"
                      class="inline-flex items-center gap-2 rounded-2xl border border-rose-200 bg-white px-3 py-2 text-sm text-rose-600 transition hover:bg-rose-50"
                      @click="removeProviderModel(provider.uid, model.uid)"
                    >
                      <Trash2 class="h-4 w-4" />
                      删除
                    </button>
                  </div>

                  <div class="mt-4 grid gap-4 md:grid-cols-2">
                    <label class="space-y-2">
                      <div class="text-sm font-medium text-slate-700">模型 ID</div>
                      <input v-model="model.id" type="text" placeholder="例如 gpt-5.4" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none transition focus:border-cyan-400 focus:bg-white">
                    </label>
                    <label class="space-y-2">
                      <div class="text-sm font-medium text-slate-700">展示名称</div>
                      <input v-model="model.name" type="text" placeholder="可留空，默认回退到模型 ID" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none transition focus:border-cyan-400 focus:bg-white">
                    </label>
                    <label class="space-y-2">
                      <div class="text-sm font-medium text-slate-700">Context Window</div>
                      <input v-model.number="model.contextWindow" type="number" min="1" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none transition focus:border-cyan-400 focus:bg-white">
                    </label>
                    <label class="space-y-2">
                      <div class="text-sm font-medium text-slate-700">Max Tokens</div>
                      <input v-model.number="model.maxTokens" type="number" min="1" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none transition focus:border-cyan-400 focus:bg-white">
                    </label>
                  </div>

                  <div class="mt-4 flex flex-wrap gap-3">
                    <label class="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                      <input v-model="model.reasoning" type="checkbox" class="h-4 w-4">
                      开启 reasoning
                    </label>
                    <label
                      v-for="inputType in inputTypeOptions"
                      :key="`${model.uid}-${inputType}`"
                      class="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700"
                    >
                      <input v-model="model.input" type="checkbox" :value="inputType" class="h-4 w-4">
                      {{ inputType }}
                    </label>
                  </div>

                  <div class="mt-4">
                    <div class="text-sm font-medium text-slate-700">输出能力</div>
                    <div class="mt-2 flex flex-wrap gap-3">
                      <label
                        v-for="outputType in outputTypeOptions"
                        :key="`${model.uid}-output-${outputType}`"
                        class="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700"
                      >
                        <input v-model="model.output" type="checkbox" :value="outputType" class="h-4 w-4">
                        {{ outputType }}
                      </label>
                    </div>
                  </div>

                  <div class="mt-5">
                    <div class="text-sm font-medium text-slate-700">Cost</div>
                    <div class="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                      <label class="space-y-2">
                        <div class="text-xs uppercase tracking-[0.16em] text-slate-400">Input</div>
                        <input v-model.number="model.cost.input" type="number" min="0" step="0.0001" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none transition focus:border-cyan-400 focus:bg-white">
                      </label>
                      <label class="space-y-2">
                        <div class="text-xs uppercase tracking-[0.16em] text-slate-400">Output</div>
                        <input v-model.number="model.cost.output" type="number" min="0" step="0.0001" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none transition focus:border-cyan-400 focus:bg-white">
                      </label>
                      <label class="space-y-2">
                        <div class="text-xs uppercase tracking-[0.16em] text-slate-400">Cache Read</div>
                        <input v-model.number="model.cost.cacheRead" type="number" min="0" step="0.0001" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none transition focus:border-cyan-400 focus:bg-white">
                      </label>
                      <label class="space-y-2">
                        <div class="text-xs uppercase tracking-[0.16em] text-slate-400">Cache Write</div>
                        <input v-model.number="model.cost.cacheWrite" type="number" min="0" step="0.0001" class="w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none transition focus:border-cyan-400 focus:bg-white">
                      </label>
                    </div>
                  </div>
                </div>
              </div>
            </article>
          </div>
        </div>

        <div class="space-y-6">
          <div class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
            <div class="text-sm font-semibold text-slate-900">CORS Allowlist</div>
            <div class="mt-1 text-sm text-slate-500">每行一个 Origin，生产环境不要使用宽泛通配。</div>
            <textarea v-model="corsInput" class="mt-4 min-h-[220px] w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-7 outline-none focus:border-cyan-400 focus:bg-white" placeholder="https://app.example.com&#10;http://127.0.0.1:8764" />
          </div>

          <div class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
            <div class="text-sm font-semibold text-slate-900">Memory Provider</div>
            <div class="mt-1 text-sm text-slate-500">这里只切换 provider，不在 Web 里直接改密钥。</div>
            <select v-model="snapshot.memory.provider" class="mt-4 w-full rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 outline-none focus:border-cyan-400 focus:bg-white">
              <option v-for="provider in snapshot.memory.providers" :key="provider" :value="provider">{{ provider }}</option>
            </select>
            <div class="mt-4 rounded-2xl bg-slate-950 p-4 text-xs leading-6 text-slate-200">
              {{ JSON.stringify(snapshot.memory.active_settings, null, 2) }}
            </div>
          </div>
        </div>
      </section>
    </template>
  </div>
</template>
