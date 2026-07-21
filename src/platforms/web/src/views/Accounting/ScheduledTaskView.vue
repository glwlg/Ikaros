<script setup lang="ts">
import { onMounted, ref, computed } from 'vue'
import { useAccountingStore } from '@/stores/accounting'
import {
    getScheduledTasks,
    createScheduledTask,
    deleteScheduledTask,
    getAccounts,
    getCategories,
    type ScheduledTask,
    type AccountItem,
    type CategoryItem,
} from '@/api/accounting'
import {
    Plus, CalendarClock, Trash2, ArrowRightLeft, ArrowRight,
} from 'lucide-vue-next'
import AccountingPageHeader from '@/components/accounting/AccountingPageHeader.vue'
import AccountingLoadingState from '@/components/accounting/AccountingLoadingState.vue'
import AccountingEmptyState from '@/components/accounting/AccountingEmptyState.vue'
import AccountingErrorState from '@/components/accounting/AccountingErrorState.vue'
import { accountingConfirm } from '@/utils/accountingDialog'
import { formatAccountingMoney } from '@/utils/accountingFormat'
import { moneyTypeTextClass } from '@/utils/accountingMoney'
import {
    accountingErrorMessage,
    accountingToastError,
    accountingToastSuccess,
} from '@/utils/accountingToast'

const store = useAccountingStore()

const tasks = ref<ScheduledTask[]>([])
const accounts = ref<AccountItem[]>([])
const categories = ref<CategoryItem[]>([])
const loading = ref(false)
const loadError = ref('')
const showCreateDialog = ref(false)
const saving = ref(false)

const createForm = ref({
    name: '',
    frequency: '每月',
    type: '支出',
    amount: '',
    account_id: '' as number | '',
    target_account_id: '' as number | '',
    category_id: '' as number | '',
    payee: '',
    remark: '',
})

const frequencies = ['每天', '每周', '每月', '每年']
const types = ['支出', '收入', '转账']

const filteredCategories = computed(() =>
    categories.value.filter(c => c.type === createForm.value.type),
)

const loadData = async () => {
    if (!store.currentBookId) return
    loading.value = true
    loadError.value = ''
    try {
        const [taskRes, accRes, catRes] = await Promise.all([
            getScheduledTasks(store.currentBookId),
            getAccounts(store.currentBookId),
            getCategories(store.currentBookId),
        ])
        tasks.value = taskRes.data
        accounts.value = accRes.data
        categories.value = catRes.data
    } catch (e) {
        loadError.value = accountingErrorMessage(e, '周期计划加载失败')
        accountingToastError(loadError.value)
    } finally {
        loading.value = false
    }
}

const openCreate = () => {
    createForm.value = {
        name: '',
        frequency: '每月',
        type: '支出',
        amount: '',
        account_id: accounts.value[0]?.id ?? '',
        target_account_id: '',
        category_id: '',
        payee: '',
        remark: '',
    }
    showCreateDialog.value = true
}

const getNextRunDate = (freq: string) => {
    const d = new Date()
    if (freq === '每天') d.setDate(d.getDate() + 1)
    else if (freq === '每周') d.setDate(d.getDate() + 7)
    else if (freq === '每月') d.setMonth(d.getMonth() + 1)
    else if (freq === '每年') d.setFullYear(d.getFullYear() + 1)
    return d.toISOString()
}

