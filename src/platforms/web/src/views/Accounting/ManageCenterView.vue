<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useAccountingStore } from '@/stores/accounting'
import {
    createBook,
    createCategory,
    deleteBook,
    deleteCategory,
    getCategories,
    getRecords,
    updateBook,
    updateCategory,
    type CategoryItem,
} from '@/api/accounting'
import { Trash2, Pencil, Check } from 'lucide-vue-next'
import AccountingPageHeader from '@/components/accounting/AccountingPageHeader.vue'
import AccountingLoadingState from '@/components/accounting/AccountingLoadingState.vue'
import AccountingEmptyState from '@/components/accounting/AccountingEmptyState.vue'
import AccountingErrorState from '@/components/accounting/AccountingErrorState.vue'
import {
    addNamedItem,
    appendOperationLog,
    loadNamedItems,
    removeNamedItem,
    type NamedItem,
} from '@/utils/accountingLocal'
import { accountingConfirm } from '@/utils/accountingDialog'
import {
    accountingErrorMessage,
    accountingToastError,
    accountingToastInfo,
    accountingToastSuccess,
} from '@/utils/accountingToast'

type ManageKind = 'category' | 'project' | 'merchant' | 'tag' | 'book'
type CategoryType = '支出' | '收入' | '转账'

const route = useRoute()
const store = useAccountingStore()

const loading = ref(false)
const loadError = ref('')
const operating = ref(false)

const resolveKind = (value: unknown): ManageKind => {
    const raw = typeof value === 'string' ? value : ''
    if (raw === 'project' || raw === 'merchant' || raw === 'tag' || raw === 'book') {
        return raw
    }
    return 'category'
}

const kind = computed<ManageKind>(() => {
    const raw = Array.isArray(route.params.kind) ? route.params.kind[0] : route.params.kind
    return resolveKind(raw)
})

const pageTitleMap: Record<ManageKind, string> = {
    category: '分类管理',
    project: '项目管理',
    merchant: '商家管理',
    tag: '标签管理',
    book: '账本管理',
}

const pageTitle = computed(() => pageTitleMap[kind.value])

const categories = ref<CategoryItem[]>([])
const newCategoryName = ref('')
const newCategoryType = ref<CategoryType>('支出')
const editingCategoryId = ref<number | null>(null)
const editingCategoryName = ref('')
const editingCategoryType = ref<CategoryType>('支出')

const localItems = ref<NamedItem[]>([])
const newLocalName = ref('')
const recentMerchants = ref<string[]>([])

const newBookName = ref('')
const editingBookId = ref<number | null>(null)
const editingBookName = ref('')

const localSection = computed(() => {
    if (kind.value === 'project') return 'projects'
    if (kind.value === 'tag') return 'tags'
    return 'merchants-custom'
})

const localPlaceholder = computed(() => {
    if (kind.value === 'project') return '输入项目名称'
    if (kind.value === 'tag') return '输入标签名称'
    return '输入商家名称'
})

const localEmptyText = computed(() => {
    if (kind.value === 'project') return '暂无项目，先创建一个吧'
    if (kind.value === 'tag') return '暂无标签，先创建一个吧'
    return '暂无自定义商家，先创建一个吧'
})

const hasBookContext = computed(() => {
    if (kind.value === 'book') return true
    return Boolean(store.currentBookId)
})

const loadCategories = async () => {
    if (!store.currentBookId) return
    const res = await getCategories(store.currentBookId)
    categories.value = res.data
}

const loadLocalItems = () => {
    localItems.value = loadNamedItems(store.currentBookId, localSection.value)
}

const loadRecentMerchants = async () => {
    if (!store.currentBookId) return
    const res = await getRecords(store.currentBookId, 200)
    const merged = new Set<string>()
    for (const record of res.data) {
        const payee = record.payee.trim()
        if (payee) merged.add(payee)
    }
    recentMerchants.value = Array.from(merged)
}

const loadBooks = async () => {
    await store.fetchBooks()
}

