<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAccountingStore } from '@/stores/accounting'
import {
    getRecordDetail,
    updateRecord,
    deleteRecord,
    getCategories,
    getAccounts,
    type CategoryItem,
    type AccountItem,
    type RecordItem,
} from '@/api/accounting'
import { ChevronLeft, Loader2, Trash2 } from 'lucide-vue-next'
import AccountingLoadingState from '@/components/accounting/AccountingLoadingState.vue'
import AccountingErrorState from '@/components/accounting/AccountingErrorState.vue'
import { appendOperationLog } from '@/utils/accountingLocal'
import {
    formatRecordTimeForInput,
    serializeRecordTimeInput,
} from '@/utils/accountingDateTime'
import { accountingConfirm } from '@/utils/accountingDialog'
import { formatAccountingMoney } from '@/utils/accountingFormat'
import {
    accountingErrorMessage,
    accountingToastError,
    accountingToastSuccess,
} from '@/utils/accountingToast'

const router = useRouter()
const route = useRoute()
const store = useAccountingStore()

const loading = ref(false)
const saving = ref(false)
const deleting = ref(false)
const categories = ref<CategoryItem[]>([])
const accounts = ref<AccountItem[]>([])
const originalRecord = ref<RecordItem | null>(null)
const loadFailed = ref(false)

const getRecordId = () => {
    const raw = route.params.id
    const value = Number(Array.isArray(raw) ? raw[0] : raw)
    return Number.isFinite(value) ? value : 0
}

const recordId = getRecordId()

const form = ref({
    type: '支出',
    amount: '',
    category_name: '未分类',
    account_name: '',
    target_account_name: '',
    payee: '',
    remark: '',
    record_time: '',
    is_large_expense: false,
    exclude_from_budget: false,
})

const tabs = ['支出', '收入', '转账'] as const

const displayCategories = computed(() => {
    const names = categories.value
        .filter(c => c.type === form.value.type)
        .map(c => c.name)

    if (form.value.category_name && !names.includes(form.value.category_name)) {
        names.unshift(form.value.category_name)
    }
    if (!names.includes('未分类')) {
        names.unshift('未分类')
    }

    return names
})

const loadData = async () => {
    if (!recordId) {
        loadFailed.value = true
        return
    }

    if (!store.currentBookId) {
        await store.fetchBooks()
    }

    if (!store.currentBookId) {
        loadFailed.value = true
        return
    }

    loading.value = true
    loadFailed.value = false

    try {
        const [recordRes, categoryRes, accountRes] = await Promise.all([
            getRecordDetail(store.currentBookId, recordId),
            getCategories(store.currentBookId),
            getAccounts(store.currentBookId),
        ])

        const record = recordRes.data
        originalRecord.value = record
        categories.value = categoryRes.data
        accounts.value = accountRes.data

        form.value = {
            type: record.type || '支出',
            amount: String(record.amount || ''),
            category_name: record.category || '未分类',
            account_name: record.account || '',
            target_account_name: record.target_account || '',
            payee: record.payee || '',
            remark: record.remark || '',
            record_time: formatRecordTimeForInput(record.record_time),
            is_large_expense: Boolean(record.is_large_expense),
            exclude_from_budget: Boolean(record.exclude_from_budget),
        }
    } catch (e) {
        loadFailed.value = true
        accountingToastError(accountingErrorMessage(e, '记录加载失败'))
    } finally {
        loading.value = false
    }
}