const saveTask = async () => {
    if (!store.currentBookId) return
    if (!createForm.value.name.trim() || !createForm.value.amount) {
        accountingToastError('请填写计划名称和金额')
        return
    }
    if (!createForm.value.account_id) {
        accountingToastError('请选择账户')
        return
    }
    if (createForm.value.type !== '转账' && !createForm.value.category_id) {
        accountingToastError('请选择分类')
        return
    }
    if (createForm.value.type === '转账' && !createForm.value.target_account_id) {
        accountingToastError('转账请选择转入账户')
        return
    }
    if (
        createForm.value.type === '转账'
        && createForm.value.account_id === createForm.value.target_account_id
    ) {
        accountingToastError('转入账户不能与转出账户相同')
        return
    }

    saving.value = true
    try {
        const next_run = getNextRunDate(createForm.value.frequency)
        await createScheduledTask(store.currentBookId, {
            name: createForm.value.name.trim(),
            frequency: createForm.value.frequency,
            type: createForm.value.type,
            amount: Number(createForm.value.amount),
            next_run,
            account_id: Number(createForm.value.account_id),
            target_account_id: createForm.value.type === '转账'
                ? Number(createForm.value.target_account_id)
                : undefined,
            category_id: createForm.value.category_id
                ? Number(createForm.value.category_id)
                : undefined,
            payee: createForm.value.payee || undefined,
            remark: createForm.value.remark || undefined,
        })
        showCreateDialog.value = false
        accountingToastSuccess('计划已创建')
        await loadData()
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '保存失败'))
    } finally {
        saving.value = false
    }
}

const handleDelete = async (id: number) => {
    if (!store.currentBookId) return
    const ok = await accountingConfirm('确定要删除该周期计划吗？', { title: '删除计划' })
    if (!ok) return
    try {
        await deleteScheduledTask(store.currentBookId, id)
        accountingToastSuccess('计划已删除')
        await loadData()
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '删除失败'))
    }
}

onMounted(async () => {
    if (!store.currentBookId) await store.fetchBooks()
    await loadData()
})

const formatDate = (dateString: string | null) => {
    if (!dateString) return '未设置'
    return new Date(dateString).toLocaleDateString('zh-CN')
}

const getIconColor = (type: string) => {
    if (type === '支出') return 'bg-accounting-expense/15 text-accounting-expense'
    if (type === '收入') return 'bg-accounting-income/15 text-accounting-income'
    return 'bg-accounting-transfer/15 text-accounting-transfer'
}
</script>

