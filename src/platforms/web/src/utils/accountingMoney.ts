/**
 * Pure accounting money / list helpers used by views and node:test.
 */

export interface MoneyFormatSettings {
    currency_symbol: string
    decimal_places: number
}

export interface DebtRemainingRow {
    type: string
    remaining_amount: number
    is_settled?: boolean
}

export interface DebtRemainingSummary {
    borrow: number
    lend: number
    reimburse: number
}

export interface DayGroupableRecord {
    id: number
    record_time: string
}

export interface DayRecordGroup<T extends DayGroupableRecord = DayGroupableRecord> {
    dateKey: string
    label: string
    records: T[]
}

const DEFAULT_SETTINGS: MoneyFormatSettings = {
    currency_symbol: '¥',
    decimal_places: 2,
}

export function normalizeMoneySettings(
    partial?: Partial<MoneyFormatSettings> | null,
): MoneyFormatSettings {
    const symbol = partial?.currency_symbol?.trim() || DEFAULT_SETTINGS.currency_symbol
    let places = partial?.decimal_places
    if (typeof places !== 'number' || !Number.isFinite(places)) {
        places = DEFAULT_SETTINGS.decimal_places
    }
    places = Math.min(4, Math.max(0, Math.round(places)))
    return { currency_symbol: symbol, decimal_places: places }
}

/**
 * Format an amount with the given currency symbol and decimal places.
 * Pure: no localStorage access.
 */
export function formatMoneyAmount(
    amount: number,
    settings?: Partial<MoneyFormatSettings> | null,
    options?: { signed?: boolean; abs?: boolean },
): string {
    const { currency_symbol, decimal_places } = normalizeMoneySettings(settings)
    const raw = Number(amount)
    const value = Number.isFinite(raw) ? raw : 0
    const absValue = Math.abs(value)
    const formatted = new Intl.NumberFormat('zh-CN', {
        minimumFractionDigits: decimal_places,
        maximumFractionDigits: decimal_places,
    }).format(absValue)

    if (options?.abs) {
        return `${currency_symbol}${formatted}`
    }
    if (value < 0) {
        return `-${currency_symbol}${formatted}`
    }
    if (options?.signed && value > 0) {
        return `+${currency_symbol}${formatted}`
    }
    return `${currency_symbol}${formatted}`
}

/**
 * Compact display for tight UI (profile cards etc): 万 / 亿, keeps similar visual width.
 * Pure: no localStorage access.
 */
export function formatCompactMoneyAmount(
    amount: number,
    settings?: Partial<MoneyFormatSettings> | null,
): string {
    const { currency_symbol } = normalizeMoneySettings(settings)
    const raw = Number(amount)
    const value = Number.isFinite(raw) ? raw : 0
    const sign = value < 0 ? '-' : ''
    const abs = Math.abs(value)

    const fmt = (n: number, digits: number) =>
        n.toLocaleString('zh-CN', {
            minimumFractionDigits: 0,
            maximumFractionDigits: digits,
        })

    if (abs >= 100_000_000) {
        return `${sign}${currency_symbol}${fmt(abs / 100_000_000, 2)}亿`
    }
    if (abs >= 10_000) {
        return `${sign}${currency_symbol}${fmt(abs / 10_000, 2)}万`
    }
    return formatMoneyAmount(value, settings)
}

/**
 * Semantic text class for record type (expense / income / transfer).
 */
export function moneyTypeTextClass(type: string): string {
    if (type === '收入') return 'text-accounting-income'
    if (type === '转账') return 'text-accounting-transfer'
    return 'text-accounting-expense'
}

export function moneyTypeDotClass(type: string): string {
    if (type === '收入') return 'bg-accounting-income'
    if (type === '转账') return 'bg-accounting-transfer'
    return 'bg-accounting-expense'
}

/**
 * Aggregate unsettled remaining amounts by debt type for MoreView tiles.
 */
