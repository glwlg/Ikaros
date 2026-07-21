<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAccountingStore } from '@/stores/accounting'
import {
    getAccounts,
    getCategories,
    getRecords,
    type AccountItem,
    type CategoryItem,
    type RecordItem,
} from '@/api/accounting'
import { Search, ChevronDown, Loader2 } from 'lucide-vue-next'
import AccountingPageHeader from '@/components/accounting/AccountingPageHeader.vue'
import AccountingLoadingState from '@/components/accounting/AccountingLoadingState.vue'
import AccountingEmptyState from '@/components/accounting/AccountingEmptyState.vue'
import AccountingErrorState from '@/components/accounting/AccountingErrorState.vue'
import RecordRow from '@/components/accounting/RecordRow.vue'
import {
    groupRecordsByDay,
    recordsPageHasMore,
} from '@/utils/accountingMoney'
import { buildRecordListQuery } from '@/utils/accountingNavigation'
import {
    accountingErrorMessage,
    accountingToastError,
} from '@/utils/accountingToast'

const PAGE_SIZE = 50

const router = useRouter()
const route = useRoute()
const store = useAccountingStore()
const loading = ref(false)
const loadingMore = ref(false)
const loadError = ref('')
const records = ref<RecordItem[]>([])
const hasMore = ref(false)

const keyword = ref('')
const searchInput = ref('')
const startDate = ref('')
const endDate = ref('')
const selectedType = ref('')
const selectedCategory = ref('')
const selectedAccount = ref('')
const filterLabel = ref('')
const filtersExpanded = ref(false)

const categories = ref<CategoryItem[]>([])
const accounts = ref<AccountItem[]>([])

const scrollEl = ref<HTMLElement | null>(null)
const loadMoreSentinel = ref<HTMLElement | null>(null)
let loadMoreObserver: IntersectionObserver | null = null

const dayGroups = computed(() => groupRecordsByDay(records.value))

const categoryOptions = computed(() => {
    const names = new Set<string>(['未分类'])
    for (const c of categories.value) {
        if (selectedType.value && c.type !== selectedType.value) continue
        if (c.name) names.add(c.name)
    }
    if (selectedCategory.value) names.add(selectedCategory.value)
    return Array.from(names).sort((a, b) => {
        if (a === '未分类') return -1
        if (b === '未分类') return 1
        return a.localeCompare(b, 'zh-CN')
    })
})

const queryString = (key: string) => {
    const raw = route.query[key]
    if (Array.isArray(raw)) return (raw[0] ?? '').toString()
    return (raw ?? '').toString()
}

const toDateInputValue = (raw: string) => {
    if (!raw) return ''
    const m = raw.match(/^(\d{4}-\d{2}-\d{2})/)
    return m?.[1] ?? ''
}

const toApiDate = (localDate: string, originalQuery: string) => {
    if (!localDate && !originalQuery) return undefined
    if (originalQuery && originalQuery.includes('T')) {
        const day = toDateInputValue(originalQuery)
        if (!localDate || day === localDate) return originalQuery
    }
    return localDate || undefined
}

const queryStartRaw = ref('')
const queryEndRaw = ref('')
let suppressRouteReload = false

const hydrateFromRoute = () => {
    selectedType.value = queryString('type')
    selectedCategory.value = queryString('category')
    selectedAccount.value = queryString('account')
    filterLabel.value = queryString('label')
    const kw = queryString('keyword')
    keyword.value = kw
    searchInput.value = kw
    queryStartRaw.value = queryString('start')
    queryEndRaw.value = queryString('end')
    startDate.value = toDateInputValue(queryStartRaw.value)
    endDate.value = toDateInputValue(queryEndRaw.value)
}

const hasActiveFilters = computed(() =>
    Boolean(
        selectedType.value
        || selectedCategory.value
        || selectedAccount.value
        || startDate.value
        || endDate.value
        || keyword.value,
    ),
)

const filterSummary = computed(() => {
    const parts: string[] = []
    if (selectedType.value) parts.push(selectedType.value)
    if (selectedCategory.value) parts.push(selectedCategory.value)
    if (selectedAccount.value) parts.push(selectedAccount.value)
    if (startDate.value || endDate.value) {
        parts.push(`${startDate.value || '…'}–${endDate.value || '…'}`)
    }
    if (keyword.value) parts.push(`“${keyword.value}”`)
    return parts.join(' · ')
})

const loadMeta = async () => {
    if (!store.currentBookId) return
    try {
        const [catRes, accRes] = await Promise.all([
            getCategories(store.currentBookId),
            getAccounts(store.currentBookId),
        ])
        categories.value = catRes.data
        accounts.value = accRes.data
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '筛选条件加载失败'))
    }
}

