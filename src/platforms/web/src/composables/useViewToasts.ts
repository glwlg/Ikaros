import { ref } from 'vue'

export type ViewToastKind = 'success' | 'error' | 'warning'

export interface ViewToast {
    id: number
    kind: ViewToastKind
    text: string
}

/** 页面级右上角浮动提示；错误停留更久，最多保留 4 条。 */
export const useViewToasts = () => {
    const toasts = ref<ViewToast[]>([])
    let seq = 0

    const dismiss = (id: number) => {
        toasts.value = toasts.value.filter(item => item.id !== id)
    }

    const push = (kind: ViewToastKind, text: string) => {
        const message = String(text || '').trim()
        if (!message) {
            return
        }
        const id = ++seq
        toasts.value = [...toasts.value.slice(-3), { id, kind, text: message }]
        window.setTimeout(() => dismiss(id), kind === 'error' ? 6000 : 4000)
    }

    return { toasts, push, dismiss }
}
