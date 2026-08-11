import { describe, expect, it } from 'vitest'

import type { ProviderFetchedModel } from '@/api/models'
import {
    DEFAULT_EFFORT_OPTIONS,
    buildFetchSummary,
    buildModelKey,
    buildModelOptions,
    buildModelsConfigPayload,
    coerceInteger,
    coerceNumber,
    createEmptyModel,
    createEmptyProvider,
    createUidGenerator,
    hydrateModelsConfig,
    mergeProviderFetchedModels,
    normalizeEffortOptions,
    normalizeInputTypes,
    normalizeOutputTypes,
    normalizeRoleSelections,
    normalizeSelectionStrategy,
    providerHeadersPayload,
    resolveRoleEffort,
    roleCompatibilityStatus,
    roleOrder,
    serializeProviderConfig,
    type ModelForm,
    type ProviderForm,
} from './modelConfig'

const fetchedModel = (overrides: Partial<ProviderFetchedModel>): ProviderFetchedModel => ({
    id: 'gpt-4o',
    name: 'gpt-4o',
    input: null,
    reasoning: null,
    reasoningEffort: null,
    reasoningEfforts: [],
    contextWindow: null,
    maxTokens: null,
    ...overrides,
})

describe('normalize helpers', () => {
    it('normalizes input types with dedupe and unknown filtering', () => {
        expect(normalizeInputTypes(['Text', ' image ', 'text', 'file', ''])).toEqual(['text', 'image'])
        expect(normalizeInputTypes('text')).toEqual([])
        expect(normalizeInputTypes(null)).toEqual([])
    })

    it('normalizes output types', () => {
        expect(normalizeOutputTypes(['VIDEO', 'text', 'text'])).toEqual(['video', 'text'])
        expect(normalizeOutputTypes(undefined)).toEqual([])
    })

    it('normalizes effort options without lowercasing', () => {
        expect(normalizeEffortOptions(['Low', ' high ', 'Low', ''])).toEqual(['Low', 'high'])
        expect(normalizeEffortOptions('low')).toEqual([])
    })

    it('normalizes selection strategy with fallback', () => {
        expect(normalizeSelectionStrategy('Round_Robin')).toBe('round_robin')
        expect(normalizeSelectionStrategy('bogus')).toBe('priority')
        expect(normalizeSelectionStrategy(undefined)).toBe('priority')
    })

    it('coerces numbers and integers with bounds', () => {
        expect(coerceNumber('2.5', 0)).toBe(2.5)
        expect(coerceNumber('nope', 7)).toBe(7)
        expect(coerceNumber(-3, 0, 0)).toBe(0)
        expect(coerceInteger('4.6', 1)).toBe(5)
        expect(coerceInteger(0, 65536, 1)).toBe(1)
    })
})

describe('uid generator and model key', () => {
    it('generates sequential unique ids per generator', () => {
        const nextUid = createUidGenerator()
        expect(nextUid('model')).toBe('model-0')
        expect(nextUid('model')).toBe('model-1')
        const other = createUidGenerator()
        expect(other('model')).toBe('model-0')
    })

    it('builds trimmed model keys', () => {
        expect(buildModelKey(' openai ', ' gpt-4o ')).toBe('openai/gpt-4o')
    })
})

describe('providerHeadersPayload', () => {
    const providerWithHeaders = (headers: Array<{ name: string; value: string }>): ProviderForm => ({
        ...createEmptyProvider(createUidGenerator()),
        name: 'proxy',
        headers: headers.map((header, index) => ({ uid: `h-${index}`, ...header })),
    })

    it('skips fully empty rows and trims values', () => {
        expect(providerHeadersPayload(providerWithHeaders([
            { name: '', value: '' },
            { name: ' X-Token ', value: ' abc ' },
        ]))).toEqual({ 'X-Token': 'abc' })
    })

    it('rejects value without name', () => {
        expect(() => providerHeadersPayload(providerWithHeaders([{ name: '', value: 'v' }])))
            .toThrow('存在空的 Header 名称')
    })

    it('rejects newlines', () => {
        expect(() => providerHeadersPayload(providerWithHeaders([{ name: 'X\nBad', value: 'v' }])))
            .toThrow('不能包含换行符')
    })

    it('rejects duplicate names case-insensitively', () => {
        expect(() => providerHeadersPayload(providerWithHeaders([
            { name: 'X-Token', value: 'a' },
            { name: 'x-token', value: 'b' },
        ]))).toThrow('Header 名称重复')
    })
})