const handleSave = async () => {
    if (!store.currentBookId || !recordId) return

    const amount = Number(form.value.amount)
    if (!amount || amount <= 0) {
        accountingToastError('请输入正确的金额')
        return
    }

    saving.value = true
    try {
        const recordTime = serializeRecordTimeInput(form.value.record_time)
        await updateRecord(store.currentBookId, recordId, {
            type: form.value.type,
            amount,
            category_name: form.value.category_name?.trim() || '',
            account_name: form.value.account_name?.trim() || '',
            target_account_name: form.value.type === '转账'
                ? (form.value.target_account_name?.trim() || '')
                : '',
            payee: form.value.payee?.trim() || '',
            remark: form.value.remark?.trim() || '',
            record_time: recordTime || undefined,
            is_large_expense: form.value.type === '支出' ? form.value.is_large_expense : false,
            exclude_from_budget: form.value.type === '支出' ? form.value.exclude_from_budget : false,
        })
        appendOperationLog(
            store.currentBookId,
            '更新交易',
            `ID ${recordId} · ${form.value.type} · ${formatAccountingMoney(amount)}`,
        )
        accountingToastSuccess('保存成功')
        await loadData()
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '保存失败，请稍后重试'))
    } finally {
        saving.value = false
    }
}

const handleDelete = async () => {
    if (!store.currentBookId || !recordId) return
    if (!await accountingConfirm('确定删除这条记录吗？删除后可在操作日志里回滚。')) return

    const snapshot = originalRecord.value
    deleting.value = true
    try {
        await deleteRecord(store.currentBookId, recordId)
        if (snapshot) {
            const rollbackType = snapshot.type === '收入' || snapshot.type === '转账' ? snapshot.type : '支出'
            appendOperationLog(
                store.currentBookId,
                '删除交易',
                `ID ${recordId} · ${snapshot.type} · ${formatAccountingMoney(snapshot.amount)}`,
                {
                    rollback: {
                        kind: 'record',
                        data: {
                            type: rollbackType,
                            amount: snapshot.amount,
                            category_name: snapshot.category || '未分类',
                            account_name: snapshot.account || '',
                            target_account_name: snapshot.target_account || '',
                            payee: snapshot.payee || '',
                            remark: snapshot.remark || '',
                            record_time: snapshot.record_time,
                        },
                    },
                },
            )
        } else {
            appendOperationLog(store.currentBookId, '删除交易', `ID ${recordId}`)
        }
        accountingToastSuccess('删除成功')
        router.replace('/accounting/records')
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '删除失败，请稍后重试'))
    } finally {
        deleting.value = false
    }
}

onMounted(() => {
    loadData()
})
</script>