export function summarizeDebtRemaining(rows: DebtRemainingRow[]): DebtRemainingSummary {
    const summary: DebtRemainingSummary = {
        borrow: 0,
        lend: 0,
        reimburse: 0,
    }

    for (const row of rows) {
        if (row.is_settled) continue
        const amount = Number(row.remaining_amount)
        if (!Number.isFinite(amount) || amount <= 0) continue

        if (row.type === '借入') summary.borrow += amount
        else if (row.type === '借出') summary.lend += amount
        else if (row.type === '报销') summary.reimburse += amount
    }

    return summary
}

export function debtRemainingLabel(
    type: '借入' | '借出' | '报销',
    summary: DebtRemainingSummary,
    settings?: Partial<MoneyFormatSettings> | null,
): string {
    const amount =
        type === '借入' ? summary.borrow
            : type === '借出' ? summary.lend
                : summary.reimburse
    const suffix = type === '借入' ? '待还' : type === '借出' ? '待收' : '待报'
    return `${formatMoneyAmount(amount, settings)} ${suffix}`
}

/**
 * Extract local date key (YYYY-MM-DD) from ISO-ish record_time.
 */
export function recordDateKey(recordTime: string): string {
    if (!recordTime) return 'unknown'
    const match = recordTime.match(/^(\d{4}-\d{2}-\d{2})/)
    if (match?.[1]) return match[1]
    const d = new Date(recordTime)
    if (Number.isNaN(d.getTime())) return 'unknown'
    const y = d.getFullYear()
    const m = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
}

export function formatDayGroupLabel(dateKey: string, now: Date = new Date()): string {
    if (dateKey === 'unknown') return '未知日期'
    const todayKey = recordDateKey(
        `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`,
    )
    const yesterday = new Date(now)
    yesterday.setDate(yesterday.getDate() - 1)
    const yesterdayKey = recordDateKey(
        `${yesterday.getFullYear()}-${String(yesterday.getMonth() + 1).padStart(2, '0')}-${String(yesterday.getDate()).padStart(2, '0')}`,
    )
    if (dateKey === todayKey) return '今天'
    if (dateKey === yesterdayKey) return '昨天'
    const parts = dateKey.split('-')
    if (parts.length === 3) {
        return `${Number(parts[1])}月${Number(parts[2])}日`
    }
    return dateKey
}

/**
 * Group records by calendar day (newest day first; within day keep input order).
 */
export function groupRecordsByDay<T extends DayGroupableRecord>(
    records: T[],
    now: Date = new Date(),
): DayRecordGroup<T>[] {
    const map = new Map<string, T[]>()
    for (const rec of records) {
        const key = recordDateKey(rec.record_time)
        const list = map.get(key)
        if (list) list.push(rec)
        else map.set(key, [rec])
    }

    const keys = Array.from(map.keys()).sort((a, b) => b.localeCompare(a))
    return keys.map(dateKey => ({
        dateKey,
        label: formatDayGroupLabel(dateKey, now),
        records: map.get(dateKey) || [],
    }))
}

/**
 * Next API limit for "load more" pagination when the backend only accepts limit.
 */
export function nextRecordsLimit(
    currentCount: number,
    pageSize: number,
    hasMore: boolean,
): number | null {
    if (!hasMore) return null
    const size = Math.max(1, Math.round(pageSize))
    const base = Math.max(0, Math.round(currentCount))
    return base + size
}

export function recordsPageHasMore(fetchedCount: number, requestedLimit: number): boolean {
    return fetchedCount >= requestedLimit && requestedLimit > 0
}

/**
 * Budget progress 0–100, capped; overspending still reports 100 for ring fill.
 */
export function budgetProgressPercent(spent: number, total: number): number {
    if (!total || total <= 0) return 0
    return Math.min(100, Math.max(0, Math.round((spent / total) * 100)))
}

/**
 * SVG circle stroke-dashoffset for a progress ring (0–100).
 */
export function ringDashOffset(percent: number, circumference: number): number {
    const p = Math.min(100, Math.max(0, percent)) / 100
    return circumference * (1 - p)
}
