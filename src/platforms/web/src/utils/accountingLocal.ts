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
