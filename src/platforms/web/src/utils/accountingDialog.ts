/**
 * Promise-based in-app confirm/alert for the accounting module.
 * AccountingLayout registers a host that fulfills these requests.
 */

export type AccountingDialogKind = 'alert' | 'confirm'

export interface AccountingDialogRequest {
    id: number
    kind: AccountingDialogKind
    title: string
    message: string
    confirmLabel: string
    cancelLabel: string
}

type Resolver = (value: boolean) => void

let seq = 1
const queue: Array<AccountingDialogRequest & { resolve: Resolver }> = []
let active: (AccountingDialogRequest & { resolve: Resolver }) | null = null
const listeners = new Set<(req: AccountingDialogRequest | null) => void>()

const notify = () => {
    const payload = active
        ? {
            id: active.id,
            kind: active.kind,
            title: active.title,
            message: active.message,
            confirmLabel: active.confirmLabel,
            cancelLabel: active.cancelLabel,
        }
        : null
    for (const listener of listeners) listener(payload)
}

const pump = () => {
    if (active) return
    const next = queue.shift()
    if (!next) {
        notify()
        return
    }
    active = next
    notify()
}

export function subscribeAccountingDialog(
    listener: (req: AccountingDialogRequest | null) => void,
): () => void {
    listeners.add(listener)
    listener(
        active
            ? {
                id: active.id,
                kind: active.kind,
                title: active.title,
                message: active.message,
                confirmLabel: active.confirmLabel,
                cancelLabel: active.cancelLabel,
            }
            : null,
    )
    return () => {
        listeners.delete(listener)
    }
}

export function resolveAccountingDialog(id: number, accepted: boolean) {
    if (!active || active.id !== id) return
    const current = active
    active = null
    current.resolve(accepted)
    pump()
}

export function accountingConfirm(
    message: string,
    options?: { title?: string; confirmLabel?: string; cancelLabel?: string },
): Promise<boolean> {
    return new Promise(resolve => {
        queue.push({
            id: seq++,
            kind: 'confirm',
            title: options?.title || '确认',
            message,
            confirmLabel: options?.confirmLabel || '确认',
            cancelLabel: options?.cancelLabel || '取消',
            resolve,
        })
        pump()
    })
}

export function accountingAlert(
    message: string,
    options?: { title?: string; confirmLabel?: string },
): Promise<void> {
    return new Promise(resolve => {
        queue.push({
            id: seq++,
            kind: 'alert',
            title: options?.title || '提示',
            message,
            confirmLabel: options?.confirmLabel || '知道了',
            cancelLabel: '',
            resolve: () => resolve(),
        })
        pump()
    })
}
