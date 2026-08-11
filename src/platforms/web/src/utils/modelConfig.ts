import type { ProviderFetchedModel } from '@/api/models'

export const roleOrder = ['primary', 'routing', 'vision', 'image_generation', 'voice'] as const
export const inputTypeOptions = ['text', 'image', 'voice'] as const
export const outputTypeOptions = ['text', 'image', 'voice', 'video'] as const
export const selectionStrategyOptions = ['priority', 'round_robin', 'least_usage'] as const

export type RoleKey = (typeof roleOrder)[number]
export type InputType = (typeof inputTypeOptions)[number]
export type OutputType = (typeof outputTypeOptions)[number]
export type SelectionStrategy = (typeof selectionStrategyOptions)[number]
export type NumericValue = number | ''

export interface CostForm {
    input: NumericValue
    output: NumericValue
    cacheRead: NumericValue
    cacheWrite: NumericValue
    extras: Record<string, unknown>
}

export interface LimitsForm {
    dailyTokens: NumericValue
    dailyImages: NumericValue
    extras: Record<string, unknown>
}

export interface ModelForm {
    uid: string
    id: string
    name: string
    reasoning: boolean
    reasoningEffort: string
    reasoningEffortOptions: string[]
    input: InputType[]
    output: OutputType[]
    cost: CostForm
    limits: LimitsForm
    contextWindow: NumericValue
    maxTokens: NumericValue
    extras: Record<string, unknown>
}

export interface HeaderForm {
    uid: string
    name: string
    value: string
}

export interface ProviderForm {
    uid: string
    name: string
    baseUrl: string
    apiKey: string
    headers: HeaderForm[]
    api: string
    models: ModelForm[]
    extras: Record<string, unknown>
}

export interface RoleConfigForm {
    bindingUid: string
    bindingKey: string
    poolKey: string
    poolUids: string[]
    poolMetaByUid: Record<string, Record<string, unknown>>
    selectionStrategy: SelectionStrategy
    selectionExtras: Record<string, unknown>
}

export interface ModelConfigForm {
    mode: string
    topLevelExtras: Record<string, unknown>
    modelExtras: Record<string, unknown>
    poolExtras: Record<string, unknown>
    selectionExtras: Record<string, unknown>
    providers: ProviderForm[]
    roles: Record<RoleKey, RoleConfigForm>
}

export interface ModelOption {
    uid: string
    key: string
    providerName: string
    modelId: string
    name: string
    input: InputType[]
    output: OutputType[]
    reasoning: boolean
    reasoningEffort: string
    reasoningEffortOptions: string[]
}

export const roleLabels: Record<RoleKey, string> = {
    primary: 'Primary',
    routing: 'Routing',
    vision: 'Vision',
    image_generation: 'Image Generation',
    voice: 'Voice',
}

export const primaryRoleStorageKey = (role: RoleKey) => role

export const roleRequiredInputs: Record<RoleKey, InputType[]> = {
    primary: ['text'],
    routing: ['text'],
    vision: ['image'],
    image_generation: [],
    voice: ['voice'],
}

export const roleRequiredOutputs: Record<RoleKey, OutputType[]> = {
    primary: [],
    routing: [],
    vision: [],
    image_generation: ['image'],
    voice: [],
}

export const roleCapabilityText: Record<RoleKey, string> = {
    primary: '至少支持 text 输入',
    routing: '至少支持 text 输入',
    vision: '至少支持 image 输入',
    image_generation: '至少支持 image 输出',
    voice: '至少支持 voice 输入',
}

export const selectionStrategyLabels: Record<SelectionStrategy, string> = {
    priority: '优先级顺序',
    round_robin: '轮询均衡',
    least_usage: '按今日最低用量',
}

export const DEFAULT_EFFORT_OPTIONS = ['low', 'medium', 'high', 'xhigh', 'max']

export type UidGenerator = (prefix: string) => string

export const createUidGenerator = (): UidGenerator => {
    let counter = 0
    return prefix => `${prefix}-${counter++}`
}

const asObject = (value: unknown): Record<string, unknown> | null => {
    if (!value || Array.isArray(value) || typeof value !== 'object') {
        return null
    }
    return { ...(value as Record<string, unknown>) }
}