describe('buildModelOptions and role compatibility', () => {
    const nextUid = createUidGenerator()
    const provider = createEmptyProvider(nextUid)
    provider.name = 'proxy'
    const textModel: ModelForm = { ...createEmptyModel(nextUid), id: 'gpt-4o', input: ['text'], output: ['text'] }
    const visionModel: ModelForm = { ...createEmptyModel(nextUid), id: 'gpt-4v', input: ['text', 'image'], output: [] }
    const noIdModel: ModelForm = { ...createEmptyModel(nextUid), id: '' }
    provider.models.push(textModel, visionModel, noIdModel)
    const form = {
        mode: 'merge',
        topLevelExtras: {},
        modelExtras: {},
        poolExtras: {},
        selectionExtras: {},
        providers: [provider],
        roles: {} as never,
    }
    const options = buildModelOptions(form)

    it('skips models without provider name or model id', () => {
        expect(options.map(option => option.modelId)).toEqual(['gpt-4o', 'gpt-4v'])
        expect(options[0]!.key).toBe('proxy/gpt-4o')
    })

    it('evaluates role compatibility', () => {
        expect(roleCompatibilityStatus('primary', options[0])).toBe('eligible')
        expect(roleCompatibilityStatus('vision', options[0])).toBe('ineligible')
        expect(roleCompatibilityStatus('vision', options[1])).toBe('eligible')
        // image_generation 要求 output 有 image；output 为空走 legacy 兼容
        expect(roleCompatibilityStatus('image_generation', options[1])).toBe('legacy')
        expect(roleCompatibilityStatus('primary', null)).toBe('ineligible')
    })

    it('normalizeRoleSelections drops incompatible pool entries and keeps binding in pool', () => {
        const roles = Object.fromEntries(roleOrder.map(role => [role, {
            bindingUid: '',
            bindingKey: role,
            poolKey: role,
            poolUids: [],
            poolMetaByUid: {},
            selectionStrategy: 'priority',
            selectionExtras: {},
        }])) as never
        const roleForm = { ...form, providers: [provider], roles } as Parameters<typeof normalizeRoleSelections>[0]
        roleForm.roles.vision.poolUids = [textModel.uid, visionModel.uid]
        roleForm.roles.vision.poolMetaByUid = { [textModel.uid]: {}, [visionModel.uid]: {} }
        roleForm.roles.vision.bindingUid = visionModel.uid
        roleForm.roles.primary.bindingUid = textModel.uid

        normalizeRoleSelections(roleForm, options)

        expect(roleForm.roles.vision.poolUids).toEqual([visionModel.uid])
        expect(Object.keys(roleForm.roles.vision.poolMetaByUid)).toEqual([visionModel.uid])
        // binding 不在 pool 时自动补回
        expect(roleForm.roles.primary.poolUids).toEqual([textModel.uid])
    })
})