const loadData = async (mode: 'replace' | 'append' = 'replace') => {
    if (!store.currentBookId) return
    if (mode === 'append') {
        if (loadingMore.value || loading.value || !hasMore.value) return
        loadingMore.value = true
    } else {
        loading.value = true
        loadError.value = ''
    }

    try {
        const offset = mode === 'append' ? records.value.length : 0
        const res = await getRecords(
            store.currentBookId,
            PAGE_SIZE,
            keyword.value || undefined,
            toApiDate(startDate.value, queryStartRaw.value),
            toApiDate(endDate.value, queryEndRaw.value),
            selectedType.value || undefined,
            selectedCategory.value || undefined,
            selectedAccount.value || undefined,
            offset,
        )
        if (mode === 'append') {
            const seen = new Set(records.value.map(r => r.id))
            const fresh = res.data.filter(r => !seen.has(r.id))
            records.value = [...records.value, ...fresh]
        } else {
            records.value = res.data
        }
        hasMore.value = recordsPageHasMore(res.data.length, PAGE_SIZE)
    } catch (e) {
        const msg = accountingErrorMessage(e, '交易加载失败')
        if (mode === 'replace') {
            loadError.value = msg
            records.value = []
            hasMore.value = false
        } else {
            accountingToastError(msg)
        }
    } finally {
        loading.value = false
        loadingMore.value = false
    }
}

const syncQueryToRoute = () => {
    const q = buildRecordListQuery({
        type: selectedType.value,
        category: selectedCategory.value,
        account: selectedAccount.value,
        keyword: keyword.value,
        label: filterLabel.value,
        start: queryStartRaw.value || startDate.value || undefined,
        end: queryEndRaw.value || endDate.value || undefined,
    })
    if (startDate.value) {
        const origDay = toDateInputValue(queryStartRaw.value)
        if (!queryStartRaw.value || (origDay && origDay !== startDate.value)) {
            q.start = startDate.value
            queryStartRaw.value = startDate.value
        }
    } else {
        delete q.start
        queryStartRaw.value = ''
    }
    if (endDate.value) {
        const origDay = toDateInputValue(queryEndRaw.value)
        if (!queryEndRaw.value || (origDay && origDay !== endDate.value)) {
            q.end = endDate.value
            queryEndRaw.value = endDate.value
        }
    } else {
        delete q.end
        queryEndRaw.value = ''
    }
    suppressRouteReload = true
    router.replace({ name: 'RecordList', query: q })
}

const applyFilters = () => {
    filterLabel.value = ''
    if (startDate.value) queryStartRaw.value = startDate.value
    if (endDate.value) queryEndRaw.value = endDate.value
    syncQueryToRoute()
    void loadData('replace')
}

const applySearch = () => {
    keyword.value = searchInput.value.trim()
    applyFilters()
}

const clearFilters = () => {
    startDate.value = ''
    endDate.value = ''
    selectedType.value = ''
    selectedCategory.value = ''
    selectedAccount.value = ''
    keyword.value = ''
    searchInput.value = ''
    filterLabel.value = ''
    queryStartRaw.value = ''
    queryEndRaw.value = ''
    suppressRouteReload = true
    router.replace({ name: 'RecordList', query: {} })
    void loadData('replace')
}

const loadMore = async () => {
    await loadData('append')
}

const openRecordDetail = (id: number) => {
    router.push({ name: 'RecordDetail', params: { id } })
}

const teardownObserver = () => {
    loadMoreObserver?.disconnect()
    loadMoreObserver = null
}

const setupObserver = async () => {
    await nextTick()
    teardownObserver()
    const root = scrollEl.value
    const target = loadMoreSentinel.value
    if (!root || !target) return

    loadMoreObserver = new IntersectionObserver(
        entries => {
            if (entries.some(e => e.isIntersecting)) {
                void loadMore()
            }
        },
        { root, rootMargin: '160px', threshold: 0 },
    )
    loadMoreObserver.observe(target)
}

watch(
    () => route.fullPath,
    () => {
        if (route.name !== 'RecordList') return
        if (suppressRouteReload) {
            suppressRouteReload = false
            return
        }
        hydrateFromRoute()
        void loadData('replace')
    },
)

watch([hasMore, loading, () => records.value.length], () => {
    if (!loading.value && hasMore.value) {
        void setupObserver()
    } else {
        teardownObserver()
    }
})

onMounted(async () => {
    if (!store.currentBookId) await store.fetchBooks()
    hydrateFromRoute()
    filtersExpanded.value = false
    await loadMeta()
    if (store.currentBookId) await loadData('replace')
})

onBeforeUnmount(() => {
    teardownObserver()
})
</script>