const loadData = async () => {
    loading.value = true
    loadError.value = ''
    try {
        if (!store.currentBookId) {
            await store.fetchBooks()
        }

        if (kind.value === 'category') {
            await loadCategories()
            return
        }

        if (kind.value === 'book') {
            await loadBooks()
            return
        }

        loadLocalItems()
        if (kind.value === 'merchant') {
            await loadRecentMerchants()
        }
    } catch (e) {
        loadError.value = accountingErrorMessage(e, '数据加载失败')
        accountingToastError(loadError.value)
    } finally {
        loading.value = false
    }
}

const addCategory = async () => {
    if (!store.currentBookId) return
    const name = newCategoryName.value.trim()
    if (!name) {
        accountingToastError('请输入分类名称')
        return
    }

    operating.value = true
    try {
        await createCategory(store.currentBookId, {
            name,
            type: newCategoryType.value,
        })
        appendOperationLog(store.currentBookId, '新增分类', `${newCategoryType.value} / ${name}`)
        newCategoryName.value = ''
        accountingToastSuccess('分类已添加')
        await loadCategories()
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '添加分类失败'))
    } finally {
        operating.value = false
    }
}

const startEditCategory = (item: CategoryItem) => {
    editingCategoryId.value = item.id
    editingCategoryName.value = item.name
    editingCategoryType.value = item.type as CategoryType
}

const cancelEditCategory = () => {
    editingCategoryId.value = null
    editingCategoryName.value = ''
    editingCategoryType.value = '支出'
}

const saveEditCategory = async () => {
    if (!store.currentBookId || editingCategoryId.value === null) return
    const name = editingCategoryName.value.trim()
    if (!name) {
        accountingToastError('请输入分类名称')
        return
    }

    operating.value = true
    try {
        await updateCategory(store.currentBookId, editingCategoryId.value, {
            name,
            type: editingCategoryType.value,
        })
        appendOperationLog(store.currentBookId, '编辑分类', `${editingCategoryType.value} / ${name}`)
        cancelEditCategory()
        accountingToastSuccess('分类已更新')
        await loadCategories()
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '更新分类失败'))
    } finally {
        operating.value = false
    }
}

const removeCategory = async (item: CategoryItem) => {
    if (!store.currentBookId) return
    if (!await accountingConfirm(`确认删除分类「${item.name}」吗？`)) return

    operating.value = true
    try {
        await deleteCategory(store.currentBookId, item.id)
        appendOperationLog(store.currentBookId, '删除分类', `${item.type} / ${item.name}`)
        accountingToastSuccess('分类已删除')
        await loadCategories()
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '删除分类失败'))
    } finally {
        operating.value = false
    }
}

const addLocalEntry = () => {
    const name = newLocalName.value.trim()
    if (!name) {
        accountingToastError('请输入名称')
        return
    }

    const next = addNamedItem(store.currentBookId, localSection.value, name)
    localItems.value = next
    appendOperationLog(store.currentBookId, '新增条目', `${pageTitle.value} / ${name}`)
    newLocalName.value = ''
    accountingToastSuccess('已添加')
}

const removeLocalEntry = async (item: NamedItem) => {
    if (!await accountingConfirm(`确认删除「${item.name}」吗？`)) return
    const next = removeNamedItem(store.currentBookId, localSection.value, item.id)
    localItems.value = next
    appendOperationLog(store.currentBookId, '删除条目', `${pageTitle.value} / ${item.name}`)
    accountingToastSuccess('已删除')
}

const addBook = async () => {
    const name = newBookName.value.trim()
    if (!name) {
        accountingToastError('请输入账本名称')
        return
    }

    operating.value = true
    try {
        const res = await createBook(name)
        await store.fetchBooks()
        store.setCurrentBook(res.data.id)
        appendOperationLog(res.data.id, '新增账本', name)
        newBookName.value = ''
        accountingToastSuccess('账本已创建')
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '创建账本失败'))
    } finally {
        operating.value = false
    }
}

const startEditBook = (id: number, name: string) => {
    editingBookId.value = id
    editingBookName.value = name
}

const cancelEditBook = () => {
    editingBookId.value = null
    editingBookName.value = ''
}