<template>
  <div class="accounting-fullscreen bg-theme-primary relative z-50">
    <header class="bg-white dark:bg-slate-800 shadow-sm relative z-10 safe-top">
      <div class="flex items-center justify-between h-14 px-4">
        <button @click="router.back()" class="p-2 -ml-2 text-slate-600 dark:text-slate-300">
          <ChevronLeft class="w-6 h-6" />
        </button>
        <h1 class="text-lg font-bold text-slate-800 dark:text-white">交易详情</h1>
        <button
          @click="handleSave"
          :disabled="saving || deleting || loading || loadFailed"
          class="px-3 py-1.5 rounded-lg bg-indigo-500 text-white text-sm font-medium disabled:opacity-50"
        >
          <Loader2 v-if="saving" class="w-4 h-4 animate-spin" />
          <span v-else>保存</span>
        </button>
      </div>
    </header>

    <main class="flex-1 min-h-0 overflow-y-auto accounting-scroll p-4 accounting-subpage-pad">
      <AccountingLoadingState v-if="loading" />

      <AccountingErrorState
        v-else-if="loadFailed"
        title="记录加载失败"
        description="记录不存在或网络异常"
        @retry="loadData"
      />

      <div v-else class="space-y-4">
        <div class="bg-white dark:bg-slate-800 rounded-2xl p-4 shadow-sm border border-slate-100 dark:border-slate-700">
          <p class="text-xs text-slate-500 mb-2">交易类型</p>
          <div class="grid grid-cols-3 gap-2">
            <button
              v-for="tab in tabs"
              :key="tab"
              @click="form.type = tab"
              :class="[
                'py-2 rounded-lg text-sm font-medium transition',
                form.type === tab
                  ? 'bg-indigo-500 text-white'
                  : 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300'
              ]"
            >
              {{ tab }}
            </button>
          </div>
        </div>

        <div class="bg-white dark:bg-slate-800 rounded-2xl p-4 shadow-sm border border-slate-100 dark:border-slate-700 space-y-4">
          <div>
            <label class="block text-xs text-slate-500 mb-1">金额</label>
            <input
              v-model="form.amount"
              type="number"
              step="0.01"
              min="0"
              class="accounting-field"
            />
          </div>

          <div>
            <label class="block text-xs text-slate-500 mb-1">分类</label>
            <select
              v-model="form.category_name"
              class="accounting-field"
            >
              <option v-for="name in displayCategories" :key="name" :value="name">{{ name }}</option>
            </select>
          </div>

          <div>
            <label class="block text-xs text-slate-500 mb-1">账户</label>
            <select
              v-model="form.account_name"
              class="accounting-field"
            >
              <option value="">未指定</option>
              <option v-for="acc in accounts" :key="acc.id" :value="acc.name">{{ acc.name }} ({{ acc.type }})</option>
            </select>
          </div>

          <div v-if="form.type === '转账'">
            <label class="block text-xs text-slate-500 mb-1">转入账户</label>
            <select
              v-model="form.target_account_name"
              class="accounting-field"
            >
              <option value="">未指定</option>
              <option v-for="acc in accounts" :key="acc.id" :value="acc.name">{{ acc.name }}</option>
            </select>
          </div>

          <div>
            <label class="block text-xs text-slate-500 mb-1">交易对象</label>
            <input
              v-model="form.payee"
              type="text"
              placeholder="例如：超市、公司、朋友"
              class="accounting-field"
            />
          </div>

          <div>
            <label class="block text-xs text-slate-500 mb-1">备注</label>
            <textarea
              v-model="form.remark"
              rows="3"
              placeholder="可选备注"
              class="accounting-field"
            />
          </div>

          <div>
            <label class="block text-xs text-slate-500 mb-1">交易时间</label>
            <input
              v-model="form.record_time"
              type="datetime-local"
              class="accounting-field"
            />
          </div>

          <div v-if="form.type === '支出'" class="pt-2 border-t border-slate-100 dark:border-slate-700 space-y-3">
            <div class="flex items-center justify-between">
              <div>
                <label class="block text-xs font-medium text-slate-700 dark:text-slate-200">不计入预算</label>
                <p class="text-[11px] text-slate-400">不占用常规月度预算与专项大额池（如股票对齐、理财投资等）</p>
              </div>
              <input
                v-model="form.exclude_from_budget"
                type="checkbox"
                class="w-5 h-5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
              />
            </div>

            <div v-if="!form.exclude_from_budget" class="flex items-center justify-between pt-2 border-t border-slate-100 dark:border-slate-700">
              <div>
                <label class="block text-xs font-medium text-slate-700 dark:text-slate-200">年度大额专项支出</label>
                <p class="text-[11px] text-slate-400">计入年度大额专项池，不占用月度常规预算</p>
              </div>
              <input
                v-model="form.is_large_expense"
                type="checkbox"
                class="w-5 h-5 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
              />
            </div>
          </div>
        </div>

        <button
          @click="handleSave"
          :disabled="saving || deleting || loadFailed"
          class="w-full py-3 bg-indigo-500 hover:bg-indigo-600 text-white rounded-xl font-medium shadow-lg shadow-indigo-500/30 disabled:opacity-50"
        >
          <Loader2 v-if="saving" class="w-4 h-4 animate-spin mx-auto" />
          <span v-else>保存修改</span>
        </button>

        <button
          @click="handleDelete"
          :disabled="saving || deleting || loadFailed"
          class="w-full py-3 rounded-xl font-medium border border-rose-200 text-rose-600 bg-rose-50 hover:bg-rose-100 disabled:opacity-50 flex items-center justify-center gap-1"
        >
          <Loader2 v-if="deleting" class="w-4 h-4 animate-spin" />
          <template v-else>
            <Trash2 class="w-4 h-4" />
            删除记录
          </template>
        </button>
      </div>
    </main>
  </div>
</template>