const omitKeys = (source: Record<string, unknown>, keys: string[]) =>
    Object.fromEntries(Object.entries(source).filter(([key]) => !keys.includes(key)))

export const normalizeInputTypes = (value: unknown): InputType[] => {
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

export const normalizeOutputTypes = (value: unknown): OutputType[] => {
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

export const normalizeEffortOptions = (value: unknown): string[] => {
    if (!Array.isArray(value)) {
        return []
    }
    const normalized: string[] = []
    for (const item of value) {
        const token = String(item || '').trim()
        if (token && !normalized.includes(token)) {
            normalized.push(token)
        }
    }
    return normalized
}

export const normalizeSelectionStrategy = (value: unknown): SelectionStrategy => {
    const normalized = String(value || '').trim().toLowerCase() as SelectionStrategy
    if (selectionStrategyOptions.includes(normalized)) {
        return normalized
    }
    return 'priority'
}

export const coerceNumber = (value: unknown, fallback: number, minimum = 0) => {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) {
        return fallback
    }
    return Math.max(minimum, parsed)
}

export const coerceInteger = (value: unknown, fallback: number, minimum = 1) =>
    Math.max(minimum, Math.round(coerceNumber(value, fallback, minimum)))

export const buildModelKey = (providerName: string, modelId: string) =>
    `${providerName.trim()}/${modelId.trim()}`

export const createEmptyModel = (nextUid: UidGenerator): ModelForm => ({
    uid: nextUid('model'),
    id: '',
    name: '',
    reasoning: false,
    reasoningEffort: '',
    reasoningEffortOptions: [],
    input: ['text'],
    output: ['text'],
    cost: {
        input: 0,
        output: 0,
        cacheRead: 0,
        cacheWrite: 0,
        extras: {},
    },
    limits: {
        dailyTokens: 0,
        dailyImages: 0,
        extras: {},
    },
    contextWindow: 1000000,
    maxTokens: 65536,
    extras: {},
})

export const createEmptyProvider = (nextUid: UidGenerator): ProviderForm => ({
    uid: nextUid('provider'),
    name: '',
    baseUrl: '',
    apiKey: '',
    headers: [],
    api: 'openai-completions',
    models: [],
    extras: {},
})

export const providerHeadersPayload = (provider: ProviderForm) => {
    const headers: Record<string, string> = {}
    const seenNames = new Set<string>()
    for (const header of provider.headers) {
        const name = header.name.trim()
        const value = header.value
        if (!name && !value) {
            continue
        }
        if (!name) {
            throw new Error(`${provider.name || 'Provider'} 存在空的 Header 名称`)
        }
        if (name.includes('\n') || name.includes('\r') || value.includes('\n') || value.includes('\r')) {
            throw new Error(`${provider.name || 'Provider'} 的 Header 不能包含换行符`)
        }
        const normalizedName = name.toLowerCase()
        if (seenNames.has(normalizedName)) {
            throw new Error(`${provider.name || 'Provider'} 的 Header 名称重复：${name}`)
        }
        seenNames.add(normalizedName)
        headers[name] = value.trim()
    }
    return headers
}

export const buildModelOptions = (form: ModelConfigForm): ModelOption[] =>
    form.providers.flatMap(provider =>
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
                    reasoningEffort: model.reasoningEffort.trim(),
                    reasoningEffortOptions: [...model.reasoningEffortOptions],
                }
            })
            .filter((item): item is ModelOption => Boolean(item))
    )