describe('resolveRoleEffort', () => {
    it('falls back to default options when provider did not report any', () => {
        const resolved = resolveRoleEffort({
            uid: 'm-0', key: 'p/m', providerName: 'p', modelId: 'm', name: 'm',
            input: ['text'], output: ['text'], reasoning: true, reasoningEffort: '', reasoningEffortOptions: [],
        })
        expect(resolved.enabled).toBe(true)
        expect(resolved.options).toEqual(DEFAULT_EFFORT_OPTIONS)
        expect(resolved.value).toBe('')
    })

    it('uses pulled options and prepends unknown current value', () => {
        const resolved = resolveRoleEffort({
            uid: 'm-0', key: 'p/m', providerName: 'p', modelId: 'm', name: 'm',
            input: ['text'], output: ['text'], reasoning: true, reasoningEffort: 'auto', reasoningEffortOptions: ['low', 'high'],
        })
        expect(resolved.options).toEqual(['auto', 'low', 'high'])
        expect(resolved.value).toBe('auto')
    })

    it('disables effort selection when no model is bound', () => {
        expect(resolveRoleEffort(null).enabled).toBe(false)
    })
})

describe('mergeProviderFetchedModels', () => {
    it('adds new models and applies reported capabilities', () => {
        const nextUid = createUidGenerator()
        const provider = createEmptyProvider(nextUid)
        const stats = mergeProviderFetchedModels(provider, [
            fetchedModel({
                id: 'gpt-5',
                input: ['text', 'image'],
                reasoning: true,
                reasoningEffort: 'medium',
                reasoningEfforts: ['low', 'medium', 'high'],
                contextWindow: 400000,
                maxTokens: 128000,
            }),
            fetchedModel({ id: 'dull-model' }),
        ], nextUid)

        expect(provider.models.map(model => model.id)).toEqual(['gpt-5', 'dull-model'])
        expect(stats).toEqual({
            total: 2,
            added: 2,
            inputApplied: 1,
            reasoningApplied: 1,
            effortApplied: 1,
            contextApplied: 2,
            manualKept: 1,
        })
        const pulled = provider.models[0]!
        expect(pulled.input).toEqual(['text', 'image'])
        expect(pulled.reasoning).toBe(true)
        expect(pulled.reasoningEffort).toBe('medium')
        expect(pulled.reasoningEffortOptions).toEqual(['low', 'medium', 'high'])
        expect(pulled.contextWindow).toBe(400000)
        expect(pulled.maxTokens).toBe(128000)
    })

    it('merges into existing models without duplicating and keeps manual config when nothing reported', () => {
        const nextUid = createUidGenerator()
        const provider = createEmptyProvider(nextUid)
        const existing = { ...createEmptyModel(nextUid), id: 'gpt-4o', name: '手动命名', input: ['text', 'voice'] as ModelForm['input'] }
        provider.models.push(existing)

        const stats = mergeProviderFetchedModels(provider, [
            fetchedModel({ id: 'gpt-4o' }),
            fetchedModel({ id: 'gpt-4o-mini', reasoning: false }),
        ], nextUid)

        expect(provider.models).toHaveLength(2)
        expect(stats.added).toBe(1)
        expect(stats.manualKept).toBe(1)
        expect(stats.reasoningApplied).toBe(1)
        // 未上报输入能力时保持手动配置
        expect(provider.models[0]!.name).toBe('手动命名')
        expect(provider.models[0]!.input).toEqual(['text', 'voice'])
    })

    it('summarizes merge stats for the toast message', () => {
        expect(buildFetchSummary({
            total: 3, added: 1, inputApplied: 2, reasoningApplied: 1, effortApplied: 0, contextApplied: 1, manualKept: 1,
        })).toBe('拉取 3 个模型：新增 1 个，应用 Provider 参数：输入能力 2、Reasoning 1、上下文/输出上限 1，1 个未返回可应用参数，保持手动配置')
        expect(buildFetchSummary({
            total: 1, added: 0, inputApplied: 0, reasoningApplied: 0, effortApplied: 0, contextApplied: 0, manualKept: 1,
        })).toBe('拉取 1 个模型：新增 0 个，1 个未返回可应用参数，保持手动配置')
    })
})

