<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAccountingStore } from '@/stores/accounting'
import { getDebts, type Debt } from '@/api/accounting'
import {
    ArrowDownToLine, ArrowUpFromLine, Receipt, Users,
    CalendarClock, CreditCard, Target, PiggyBank,
} from 'lucide-vue-next'
import {
    debtRemainingLabel,
    summarizeDebtRemaining,
} from '@/utils/accountingMoney'
import { getAccountingMoneySettings } from '@/utils/accountingFormat'
import QuickAddFab from '@/components/accounting/QuickAddFab.vue'

const store = useAccountingStore()
const debts = ref<Debt[]>([])
const loading = ref(false)

const moneySettings = computed(() => getAccountingMoneySettings())

const remaining = computed(() => summarizeDebtRemaining(debts.value))

const sections = computed(() => [
    {
        title: '往来管理',
        subtitle: '借入、借出与报销',
        items: [
            {
                icon: ArrowDownToLine,
                label: '借入',
                desc: debtRemainingLabel('借入', remaining.value, moneySettings.value),
                route: '/accounting/debts?type=借入',
            },
            {
                icon: ArrowUpFromLine,
                label: '借出',
                desc: debtRemainingLabel('借出', remaining.value, moneySettings.value),
                route: '/accounting/debts?type=借出',
            },
            {
                icon: Receipt,
                label: '报销',
                desc: debtRemainingLabel('报销', remaining.value, moneySettings.value),
                route: '/accounting/debts?type=报销',
            },
            {
                icon: Users,
                label: '往来',
                desc: '管理全部',
                route: '/accounting/debts',
            },
        ],
    },
    {
        title: '计划管理',
        subtitle: '周期与预算',
        items: [
            {
                icon: CalendarClock,
                label: '周期',
                desc: '计划任务',
                route: '/accounting/scheduled-tasks',
            },
            {
                icon: CreditCard,
                label: '分期',
                desc: '项目管理',
                route: '/accounting/manage/project',
            },
            {
                icon: Target,
                label: '预算',
                desc: '月度预算',
                route: '/accounting/budgets',
            },
            {
                icon: PiggyBank,
                label: '存钱',
                desc: '预算计划',
                route: '/accounting/budgets',
            },
        ],
    },
])

const loadDebts = async () => {
    if (!store.currentBookId) return
    loading.value = true
    try {
        const res = await getDebts(store.currentBookId)
        debts.value = res.data
    } catch (e) {
        console.error(e)
        debts.value = []
    } finally {
        loading.value = false
    }
}

onMounted(async () => {
    if (!store.currentBookId) await store.fetchBooks()
    await loadDebts()
})
</script>

<template>
  <div class="accounting-page-pad">
    <div class="px-4 pt-4 pb-2">
      <h2 class="text-lg font-bold text-theme-primary text-center">更多</h2>
    </div>

    <div v-for="section in sections" :key="section.title" class="px-4 mt-4">
      <h3 class="text-base font-bold text-accounting-brand">{{ section.title }}</h3>
      <p class="text-xs text-theme-muted mb-3">{{ section.subtitle }}</p>

      <div class="grid grid-cols-2 gap-3">
        <RouterLink
          v-for="item in section.items"
          :key="item.label"
          :to="item.route"
          class="bg-theme-elevated rounded-2xl p-4 shadow-sm border border-theme-secondary hover:shadow-md transition cursor-pointer"
        >
          <div class="flex items-center gap-3">
            <div class="w-10 h-10 rounded-xl flex items-center justify-center bg-accounting-brand">
              <component :is="item.icon" class="w-5 h-5 text-white" />
            </div>
            <div class="min-w-0">
              <p class="font-semibold text-theme-primary text-sm">{{ item.label }}</p>
              <p class="text-xs text-theme-muted truncate">{{ loading && item.desc.includes('待') ? '加载中…' : item.desc }}</p>
            </div>
          </div>
        </RouterLink>
      </div>
    </div>

    <QuickAddFab :book-id="store.currentBookId" @saved="loadDebts" />
  </div>
</template>