const saveBook = async () => {
    if (editingBookId.value === null) return
    const name = editingBookName.value.trim()
    if (!name) {
        accountingToastError('请输入账本名称')
        return
    }

    operating.value = true
    try {
        await updateBook(editingBookId.value, { name })
        appendOperationLog(editingBookId.value, '重命名账本', name)
        cancelEditBook()
        accountingToastSuccess('账本已更新')
        await store.fetchBooks()
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '更新账本失败'))
    } finally {
        operating.value = false
    }
}

const removeBook = async (id: number, name: string) => {
    if (!await accountingConfirm(`确认删除账本「${name}」吗？该账本下数据会一并删除。`)) return

    operating.value = true
    try {
        await deleteBook(id)
        appendOperationLog(id, '删除账本', name)
        await store.fetchBooks()
        const exists = store.books.some(book => book.id === store.currentBookId)
        if (!exists) {
            const first = store.books[0]
            if (first) {
                store.setCurrentBook(first.id)
            } else {
                store.currentBookId = null
            }
        }
        accountingToastSuccess('账本已删除')
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '删除账本失败'))
    } finally {
        operating.value = false
    }
}

const selectBook = (id: number, name: string) => {
    store.setCurrentBook(id)
    appendOperationLog(id, '切换账本', name)
    accountingToastInfo('已切换账本')
}

watch(kind, () => {
    cancelEditCategory()
    cancelEditBook()
    loadData()
})

onMounted(() => {
    loadData()
})
</script>