<template>
  <div class="accounting-fullscreen bg-theme-primary">
    <AccountingPageHeader title="交易明细" />

    <div ref="scrollEl" class="flex-1 min-h-0 overflow-auto accounting-scroll accounting-subpage-pad">
      <!-- Sticky filter bar -->
      <div class="sticky top-0 z-10 bg-theme-primary/95 backdrop-blur-md border-b border-theme-secondary px-3 pt-3 pb-3">
        <div class="flex items-center gap-2">
          <div class="accounting-search flex-1 min-w-0">
            <Search class="accounting-search-icon" aria-hidden="true" />
            <input
              v-model="searchInput"
              type="text"
              inputmode="search"
              enterkeyhint="search"
              autocomplete="off"
              placeholder="搜索备注、付款对象"
              @keyup.enter="applySearch"
            >
          </div>
          <button
            type="button"
            class="h-11 shrink-0 px-3.5 rounded-xl border border-theme-secondary bg-theme-elevated text-sm font-medium text-theme-primary inline-flex items-center gap-1 active:opacity-80"
            @click="filtersExpanded = !filtersExpanded"
          >
            筛选
            <ChevronDown class="w-4 h-4 transition-transform" :class="filtersExpanded ? 'rotate-180' : ''" />
          </button>
        </div>

        <div v-if="hasActiveFilters && !filtersExpanded" class="mt-2.5 flex items-center gap-2">
          <p class="flex-1 text-xs text-theme-muted truncate leading-5">{{ filterSummary }}</p>
          <button type="button" class="text-xs text-accounting-brand font-medium shrink-0 px-1 py-1" @click="clearFilters">
            清除
          </button>
        </div>

        <div v-if="filtersExpanded" class="mt-3 accounting-filter-grid">
          <div>
            <label class="accounting-field-label">类型</label>
            <select v-model="selectedType" class="accounting-field" @change="applyFilters">
              <option value="">全部</option>
              <option value="支出">支出</option>
              <option value="收入">收入</option>
              <option value="转账">转账</option>
            </select>
          </div>
          <div>
            <label class="accounting-field-label">分类</label>
            <select v-model="selectedCategory" class="accounting-field" @change="applyFilters">
              <option value="">全部</option>
              <option v-for="name in categoryOptions" :key="name" :value="name">{{ name }}</option>
            </select>
          </div>
          <div class="span-2">
            <label class="accounting-field-label">账户</label>
            <select v-model="selectedAccount" class="accounting-field" @change="applyFilters">
              <option value="">全部账户</option>
              <option v-for="acc in accounts" :key="acc.id" :value="acc.name">{{ acc.name }}</option>
            </select>
          </div>
          <div>
            <label class="accounting-field-label">开始日期</label>
            <input v-model="startDate" type="date" class="accounting-field" @change="applyFilters">
          </div>
          <div>
            <label class="accounting-field-label">结束日期</label>
            <input v-model="endDate" type="date" class="accounting-field" @change="applyFilters">
          </div>
          <div class="span-2 flex gap-2 pt-1">
            <button
              type="button"
              class="flex-1 h-11 rounded-xl bg-accounting-brand text-white text-sm font-medium active:opacity-90"
              @click="applySearch"
            >
              应用
            </button>
            <button
              v-if="hasActiveFilters"
              type="button"
              class="h-11 px-5 rounded-xl border border-theme-secondary bg-theme-elevated text-sm text-theme-secondary"
              @click="clearFilters"
            >
              重置
            </button>
          </div>
        </div>
      </div>

      <div class="px-3 pt-3">
        <AccountingLoadingState v-if="loading" />

        <AccountingErrorState
          v-else-if="loadError"
          title="交易加载失败"
          :description="loadError"
          @retry="loadData('replace')"
        />

        <AccountingEmptyState
          v-else-if="records.length === 0"
          title="没有符合条件的交易"
          description="试试换个分类，或点「筛选 → 重置」看全部"
        >
          <template #action>
            <button
              v-if="hasActiveFilters"
              type="button"
              class="px-4 h-10 rounded-xl bg-accounting-brand text-white text-sm"
              @click="clearFilters"
            >
              清除筛选
            </button>
          </template>
        </AccountingEmptyState>

        <div v-else class="space-y-3 pb-6">
          <div
            v-for="group in dayGroups"
            :key="group.dateKey"
            class="rounded-2xl bg-theme-elevated shadow-sm border border-theme-secondary overflow-hidden"
          >
            <div class="px-4 py-2 bg-theme-secondary/60">
              <p class="text-xs font-semibold text-theme-muted">{{ group.label }}</p>
            </div>
            <ul class="divide-y divide-[var(--color-border-secondary)]">
              <li
                v-for="rec in group.records"
                :key="rec.id"
                class="active:bg-theme-secondary/50 transition"
                @click="openRecordDetail(rec.id)"
              >
                <RecordRow
                  :id="rec.id"
                  :type="rec.type"
                  :amount="rec.amount"
                  :category="rec.category"
                  :payee="rec.payee"
                  :remark="rec.remark"
                  :account="rec.account"
                  :target-account="rec.target_account"
                  :record-time="rec.record_time"
                  :show-date="false"
                />
              </li>
            </ul>
          </div>

          <div ref="loadMoreSentinel" class="flex justify-center pt-1 min-h-[2.5rem]">
            <div v-if="loadingMore" class="inline-flex items-center gap-2 text-xs text-theme-muted py-2">
              <Loader2 class="w-3.5 h-3.5 animate-spin text-accounting-brand" />
              加载更多…
            </div>
            <button
              v-else-if="hasMore"
              type="button"
              class="px-5 h-11 rounded-full border border-theme-primary text-sm font-medium text-accounting-brand active:bg-theme-secondary"
              @click="loadMore"
            >
              加载更多
            </button>
            <p v-else class="text-xs text-theme-muted py-2">共 {{ records.length }} 条</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
