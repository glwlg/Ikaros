export interface NamedItem {
    id: string
    name: string
    created_at: string
}

export interface OperationLogEntry {
    id: string
    created_at: string
    action: string
    detail: string
}

export interface GlobalSettingsState {
    currency_symbol: string
    decimal_places: number
    week_start: '周一' | '周日'
    quick_create_enabled: boolean
}

export interface ExtensionSettingsState {
    smart_category_enabled: boolean
    recurring_reminder_enabled: boolean
    debt_reminder_enabled: boolean
    quick_import_enabled: boolean
}

export type StatsRangePreset =
    | 'all_time'
    | 'this_year'
    | 'this_quarter'
    | 'this_month'
    | 'this_week'
    | 'last_12_months'
    | 'last_30_days'
    | 'last_6_weeks'
    | 'year_range'
    | 'quarter_range'
    | 'month_range'
    | 'week_range'
    | 'day_range'

export type StatsPanelMetric = 'sum' | 'avg' | 'max' | 'min' | 'count'

export type StatsPanelSubject =
    | 'dynamic'
    | 'year'
    | 'quarter'
    | 'month'
    | 'week'
    | 'day'
    | 'amount'
    | 'category'
    | 'account'
    | 'project'

export type StatsPanelFilter =
    | 'type'
    | 'date_range'
    | 'category'
    | 'account'
    | 'project'

export type StatsPanelKind = 'category' | 'trend' | 'team' | 'generic'

export interface StatsPanelConfig {
    id: string
    name: string
    description: string
    kind: StatsPanelKind
    enabled: boolean
    is_custom: boolean
    metric: StatsPanelMetric
    subject: StatsPanelSubject
    filters: StatsPanelFilter[]
    default_type: '支出' | '收入'
    default_range: StatsRangePreset
    default_category: string
    sort_order: number
}

const STORAGE_PREFIX = 'x-bot:accounting'

const nowIso = () => new Date().toISOString()