describe('hydrateModelsConfig / buildModelsConfigPayload roundtrip', () => {
    const payload = {
        mode: 'merge',
        model: { primary: 'proxy/gpt-4o', routing: 'proxy/gpt-4o-mini' },
        models: {
            primary: { 'proxy/gpt-4o': { note: 'keep' } },
            routing: ['proxy/gpt-4o-mini'],
        },
        selection: { primary: 'round_robin', routing: { strategy: 'least_usage', extra: 1 } },
        providers: {
            proxy: {
                baseUrl: 'https://example.com/v1',
                apiKey: 'sk-test',
                headers: { 'X-Team': 'ikaros' },
                api: 'openai-completions',
                customProviderField: 'preserved',
                models: [
                    {
                        id: 'gpt-4o',
                        name: 'GPT-4o',
                        reasoning: true,
                        reasoningEffort: 'high',
                        reasoningEfforts: ['low', 'high'],
                        input: ['text', 'image'],
                        output: ['text'],
                        cost: { input: 2.5, output: 10, customCost: 'x' },
                        limits: { dailyTokens: 1000 },
                        contextWindow: 128000,
                        maxTokens: 4096,
                        customModelField: 42,
                    },
                    { id: 'gpt-4o-mini', input: ['text'], output: ['text'] },
                ],
            },
        },
        unknownTopLevel: 'kept',
    }

    it('hydrates form state from models.json payload', () => {
        const form = hydrateModelsConfig(payload, createUidGenerator())

        expect(form.mode).toBe('merge')
        expect(form.topLevelExtras).toEqual({ unknownTopLevel: 'kept' })
        const provider = form.providers[0]!
        expect(provider.name).toBe('proxy')
        expect(provider.headers).toEqual([expect.objectContaining({ name: 'X-Team', value: 'ikaros' })])
        expect(provider.extras).toEqual({ customProviderField: 'preserved' })

        const main = provider.models[0]!
        const mini = provider.models[1]!
        expect(main.reasoningEffort).toBe('high')
        expect(main.reasoningEffortOptions).toEqual(['low', 'high'])
        expect(main.input).toEqual(['text', 'image'])
        expect(main.cost.extras).toEqual({ customCost: 'x' })
        expect(main.limits.dailyTokens).toBe(1000)
        expect(main.limits.dailyImages).toBe(0)
        expect(main.extras).toEqual({ customModelField: 42 })
        expect(mini.contextWindow).toBe(1000000)

        expect(form.roles.primary.bindingUid).toBe(main.uid)
        expect(form.roles.primary.poolUids).toEqual([main.uid])
        expect(form.roles.primary.poolMetaByUid[main.uid]).toEqual({ note: 'keep' })
        expect(form.roles.primary.selectionStrategy).toBe('round_robin')
        expect(form.roles.routing.bindingUid).toBe(mini.uid)
        expect(form.roles.routing.poolUids).toEqual([mini.uid])
        expect(form.roles.routing.selectionStrategy).toBe('least_usage')
        expect(form.roles.routing.selectionExtras).toEqual({ extra: 1 })
        // vision 模型未绑定但要求 image 输入，pool 为空不受影响
        expect(form.roles.vision.bindingUid).toBe('')
    })

    it('rebuilds a models.json payload from hydrated form', () => {
        const form = hydrateModelsConfig(payload, createUidGenerator())
        const result = buildModelsConfigPayload(form)

        expect(result.ok).toBe(true)
        if (!result.ok) {
            return
        }
        const rebuilt = result.modelsConfig as {
            unknownTopLevel: string
            mode: string
            model: Record<string, string>
            models: Record<string, Record<string, unknown>>
            selection: Record<string, { strategy: string }>
            providers: Record<string, Record<string, unknown>>
        }
        expect(rebuilt.unknownTopLevel).toBe('kept')
        expect(rebuilt.mode).toBe('merge')
        expect(rebuilt.model).toEqual({ primary: 'proxy/gpt-4o', routing: 'proxy/gpt-4o-mini' })
        expect(rebuilt.models).toEqual({
            primary: { 'proxy/gpt-4o': { note: 'keep' } },
            routing: { 'proxy/gpt-4o-mini': {} },
        })
        expect(rebuilt.selection).toEqual({
            primary: { strategy: 'round_robin' },
            routing: { strategy: 'least_usage' },
            vision: { strategy: 'priority' },
            image_generation: { strategy: 'priority' },
            voice: { strategy: 'priority' },
        })
        const providers = rebuilt.providers
        const proxy = providers.proxy!
        expect(proxy.baseUrl).toBe('https://example.com/v1')
        expect(proxy.headers).toEqual({ 'X-Team': 'ikaros' })
        expect(proxy.customProviderField).toBe('preserved')
        const models = proxy.models as Array<Record<string, unknown>>
        expect(models[0]).toMatchObject({
            id: 'gpt-4o',
            name: 'GPT-4o',
            reasoning: true,
            reasoningEffort: 'high',
            reasoningEfforts: ['low', 'high'],
            input: ['text', 'image'],
            contextWindow: 128000,
            customModelField: 42,
        })
        // 未设置思考程度的模型不输出 reasoningEffort 字段
        expect(models[1]).not.toHaveProperty('reasoningEffort')
    })

    it('reports validation errors instead of throwing', () => {
        const form = hydrateModelsConfig(payload, createUidGenerator())
        form.providers[0]!.name = ''
        expect(buildModelsConfigPayload(form)).toEqual({ ok: false, error: 'Provider 名称不能为空' })

        const dupForm = hydrateModelsConfig(payload, createUidGenerator())
        const clone = { ...dupForm.providers[0]!, models: [] }
        dupForm.providers.push(clone)
        expect(buildModelsConfigPayload(dupForm)).toEqual({ ok: false, error: 'Provider 名称重复：proxy' })

        const emptyIdForm = hydrateModelsConfig(payload, createUidGenerator())
        emptyIdForm.providers[0]!.models[0]!.id = ' '
        expect(buildModelsConfigPayload(emptyIdForm)).toEqual({ ok: false, error: 'proxy 下存在空的模型 ID' })

        const dupIdForm = hydrateModelsConfig(payload, createUidGenerator())
        dupIdForm.providers[0]!.models[1]!.id = 'gpt-4o'
        expect(buildModelsConfigPayload(dupIdForm)).toEqual({ ok: false, error: 'proxy 下模型 ID 重复：gpt-4o' })

        const orphanForm = hydrateModelsConfig(payload, createUidGenerator())
        orphanForm.roles.primary.bindingUid = 'ghost-uid'
        expect(buildModelsConfigPayload(orphanForm)).toEqual({ ok: false, error: 'Primary 绑定了一个未完整配置的模型' })

        const badHeaderForm = hydrateModelsConfig(payload, createUidGenerator())
        badHeaderForm.providers[0]!.headers.push({ uid: 'h-x', name: '', value: 'v' })
        expect(buildModelsConfigPayload(badHeaderForm)).toEqual({ ok: false, error: 'proxy 存在空的 Header 名称' })
    })
})

describe('serializeProviderConfig', () => {
    it('serializes a single provider as pretty JSON', () => {
        const nextUid = createUidGenerator()
        const provider = createEmptyProvider(nextUid)
        provider.name = 'proxy'
        provider.baseUrl = 'https://example.com/v1'
        provider.apiKey = 'sk-test'
        const model = createEmptyModel(nextUid)
        model.id = 'gpt-4o'
        model.reasoningEffort = 'low'
        provider.models.push(model)

        const parsed = JSON.parse(serializeProviderConfig(provider))
        expect(Object.keys(parsed)).toEqual(['proxy'])
        expect(parsed.proxy.api).toBe('openai-completions')
        expect(parsed.proxy.models[0]).toMatchObject({
            id: 'gpt-4o',
            reasoningEffort: 'low',
            contextWindow: 1000000,
            maxTokens: 65536,
        })
        expect(parsed.proxy.models[0]).not.toHaveProperty('reasoningEfforts')
    })
})