<template>
  <div class="accounting-fullscreen bg-theme-primary">
    <AccountingPageHeader title="计划管理">
      <template #actions>
        <button type="button" class="p-2 text-accounting-brand" @click="openCreate">
          <Plus class="w-6 h-6" />
        </button>
      </template>
    </AccountingPageHeader>

    <main class="flex-1 min-h-0 overflow-y-auto accounting-scroll p-4 accounting-subpage-pad">
      <AccountingLoadingState v-if="loading" />
      <AccountingErrorState
        v-else-if="loadError"
        title="周期计划加载失败"
        :description="loadError"
        @retry="loadData"
      />
      <AccountingEmptyState
        v-else-if="tasks.length === 0"
        title="暂无周期计划"
        description="添加房租、工资等自动计划"
      >
        <template #icon>
          <CalendarClock class="w-7 h-7" />
        </template>
        <template #action>
          <button
            type="button"
            class="px-4 py-2 rounded-xl bg-accounting-brand text-white text-sm"
            @click="openCreate"
          >
            新增计划
          </button>
        </template>
      </AccountingEmptyState>

      <div v-else class="space-y-4">
        <div
          v-for="task in tasks"
          :key="task.id"
          class="bg-theme-elevated rounded-2xl p-4 shadow-sm border border-theme-secondary"
          :class="{ 'opacity-60': !task.is_active }"
        >
          <div class="flex items-start justify-between">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-xl flex items-center justify-center" :class="getIconColor(task.type)">
                <ArrowRightLeft v-if="task.type === '转账'" class="w-5 h-5 flex-shrink-0" />
                <ArrowRight
                  v-else
                  class="w-5 h-5 flex-shrink-0"
                  :class="task.type === '支出' ? 'rotate-45' : '-rotate-45'"
                />
              </div>
              <div>
                <div class="flex items-center gap-2">
                  <h3 class="font-bold text-theme-primary">{{ task.name }}</h3>
                  <span class="px-2 py-0.5 rounded text-[10px] font-medium bg-theme-secondary text-theme-muted">
                    {{ task.frequency }}
                  </span>
                </div>
                <div class="text-xs text-theme-muted mt-0.5">
                  下次执行: {{ formatDate(task.next_run) }}
                </div>
              </div>
            </div>

            <div class="text-right">
              <div class="text-base font-bold tabular-nums" :class="moneyTypeTextClass(task.type)">
                {{ task.type === '支出' ? '-' : (task.type === '收入' ? '+' : '') }}{{ formatAccountingMoney(task.amount) }}
              </div>
              <div class="mt-1 flex justify-end">
                <button
                  type="button"
                  class="text-theme-muted hover:text-accounting-expense transition rounded-md p-1"
                  @click="handleDelete(task.id)"
                >
                  <Trash2 class="w-4 h-4" />
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </main>

    <div v-if="showCreateDialog" class="fixed inset-0 bg-black/50 z-[60] flex items-end sm:items-center justify-center p-0 sm:p-4">
      <div class="bg-theme-elevated rounded-t-2xl sm:rounded-2xl w-full sm:max-w-sm overflow-hidden safe-bottom">
        <div class="p-4 border-b border-theme-secondary">
          <h2 class="text-lg font-bold text-center text-theme-primary">新增周期计划</h2>
        </div>
        <div class="p-4 space-y-3 max-h-[60vh] overflow-y-auto">
          <div>
            <label class="block text-sm text-theme-muted mb-1">计划名称</label>
            <input
              v-model="createForm.name"
              type="text"
              class="accounting-field"
              placeholder="房租/工资/还款"
            >
          </div>
          <div class="flex gap-3">
            <div class="flex-1">
              <label class="block text-sm text-theme-muted mb-1">执行周期</label>
              <select
                v-model="createForm.frequency"
                class="accounting-field"
              >
                <option v-for="freq in frequencies" :key="freq" :value="freq">{{ freq }}</option>
              </select>
            </div>
            <div class="flex-1">
              <label class="block text-sm text-theme-muted mb-1">交易类型</label>
              <select
                v-model="createForm.type"
                class="accounting-field"
                @change="createForm.category_id = ''"
              >
                <option v-for="t in types" :key="t" :value="t">{{ t }}</option>
              </select>
            </div>
          </div>
          <div>
            <label class="block text-sm text-theme-muted mb-1">金额</label>
            <input
              v-model="createForm.amount"
              type="number"
              class="accounting-field"
              placeholder="0.00"
            >
          </div>
          <div>
            <label class="block text-sm text-theme-muted mb-1">账户 <span class="text-accounting-expense">*</span></label>
            <select
              v-model="createForm.account_id"
              class="accounting-field"
            >
              <option value="">请选择账户</option>
              <option v-for="acc in accounts" :key="acc.id" :value="acc.id">{{ acc.name }}</option>
            </select>
          </div>
          <div v-if="createForm.type === '转账'">
            <label class="block text-sm text-theme-muted mb-1">转入账户 <span class="text-accounting-expense">*</span></label>
            <select
              v-model="createForm.target_account_id"
              class="accounting-field"
            >
              <option value="">请选择转入账户</option>
              <option v-for="acc in accounts" :key="acc.id" :value="acc.id">{{ acc.name }}</option>
            </select>
          </div>
          <div v-if="createForm.type !== '转账'">
            <label class="block text-sm text-theme-muted mb-1">分类 <span class="text-accounting-expense">*</span></label>
            <select
              v-model="createForm.category_id"
              class="accounting-field"
            >
              <option value="">请选择分类</option>
              <option v-for="cat in filteredCategories" :key="cat.id" :value="cat.id">{{ cat.name }}</option>
            </select>
          </div>
          <div>
            <label class="block text-sm text-theme-muted mb-1">备注 (选填)</label>
            <input
              v-model="createForm.remark"
              type="text"
              class="accounting-field"
              placeholder="添加备注..."
            >
          </div>
        </div>
        <div class="p-4 flex gap-3 border-t border-theme-secondary">
          <button
            type="button"
            class="flex-1 py-3 bg-theme-secondary text-theme-secondary rounded-xl font-medium"
            @click="showCreateDialog = false"
          >
            取消
          </button>
          <button
            type="button"
            class="flex-1 py-3 bg-accounting-brand text-white rounded-xl font-medium disabled:opacity-50"
            :disabled="saving"
            @click="saveTask"
          >
            保存
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
