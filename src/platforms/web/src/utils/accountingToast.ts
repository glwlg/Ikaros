/**
 * Lightweight toast queue for the accounting module.
 * AccountingLayout hosts AccountingToastHost to render items.
 */

export type AccountingToastType = 'success' | 'error' | 'info'

export interface AccountingToastItem {
    id: number
    message: string
    type: AccountingToastType
    duration: number
}

type Listener = (items: AccountingToastItem[]) => void

let seq = 1
const items: AccountingToastItem[] = []
const listeners = new Set<Listener>()
const timers = new Map<number, ReturnType<typeof setTimeout>>()

const notify = () => {
    const snapshot = items.map(i => ({ ...i }))
    for (const listener of listeners) listener(snapshot)
}

export function subscribeAccountingToast(listener: Listener): () => void {
    listeners.add(listener)
    listener(items.map(i => ({ ...i })))
    return () => {
        listeners.delete(listener)
    }
}

export function dismissAccountingToast(id: number) {
    const idx = items.findIndex(i => i.id === id)
    if (idx < 0) return
    items.splice(idx, 1)
    const timer = timers.get(id)
    if (timer) {
        clearTimeout(timer)
        timers.delete(id)
    }
    notify()
}

export function accountingToast(
    message: string,
    options?: { type?: AccountingToastType; duration?: number },
): number {
    const type = options?.type || 'info'
    const duration = options?.duration ?? (type === 'error' ? 4200 : 2600)
    const id = seq++
    items.push({ id, message, type, duration })
    // Cap stack so long sessions don't pile up
    while (items.length > 4) {
        const old = items.shift()
        if (old) {
            const t = timers.get(old.id)
            if (t) {
                clearTimeout(t)
                timers.delete(old.id)
            }
        }
    }
    notify()
    if (duration > 0) {
        timers.set(
            id,
            setTimeout(() => dismissAccountingToast(id), duration),
        )
    }
    return id
}

export function accountingToastSuccess(message: string, duration?: number) {
    return accountingToast(message, { type: 'success', duration })
}

export function accountingToastError(message: string, duration?: number) {
    return accountingToast(message, { type: 'error', duration })
}

export function accountingToastInfo(message: string, duration?: number) {
    return accountingToast(message, { type: 'info', duration })
}

/** Extract a user-facing message from axios / fetch style errors. */
export function accountingErrorMessage(
    error: unknown,
    fallback = '加载失败，请稍后重试',
): string {
    if (error == null) return fallback
    if (typeof error === 'string' && error.trim()) return error.trim()

    const anyErr = error as {
        response?: { data?: { detail?: unknown; message?: unknown } }
        message?: string
    }
    const detail = anyErr?.response?.data?.detail
    if (typeof detail === 'string' && detail.trim()) return detail.trim()
    if (Array.isArray(detail)) {
        const parts = detail
            .map((item: unknown) => {
                if (typeof item === 'string') return item
                if (item && typeof item === 'object' && 'msg' in item) {
                    return String((item as { msg: unknown }).msg)
                }
                return ''
            })
            .filter(Boolean)
        if (parts.length) return parts.join('；')
    }
    const msg = anyErr?.response?.data?.message
    if (typeof msg === 'string' && msg.trim()) return msg.trim()
    if (typeof anyErr?.message === 'string' && anyErr.message && anyErr.message !== 'Network Error') {
        // Avoid raw Axios "Request failed with status code 500"
        if (!/^Request failed with status code/i.test(anyErr.message)) {
            return anyErr.message
        }
    }
    if (typeof anyErr?.message === 'string' && /Network Error/i.test(anyErr.message)) {
        return '网络异常，请检查连接后重试'
    }
    return fallback
}