const randomId = () => {
    return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

const storageKey = (bookId: number | null, section: string) => {
    const scope = bookId ?? 'global'
    return `${STORAGE_PREFIX}:${scope}:${section}`
}

const readJson = <T>(key: string, fallback: T): T => {
    if (typeof window === 'undefined') return fallback
    const raw = localStorage.getItem(key)
    if (!raw) return fallback

    try {
        return JSON.parse(raw) as T
    } catch {
        return fallback
    }
}

const writeJson = (key: string, value: unknown) => {
    if (typeof window === 'undefined') return
    localStorage.setItem(key, JSON.stringify(value))
}

export const loadNamedItems = (bookId: number | null, section: string) => {
    const key = storageKey(bookId, section)
    return readJson<NamedItem[]>(key, [])
}

export const saveNamedItems = (bookId: number | null, section: string, items: NamedItem[]) => {
    const key = storageKey(bookId, section)
    writeJson(key, items)
}

export const addNamedItem = (bookId: number | null, section: string, name: string) => {
    const cleanName = name.trim()
    if (!cleanName) return loadNamedItems(bookId, section)

    const items = loadNamedItems(bookId, section)
    if (items.some(item => item.name === cleanName)) {
        return items
    }

    const next: NamedItem[] = [
        {
            id: randomId(),
            name: cleanName,
            created_at: nowIso(),
        },
        ...items,
    ]
    saveNamedItems(bookId, section, next)
    return next
}

export const removeNamedItem = (bookId: number | null, section: string, id: string) => {
    const items = loadNamedItems(bookId, section)
    const next = items.filter(item => item.id !== id)
    saveNamedItems(bookId, section, next)
    return next
}

export const appendOperationLog = (
    bookId: number | null,
    action: string,
    detail: string,
) => {
    const key = storageKey(bookId, 'operation-logs')
    const logs = readJson<OperationLogEntry[]>(key, [])
    const next: OperationLogEntry[] = [
        {
            id: randomId(),
            created_at: nowIso(),
            action,
            detail,
        },
        ...logs,
    ].slice(0, 300)

    writeJson(key, next)
}

export const loadOperationLogs = (bookId: number | null) => {
    const key = storageKey(bookId, 'operation-logs')
    return readJson<OperationLogEntry[]>(key, [])
}

export const clearOperationLogs = (bookId: number | null) => {
    const key = storageKey(bookId, 'operation-logs')
    writeJson(key, [])
}

export const loadGlobalSettings = (): GlobalSettingsState => {
    const key = storageKey(null, 'global-settings')
    return readJson<GlobalSettingsState>(key, {
        currency_symbol: '¥',
        decimal_places: 2,
        week_start: '周一',
        quick_create_enabled: true,
    })
}

export const saveGlobalSettings = (state: GlobalSettingsState) => {
    const key = storageKey(null, 'global-settings')
    writeJson(key, state)
}

export const loadExtensionSettings = (): ExtensionSettingsState => {
    const key = storageKey(null, 'extension-settings')
    return readJson<ExtensionSettingsState>(key, {
        smart_category_enabled: true,
        recurring_reminder_enabled: true,
        debt_reminder_enabled: true,
        quick_import_enabled: true,
    })
}

export const saveExtensionSettings = (state: ExtensionSettingsState) => {
    const key = storageKey(null, 'extension-settings')
    writeJson(key, state)
}

const DEFAULT_STATS_PANELS: StatsPanelConfig[] = [
    {
        id: 'preset-category',
        name: '分类统计',
        description: '查看各个分类收支占比',
        kind: 'category',
        enabled: true,
        is_custom: false,
        metric: 'sum',
        subject: 'category',
        filters: ['type', 'date_range'],
        default_type: '支出',
        default_range: 'last_12_months',
        default_category: '全部分类',
        sort_order: 10,
    },
    {
        id: 'preset-food-spend',
        name: '吃了多少钱',
        description: '查看某个分类每月收支多少，如看每月话费支出多少',
        kind: 'generic',
        enabled: false,
        is_custom: false,
        metric: 'sum',
        subject: 'month',
        filters: ['type', 'date_range', 'category'],
        default_type: '支出',
        default_range: 'last_12_months',
        default_category: '餐饮',
        sort_order: 20,
    },
    {
        id: 'preset-daily-trend',
        name: '日趋势',
        description: '查看每天收支变化趋势',
        kind: 'trend',
        enabled: false,
        is_custom: false,
        metric: 'sum',
        subject: 'day',
        filters: ['type', 'date_range'],
        default_type: '支出',
        default_range: 'last_30_days',
        default_category: '全部分类',
        sort_order: 30,
    },
    {
        id: 'preset-weekend',
        name: '周末统计',
        description: '查看每个周末收支多少',
        kind: 'generic',
        enabled: false,
        is_custom: false,
        metric: 'sum',
        subject: 'week',
        filters: ['type', 'date_range'],
        default_type: '支出',
        default_range: 'last_6_weeks',
        default_category: '全部分类',
        sort_order: 40,
    },
    {
        id: 'preset-amount-distribution',
        name: '金额分布',
        description: '查看交易金额范围分布',
        kind: 'generic',
        enabled: false,
        is_custom: false,
        metric: 'count',
        subject: 'amount',
        filters: ['type', 'date_range'],
        default_type: '支出',
        default_range: 'last_30_days',
        default_category: '全部分类',
        sort_order: 50,
    },
    {
        id: 'preset-month-summary',
        name: '月度收支',
        description: '查看每月收支多少',
        kind: 'trend',
        enabled: false,
        is_custom: false,
        metric: 'sum',
        subject: 'month',
        filters: ['type', 'date_range'],
        default_type: '支出',
        default_range: 'this_year',
        default_category: '全部分类',
        sort_order: 60,
    },
    {
        id: 'preset-yearly',
        name: '年度统计',
        description: '查看每年收支多少',
        kind: 'trend',
        enabled: true,
        is_custom: false,
        metric: 'sum',
        subject: 'year',
        filters: ['type', 'date_range', 'category'],
        default_type: '支出',
        default_range: 'all_time',
        default_category: '全部分类',
        sort_order: 70,
    },
    {
        id: 'preset-weekly',
        name: '一周统计',
        description: '查看一周中的每天收支多少',
        kind: 'generic',
        enabled: false,
        is_custom: false,
        metric: 'sum',
        subject: 'day',
        filters: ['type', 'date_range', 'category'],
        default_type: '支出',
        default_range: 'this_week',
        default_category: '全部分类',
        sort_order: 80,
    },
    {
        id: 'preset-account',
        name: '账户统计',
        description: '查看各个账户收支占比',
        kind: 'generic',
        enabled: false,
        is_custom: false,
        metric: 'sum',
        subject: 'account',
        filters: ['type', 'date_range', 'account'],
        default_type: '支出',
        default_range: 'last_12_months',
        default_category: '全部分类',
        sort_order: 90,
    },
    {
        id: 'preset-max-single',
        name: '单笔最高',
        description: '查看最大单笔交易',
        kind: 'generic',
        enabled: false,
        is_custom: false,
        metric: 'max',
        subject: 'day',
        filters: ['type', 'date_range', 'category'],
        default_type: '支出',
        default_range: 'last_30_days',
        default_category: '全部分类',
        sort_order: 100,
    },
]

const cloneStatsPanel = (panel: StatsPanelConfig): StatsPanelConfig => ({
    ...panel,
    filters: [...panel.filters],
})

const normalizeStatsPanel = (
    panel: Partial<StatsPanelConfig>,
    index: number,
): StatsPanelConfig => {
    return {
        id: panel.id || randomId(),
        name: panel.name?.trim() || '自定义统计',
        description: panel.description?.trim() || '',
        kind: panel.kind || 'generic',
        enabled: panel.enabled ?? true,
        is_custom: panel.is_custom ?? true,
        metric: panel.metric || 'sum',
        subject: panel.subject || 'dynamic',
        filters: panel.filters ? [...panel.filters] : ['type', 'date_range'],
        default_type: panel.default_type || '支出',
        default_range: panel.default_range || 'last_12_months',
        default_category: panel.default_category || '全部分类',
        sort_order: panel.sort_order ?? (200 + index),
    }
}

const mergeStatsPanels = (stored: StatsPanelConfig[]) => {
    const byId = new Map<string, StatsPanelConfig>()

    for (const panel of stored) {
        byId.set(panel.id, normalizeStatsPanel(panel, byId.size))
    }

    for (const preset of DEFAULT_STATS_PANELS) {
        if (!byId.has(preset.id)) {
            byId.set(preset.id, cloneStatsPanel(preset))
        }
    }

    return [...byId.values()].sort((a, b) => a.sort_order - b.sort_order)
}

export const listStatsPanelTemplates = () => {
    return DEFAULT_STATS_PANELS.map(cloneStatsPanel)
}

export const loadStatsPanels = (bookId: number | null) => {
    const key = storageKey(bookId, 'stats-panels')
    const stored = readJson<StatsPanelConfig[]>(key, [])
    if (stored.length === 0) {
        const defaults = DEFAULT_STATS_PANELS.map(cloneStatsPanel)
        writeJson(key, defaults)
        return defaults
    }

    const merged = mergeStatsPanels(stored)
    writeJson(key, merged)
    return merged
}

export const saveStatsPanels = (bookId: number | null, panels: StatsPanelConfig[]) => {
    const key = storageKey(bookId, 'stats-panels')
    const next = panels.map((panel, index) => normalizeStatsPanel(panel, index))
    writeJson(key, next)
}

export const getStatsPanel = (bookId: number | null, id: string) => {
    return loadStatsPanels(bookId).find(panel => panel.id === id)
}

export const setStatsPanelEnabled = (
    bookId: number | null,
    id: string,
    enabled: boolean,
) => {
    const next = loadStatsPanels(bookId).map(panel => {
        if (panel.id !== id) return panel
        return { ...panel, enabled }
    })
    saveStatsPanels(bookId, next)
    return next
}

export const upsertStatsPanel = (
    bookId: number | null,
    panel: StatsPanelConfig,
) => {
    const current = loadStatsPanels(bookId)
    const idx = current.findIndex(item => item.id === panel.id)
    let next: StatsPanelConfig[]

    if (idx === -1) {
        next = [...current, normalizeStatsPanel({ ...panel, is_custom: true }, current.length)]
    } else {
        next = current.map((item, index) => {
            if (index !== idx) return item
            return normalizeStatsPanel(panel, index)
        })
    }

    saveStatsPanels(bookId, next)
    return next
}

export const removeStatsPanel = (bookId: number | null, id: string) => {
    const current = loadStatsPanels(bookId)
    const target = current.find(panel => panel.id === id)
    if (!target || !target.is_custom) return current

    const next = current.filter(panel => panel.id !== id)
    saveStatsPanels(bookId, next)
    return next
}

export const createStatsPanelDraft = (): StatsPanelConfig => {
    return {
        id: randomId(),
        name: '自定义统计',
        description: '描述一下统计的功能',
        kind: 'generic',
        enabled: true,
        is_custom: true,
        metric: 'sum',
        subject: 'dynamic',
        filters: ['type', 'date_range'],
        default_type: '支出',
        default_range: 'last_12_months',
        default_category: '全部分类',
        sort_order: Date.now(),
    }
}