export const roleCompatibilityStatus = (role: RoleKey, option: ModelOption | null | undefined) => {
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

export const normalizeRoleSelections = (form: ModelConfigForm, options: ModelOption[]) => {
    for (const role of roleOrder) {
        const roleConfig = form.roles[role]
        const compatibleUids = new Set(
            options
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

export const resolveRoleEffort = (option: ModelOption | null | undefined) => {
    const pulledOptions = option?.reasoningEffortOptions || []
    const options = pulledOptions.length ? [...pulledOptions] : [...DEFAULT_EFFORT_OPTIONS]
    const value = option?.reasoningEffort || ''
    if (value && !options.includes(value)) {
        options.unshift(value)
    }
    return {
        enabled: Boolean(option),
        value,
        options,
    }
}

export interface ProviderFetchMergeStats {
    total: number
    added: number
    inputApplied: number
    reasoningApplied: number
    effortApplied: number
    contextApplied: number
    manualKept: number
}

export const mergeProviderFetchedModels = (
    provider: ProviderForm,
    fetched: ProviderFetchedModel[],
    nextUid: UidGenerator
): ProviderFetchMergeStats => {
    const existingById = new Map(
        provider.models
            .map(model => [model.id.trim(), model] as const)
            .filter(([modelId]) => Boolean(modelId))
    )
    const stats: ProviderFetchMergeStats = {
        total: fetched.length,
        added: 0,
        inputApplied: 0,
        reasoningApplied: 0,
        effortApplied: 0,
        contextApplied: 0,
        manualKept: 0,
    }
    for (const item of fetched) {
        let target = existingById.get(item.id)
        if (!target) {
            target = createEmptyModel(nextUid)
            target.id = item.id
            target.name = item.name || item.id
            provider.models.push(target)
            existingById.set(item.id, target)
            stats.added += 1
        }
        let applied = false
        const fetchedInputs = normalizeInputTypes(item.input)
        if (fetchedInputs.length) {
            target.input = fetchedInputs
            stats.inputApplied += 1
            applied = true
        }
        if (typeof item.reasoning === 'boolean') {
            target.reasoning = item.reasoning
            stats.reasoningApplied += 1
            applied = true
        }
        if (item.reasoningEffort && item.reasoningEffort.trim()) {
            target.reasoningEffort = item.reasoningEffort.trim()
            stats.effortApplied += 1
            applied = true
        }
        if (item.reasoningEfforts.length) {
            target.reasoningEffortOptions = [...item.reasoningEfforts]
        }
        if (typeof item.contextWindow === 'number' && item.contextWindow > 0) {
            target.contextWindow = item.contextWindow
            stats.contextApplied += 1
            applied = true
        }
        if (typeof item.maxTokens === 'number' && item.maxTokens > 0) {
            target.maxTokens = item.maxTokens
            stats.contextApplied += 1
            applied = true
        }
        if (!applied) {
            stats.manualKept += 1
        }
    }
    return stats
}

export const buildFetchSummary = (stats: ProviderFetchMergeStats) => {
    const appliedBits: string[] = []
    if (stats.inputApplied) {
        appliedBits.push(`输入能力 ${stats.inputApplied}`)
    }
    if (stats.reasoningApplied) {
        appliedBits.push(`Reasoning ${stats.reasoningApplied}`)
    }
    if (stats.effortApplied) {
        appliedBits.push(`思考程度 ${stats.effortApplied}`)
    }
    if (stats.contextApplied) {
        appliedBits.push(`上下文/输出上限 ${stats.contextApplied}`)
    }
    const summary = [`拉取 ${stats.total} 个模型：新增 ${stats.added} 个`]
    if (appliedBits.length) {
        summary.push(`应用 Provider 参数：${appliedBits.join('、')}`)
    }
    if (stats.manualKept) {
        summary.push(`${stats.manualKept} 个未返回可应用参数，保持手动配置`)
    }
    return summary.join('，')
}

export const serializeProviderConfig = (provider: ProviderForm) => {
    const providerName = provider.name.trim() || 'provider'
    return JSON.stringify(
        {
            [providerName]: {
                ...provider.extras,
                baseUrl: provider.baseUrl.trim(),
                apiKey: provider.apiKey,
                headers: providerHeadersPayload(provider),
                api: provider.api.trim() || 'openai-completions',
                models: provider.models.map(model => ({
                    ...model.extras,
                    id: model.id.trim(),
                    name: model.name.trim() || model.id.trim(),
                    reasoning: Boolean(model.reasoning),
                    ...(model.reasoningEffort.trim() ? { reasoningEffort: model.reasoningEffort.trim() } : {}),
                    ...(model.reasoningEffortOptions.length ? { reasoningEfforts: [...model.reasoningEffortOptions] } : {}),
                    input: [...model.input],
                    output: [...model.output],
                    cost: {
                        ...model.cost.extras,
                        input: coerceNumber(model.cost.input, 0, 0),
                        output: coerceNumber(model.cost.output, 0, 0),
                        cacheRead: coerceNumber(model.cost.cacheRead, 0, 0),
                        cacheWrite: coerceNumber(model.cost.cacheWrite, 0, 0),
                    },
                    limits: {
                        ...model.limits.extras,
                        dailyTokens: coerceInteger(model.limits.dailyTokens, 0, 0),
                        dailyImages: coerceInteger(model.limits.dailyImages, 0, 0),
                    },
                    contextWindow: coerceInteger(model.contextWindow, 1000000, 1),
                    maxTokens: coerceInteger(model.maxTokens, 65536, 1),
                })),
            },
        },
        null,
        2
    )
}

export const hydrateModelsConfig = (payload: Record<string, unknown>, nextUid: UidGenerator): ModelConfigForm => {
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
            headers: Object.entries(asObject(rawProvider.headers) || {}).map(([name, value]) => ({
                uid: nextUid('header'),
                name,
                value: String(value ?? ''),
            })),
            api: String(rawProvider.api || '').trim() || 'openai-completions',
            models: [],
            extras: omitKeys(rawProvider, ['baseUrl', 'apiKey', 'headers', 'api', 'models']),
        }

        const rawModels = Array.isArray(rawProvider.models) ? rawProvider.models : []
        for (const item of rawModels) {
            const rawModel = asObject(item)
            if (!rawModel) {
                continue
            }
            const cost = asObject(rawModel.cost) || {}
            const limits = asObject(rawModel.limits) || {}
            const model: ModelForm = {
                uid: nextUid('model'),
                id: String(rawModel.id || '').trim(),
                name: String(rawModel.name || rawModel.id || '').trim(),
                reasoning: Boolean(rawModel.reasoning),
                reasoningEffort: String(rawModel.reasoningEffort || '').trim(),
                reasoningEffortOptions: normalizeEffortOptions(rawModel.reasoningEfforts),
                input: normalizeInputTypes(rawModel.input),
                output: normalizeOutputTypes(rawModel.output),
                cost: {
                    input: coerceNumber(cost.input, 0, 0),
                    output: coerceNumber(cost.output, 0, 0),
                    cacheRead: coerceNumber(cost.cacheRead, 0, 0),
                    cacheWrite: coerceNumber(cost.cacheWrite, 0, 0),
                    extras: omitKeys(cost, ['input', 'output', 'cacheRead', 'cacheWrite']),
                },
                limits: {
                    dailyTokens: coerceInteger(limits.dailyTokens, 0, 0),
                    dailyImages: coerceInteger(limits.dailyImages, 0, 0),
                    extras: omitKeys(limits, ['dailyTokens', 'dailyImages']),
                },
                contextWindow: coerceInteger(rawModel.contextWindow, 1000000, 1),
                maxTokens: coerceInteger(rawModel.maxTokens, 65536, 1),
                extras: omitKeys(rawModel, ['id', 'name', 'reasoning', 'reasoningEffort', 'reasoningEfforts', 'input', 'output', 'cost', 'limits', 'contextWindow', 'maxTokens']),
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
    const rawSelection = asObject(payload.selection) || {}
    const roles = {} as Record<RoleKey, RoleConfigForm>

    for (const role of roleOrder) {
        const bindingKey = primaryRoleStorageKey(role)
        const selectedModelKey = String(rawModelBindings[bindingKey] || '').trim()
        const poolKey = primaryRoleStorageKey(role)
        const rawPool = rawPools[poolKey]
        const rawSelectionValue = rawSelection[role]
        const selectionPayload =
            typeof rawSelectionValue === 'string'
                ? { strategy: rawSelectionValue }
                : asObject(rawSelectionValue) || {}
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
            selectionStrategy: normalizeSelectionStrategy(selectionPayload.strategy),
            selectionExtras: omitKeys(selectionPayload, ['strategy']),
        }
    }

    const form: ModelConfigForm = {
        mode: String(payload.mode || '').trim() || 'merge',
        topLevelExtras: omitKeys(payload, ['mode', 'model', 'models', 'providers', 'selection']),
        modelExtras: {},
        poolExtras: {},
        selectionExtras: {},
        providers,
        roles,
    }
    normalizeRoleSelections(form, buildModelOptions(form))
    return form
}

export type ModelsConfigSubmissionResult =
    | { ok: true; modelsConfig: Record<string, unknown> }
    | { ok: false; error: string }

export const buildModelsConfigPayload = (form: ModelConfigForm): ModelsConfigSubmissionResult => {
    const providersPayload: Record<string, unknown> = {}
    const modelKeyByUid: Record<string, string> = {}
    const seenProviderNames = new Set<string>()

    for (const provider of form.providers) {
        const providerName = provider.name.trim()
        if (!providerName) {
            return { ok: false, error: 'Provider 名称不能为空' }
        }
        if (seenProviderNames.has(providerName)) {
            return { ok: false, error: `Provider 名称重复：${providerName}` }
        }
        seenProviderNames.add(providerName)

        const seenModelIds = new Set<string>()
        const modelsPayload = []
        for (const model of provider.models) {
            const modelId = model.id.trim()
            if (!modelId) {
                return { ok: false, error: `${providerName} 下存在空的模型 ID` }
            }
            if (seenModelIds.has(modelId)) {
                return { ok: false, error: `${providerName} 下模型 ID 重复：${modelId}` }
            }
            seenModelIds.add(modelId)
            modelKeyByUid[model.uid] = buildModelKey(providerName, modelId)
            modelsPayload.push({
                ...model.extras,
                id: modelId,
                name: model.name.trim() || modelId,
                reasoning: Boolean(model.reasoning),
                ...(model.reasoningEffort.trim() ? { reasoningEffort: model.reasoningEffort.trim() } : {}),
                ...(model.reasoningEffortOptions.length ? { reasoningEfforts: [...model.reasoningEffortOptions] } : {}),
                input: [...model.input],
                output: [...model.output],
                cost: {
                    ...model.cost.extras,
                    input: coerceNumber(model.cost.input, 0, 0),
                    output: coerceNumber(model.cost.output, 0, 0),
                    cacheRead: coerceNumber(model.cost.cacheRead, 0, 0),
                    cacheWrite: coerceNumber(model.cost.cacheWrite, 0, 0),
                },
                limits: {
                    ...model.limits.extras,
                    dailyTokens: coerceInteger(model.limits.dailyTokens, 0, 0),
                    dailyImages: coerceInteger(model.limits.dailyImages, 0, 0),
                },
                contextWindow: coerceInteger(model.contextWindow, 1000000, 1),
                maxTokens: coerceInteger(model.maxTokens, 65536, 1),
            })
        }

        let headers: Record<string, string>
        try {
            headers = providerHeadersPayload(provider)
        } catch (error) {
            return { ok: false, error: error instanceof Error ? error.message : 'Header 配置无效' }
        }

        providersPayload[providerName] = {
            ...provider.extras,
            baseUrl: provider.baseUrl.trim(),
            apiKey: provider.apiKey,
            headers,
            api: provider.api.trim() || 'openai-completions',
            models: modelsPayload,
        }
    }

    const modelPayload: Record<string, unknown> = {}
    const poolsPayload: Record<string, unknown> = {}
    const selectionPayload: Record<string, unknown> = {}

    for (const role of roleOrder) {
        const roleConfig = form.roles[role]
        const bindingKey = primaryRoleStorageKey(role)
        const poolKey = primaryRoleStorageKey(role)
        const selectedModelKey = roleConfig.bindingUid ? modelKeyByUid[roleConfig.bindingUid] : ''

        if (roleConfig.bindingUid && !selectedModelKey) {
            return { ok: false, error: `${roleLabels[role]} 绑定了一个未完整配置的模型` }
        }
        if (selectedModelKey) {
            modelPayload[bindingKey] = selectedModelKey
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

        selectionPayload[role] = {
            strategy: normalizeSelectionStrategy(roleConfig.selectionStrategy),
        }
    }

    return {
        ok: true,
        modelsConfig: {
            ...form.topLevelExtras,
            mode: form.mode.trim() || 'merge',
            model: modelPayload,
            models: poolsPayload,
            selection: selectionPayload,
            providers: providersPayload,
        },
    }
}
