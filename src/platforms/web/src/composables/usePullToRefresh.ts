import { computed, ref, type Ref } from 'vue'

export interface UsePullToRefreshOptions {
    threshold?: number
    onRefresh: () => Promise<void> | void
    /** Optional: element that owns vertical scroll; defaults to walking parents of pageRef */
    pageRef?: Ref<HTMLElement | null>
}

export function usePullToRefresh(options: UsePullToRefreshOptions) {
    const threshold = options.threshold ?? 72
    const refreshing = ref(false)
    const pullStartY = ref<number | null>(null)
    const pullDistance = ref(0)
    const isPulling = ref(false)

    const pullHint = computed(() => {
        if (refreshing.value) return '刷新中...'
        return pullDistance.value >= threshold ? '松开刷新' : '下拉刷新'
    })

    const getScrollParent = () => {
        let node: HTMLElement | null = options.pageRef?.value?.parentElement || null
        while (node) {
            const style = window.getComputedStyle(node)
            const scrollable = /(auto|scroll)/.test(style.overflowY)
            if (scrollable && node.scrollHeight > node.clientHeight) {
                return node
            }
            node = node.parentElement
        }
        return null
    }

    const resetPull = () => {
        pullDistance.value = 0
        pullStartY.value = null
        isPulling.value = false
    }

    const triggerRefresh = async () => {
        if (refreshing.value) return
        refreshing.value = true
        try {
            await options.onRefresh()
        } finally {
            refreshing.value = false
            resetPull()
        }
    }

    const handleTouchStart = (event: TouchEvent) => {
        if (refreshing.value) return
        const scrollParent = getScrollParent()
        if (scrollParent && scrollParent.scrollTop > 0) return
        if (options.pageRef?.value && options.pageRef.value.scrollTop > 0) return
        pullStartY.value = event.touches[0]?.clientY ?? null
        isPulling.value = true
    }

    const handleTouchMove = (event: TouchEvent) => {
        if (!isPulling.value || pullStartY.value === null) return
        const currentY = event.touches[0]?.clientY ?? pullStartY.value
        const delta = currentY - pullStartY.value
        if (delta <= 0) {
            pullDistance.value = 0
            return
        }
        pullDistance.value = Math.min(120, delta * 0.5)
        if (pullDistance.value > 0) {
            event.preventDefault()
        }
    }

    const handleTouchEnd = () => {
        if (!isPulling.value) return
        if (pullDistance.value >= threshold) {
            void triggerRefresh()
            return
        }
        resetPull()
    }

    return {
        refreshing,
        pullDistance,
        pullHint,
        handleTouchStart,
        handleTouchMove,
        handleTouchEnd,
        triggerRefresh,
        resetPull,
    }
}