<template>
  <div class="accounting-fullscreen bg-theme-primary">
    <AccountingPageHeader :title="pageTitle" />

    <main class="flex-1 min-h-0 overflow-y-auto accounting-scroll p-4 accounting-subpage-pad">
      <AccountingLoadingState v-if="loading" />

      <AccountingErrorState
        v-else-if="loadError"
        title="加载失败"
        :description="loadError"
        @retry="loadData"
      />

      <AccountingEmptyState
        v-else-if="!hasBookContext"
        title="还没有账本"
        description="请先在账本管理中创建账本"
      />

      <template v-else>
        <div v-if="kind === 'category'" class="space-y-4">
          <div class="bg-white dark:bg-slate-800 rounded-2xl p-4 border border-slate-100 dark:border-slate-700 shadow-sm space-y-3">
            <input
              v-model="newCategoryName"
              type="text"
              placeholder="输入分类名称"
              class="accounting-field"
            />
            <div class="flex gap-2">
              <select
                v-model="newCategoryType"
                class="accounting-field flex-1"
              >
                <option value="支出">支出</option>
                <option value="收入">收入</option>
                <option value="转账">转账</option>
              </select>
              <button
                @click="addCategory"
                :disabled="operating"
                class="px-4 py-2.5 rounded-xl bg-indigo-500 text-white font-medium disabled:opacity-50"
              >新增</button>
            </div>
          </div>

          <div class="bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm overflow-hidden">
            <AccountingEmptyState v-if="categories.length === 0" title="暂无分类" description="在上方输入名称后新增" />
            <div v-for="item in categories" :key="item.id" class="px-4 py-3 border-b border-slate-100 dark:border-slate-700 last:border-b-0">
              <div v-if="editingCategoryId !== item.id" class="flex items-center gap-3">
                <span class="flex-1 text-sm text-slate-800 dark:text-white">{{ item.name }} <span class="text-slate-400">({{ item.type }})</span></span>
                <button @click="startEditCategory(item)" class="p-1.5 text-slate-500 hover:text-slate-700">
                  <Pencil class="w-4 h-4" />
                </button>
                <button @click="removeCategory(item)" class="p-1.5 text-rose-500 hover:text-rose-600">
                  <Trash2 class="w-4 h-4" />
                </button>
              </div>

              <div v-else class="space-y-2">
                <input
                  v-model="editingCategoryName"
                  type="text"
                  class="accounting-field"
                />
                <div class="flex gap-2">
                  <select
                    v-model="editingCategoryType"
                    class="accounting-field flex-1"
                  >
                    <option value="支出">支出</option>
                    <option value="收入">收入</option>
                    <option value="转账">转账</option>
                  </select>
                  <button @click="saveEditCategory" class="px-3 py-2 rounded-lg bg-indigo-500 text-white text-sm"><Check class="w-4 h-4" /></button>
                  <button @click="cancelEditCategory" class="px-3 py-2 rounded-lg bg-slate-200 text-slate-700 text-sm">取消</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-else-if="kind === 'book'" class="space-y-4">
          <div class="bg-white dark:bg-slate-800 rounded-2xl p-4 border border-slate-100 dark:border-slate-700 shadow-sm space-y-3">
            <input
              v-model="newBookName"
              type="text"
              placeholder="输入新账本名称"
              class="accounting-field"
            />
            <button
              @click="addBook"
              :disabled="operating"
              class="w-full py-2.5 rounded-xl bg-indigo-500 text-white font-medium disabled:opacity-50"
            >新建账本</button>
          </div>

          <div class="bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm overflow-hidden">
            <AccountingEmptyState v-if="store.books.length === 0" title="暂无账本" description="在上方输入名称后创建" />
            <div v-for="book in store.books" :key="book.id" class="px-4 py-3 border-b border-slate-100 dark:border-slate-700 last:border-b-0">
              <div v-if="editingBookId !== book.id" class="flex items-center gap-3">
                <button
                  @click="selectBook(book.id, book.name)"
                  class="flex-1 text-left text-sm"
                  :class="store.currentBookId === book.id ? 'text-indigo-600 font-semibold' : 'text-slate-800 dark:text-white'"
                >
                  {{ book.name }}
                </button>
                <button @click="startEditBook(book.id, book.name)" class="p-1.5 text-slate-500 hover:text-slate-700">
                  <Pencil class="w-4 h-4" />
                </button>
                <button @click="removeBook(book.id, book.name)" class="p-1.5 text-rose-500 hover:text-rose-600">
                  <Trash2 class="w-4 h-4" />
                </button>
              </div>

              <div v-else class="flex gap-2">
                <input
                  v-model="editingBookName"
                  type="text"
                  class="accounting-field flex-1"
                />
                <button @click="saveBook" class="px-3 py-2 rounded-lg bg-indigo-500 text-white text-sm"><Check class="w-4 h-4" /></button>
                <button @click="cancelEditBook" class="px-3 py-2 rounded-lg bg-slate-200 text-slate-700 text-sm">取消</button>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="space-y-4">
          <div class="bg-white dark:bg-slate-800 rounded-2xl p-4 border border-slate-100 dark:border-slate-700 shadow-sm space-y-3">
            <input
              v-model="newLocalName"
              type="text"
              :placeholder="localPlaceholder"
              class="accounting-field"
            />
            <button @click="addLocalEntry" class="w-full py-2.5 rounded-xl bg-indigo-500 text-white font-medium">新增</button>
          </div>

          <div class="bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm overflow-hidden">
            <div v-if="localItems.length === 0" class="p-6 text-center text-sm text-slate-500">{{ localEmptyText }}</div>
            <div v-for="item in localItems" :key="item.id" class="px-4 py-3 border-b border-slate-100 dark:border-slate-700 last:border-b-0 flex items-center gap-3">
              <span class="flex-1 text-sm text-slate-800 dark:text-white">{{ item.name }}</span>
              <button @click="removeLocalEntry(item)" class="p-1.5 text-rose-500 hover:text-rose-600">
                <Trash2 class="w-4 h-4" />
              </button>
            </div>
          </div>

          <div v-if="kind === 'merchant'" class="bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm overflow-hidden">
            <div class="px-4 py-3 text-sm font-medium text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-700">最近交易中的商家</div>
            <div v-if="recentMerchants.length === 0" class="p-4 text-sm text-slate-500">暂无交易商家</div>
            <div v-for="merchant in recentMerchants" :key="merchant" class="px-4 py-2.5 text-sm text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-700 last:border-b-0">
              {{ merchant }}
            </div>
          </div>
        </div>
      </template>
    </main>
  </div>
</template>
