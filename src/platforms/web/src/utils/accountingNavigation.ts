/**
 * Pure helpers for building accounting record-list deep links and period bounds.
 */

export type PeriodGranularity = 'day' | 'week' | 'month' | 'quarter' | 'year'

export interface RecordListQueryInput {
    type?: string
    category?: string
    account?: string
    /** Inclusive display label (optional) */
    label?: string
    /** Window start (inclusive) */
    start?: Date | string | null
    /** Window end (exclusive preferred, ISO local) */
    end?: Date | string | null
    keyword?: string
}

export type RecordListQuery = Record<string, string>

const pad2 = (n: number) => String(n).padStart(2, '0')

export function toIsoLocalDateTime(d: Date): string {
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}T${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
}

export function toDateOnly(d: Date): string {
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

function asDate(value: Date | string | null | undefined): Date | null {
    if (value == null || value === '') return null
    if (value instanceof Date) {
        return Number.isNaN(value.getTime()) ? null : value
    }
    const raw = String(value).trim()
    if (!raw) return null
    // Date-only: local midnight
    const dayOnly = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/)
    if (dayOnly) {
        return new Date(Number(dayOnly[1]), Number(dayOnly[2]) - 1, Number(dayOnly[3]))
    }
    const d = new Date(raw)
    return Number.isNaN(d.getTime()) ? null : d
}

/**
 * Build vue-router query for RecordList. Omits empty fields.
 * Dates are serialized with toIsoLocalDateTime for half-open stats windows.
 */
export function buildRecordListQuery(input: RecordListQueryInput): RecordListQuery {
    const query: RecordListQuery = {}
    const type = (input.type || '').trim()
    if (type && type !== '全部' && type !== '结余') {
        query.type = type
    }
    const category = (input.category || '').trim()
    // Keep「未分类」as a real filter value (not an empty all-categories token)
    if (category && category !== '全部' && category !== '全部分类') {
        query.category = category
    }
    const account = (input.account || '').trim()
    if (account) {
        query.account = account
    }
    const keyword = (input.keyword || '').trim()
    if (keyword) {
        query.keyword = keyword
    }
    const label = (input.label || '').trim()
    if (label) {
        query.label = label
    }

    const start = asDate(input.start ?? null)
    const end = asDate(input.end ?? null)
    if (start) query.start = toIsoLocalDateTime(start)
    if (end) query.end = toIsoLocalDateTime(end)

    return query
}

/**
 * Resolve a period label from range-summary into [start, end) local bounds.
 * Supports: YYYY-MM-DD, YYYY-MM, YYYY, YYYY-Qn, YYYY-Www (best effort).
 */
export function periodBounds(
    period: string,
    granularity: PeriodGranularity = 'day',
): { start: Date; end: Date } | null {
    const p = (period || '').trim()
    if (!p) return null

    // day: 2026-03-14
    const day = p.match(/^(\d{4})-(\d{2})-(\d{2})$/)
    if (day || granularity === 'day') {
        if (day) {
            const start = new Date(Number(day[1]), Number(day[2]) - 1, Number(day[3]))
            const end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1)
            return { start, end }
        }
    }

    // month: 2026-03
    const month = p.match(/^(\d{4})-(\d{2})$/)
    if (month || granularity === 'month') {
        if (month) {
            const y = Number(month[1])
            const m = Number(month[2]) - 1
            const start = new Date(y, m, 1)
            const end = new Date(y, m + 1, 1)
            return { start, end }
        }
    }

    // quarter: 2026-Q1 or 2026Q1
    const quarter = p.match(/^(\d{4})-?Q([1-4])$/i)
    if (quarter || granularity === 'quarter') {
        if (quarter) {
            const y = Number(quarter[1])
            const q = Number(quarter[2])
            const start = new Date(y, (q - 1) * 3, 1)
            const end = new Date(y, q * 3, 1)
            return { start, end }
        }
    }

    // year: 2026
    const year = p.match(/^(\d{4})$/)
    if (year || granularity === 'year') {
        if (year) {
            const y = Number(year[1])
            return { start: new Date(y, 0, 1), end: new Date(y + 1, 0, 1) }
        }
    }

    // week: 2026-W12 — ISO-ish Monday start
    const week = p.match(/^(\d{4})-W(\d{2})$/i)
    if (week || granularity === 'week') {
        if (week) {
            const y = Number(week[1])
            const w = Number(week[2])
            const jan4 = new Date(y, 0, 4)
            const jan4Day = jan4.getDay() === 0 ? 7 : jan4.getDay()
            const week1Monday = new Date(y, 0, 4 - (jan4Day - 1))
            const start = new Date(
                week1Monday.getFullYear(),
                week1Monday.getMonth(),
                week1Monday.getDate() + (w - 1) * 7,
            )
            const end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 7)
            return { start, end }
        }
    }

    // fallback: try Date parse as single day
    const fallback = asDate(p)
    if (fallback) {
        const start = new Date(fallback.getFullYear(), fallback.getMonth(), fallback.getDate())
        const end = new Date(start.getFullYear(), start.getMonth(), start.getDate() + 1)
        return { start, end }
    }
    return null
}

/** Month calendar window [first day, first of next month) for budget drill-down. */
export function monthWindow(year: number, month: number): { start: Date; end: Date; label: string } {
    const start = new Date(year, month - 1, 1)
    const end = new Date(year, month, 1)
    return {
        start,
        end,
        label: `${year}年${month}月`,
    }
}
