<script setup lang="ts">
import { ref, computed, onBeforeUnmount, onMounted } from 'vue'
import { createRecord, getCategories, getAccounts, type CategoryItem, type AccountItem } from '@/api/accounting'
import { X, Delete, Loader2, ChevronRight } from 'lucide-vue-next'
import { appendOperationLog, loadNamedItems, type NamedItem } from '@/utils/accountingLocal'
import { toLocalIsoString } from '@/utils/accountingDateTime'
import { formatAccountingMoney } from '@/utils/accountingFormat'
import { moneyTypeTextClass } from '@/utils/accountingMoney'
import {
    accountingErrorMessage,
    accountingToastError,
    accountingToastSuccess,
} from '@/utils/accountingToast'

const props = defineProps<{
    bookId: number
}>()

const emit = defineEmits<{
    close: []
    saved: []
}>()

// Tab: 支出/收入/转账
const activeTab = ref<'支出' | '收入' | '转账'>('支出')
const tabs = ['支出', '收入', '转账'] as const

// Amount input
const amountStr = ref('0')

const arithmeticOperators = new Set(['+', '-', '×', '÷'])

const hasExpression = computed(() => /[+\-×÷()]/.test(amountStr.value))
const actionKeyLabel = computed(() => (hasExpression.value ? '=' : 'OK'))

// Categories
const categories = ref<CategoryItem[]>([])
const selectedCategory = ref('')

// Accounts
const accounts = ref<AccountItem[]>([])
const selectedAccount = ref('')
const selectedTargetAccount = ref('')

// Other fields
const remark = ref('')
const payee = ref('')
const selectedProject = ref('')
const selectedTag = ref('')
const projects = ref<NamedItem[]>([])
const tags = ref<NamedItem[]>([])
const merchants = ref<NamedItem[]>([])
const saving = ref(false)

// Date time selection
const selectedDate = ref('')
const selectedTime = ref('')

// Initialize date and time to now
const initDateTime = () => {
    const now = new Date()
    selectedDate.value = now.toISOString().slice(0, 10)
    selectedTime.value = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
}

const buildRecordTime = () => {
    if (!selectedDate.value || !selectedTime.value) {
        return toLocalIsoString(new Date(), { includeSeconds: true })
    }
    return `${selectedDate.value}T${selectedTime.value}:00`
}

// Default categories per type - main categories shown first
const mainCategories: Record<string, string[]> = {
    '支出': ['买菜', '交通', '娱乐', '日用', '水果', '水电', '购物', '餐饮美食'],
    '收入': ['工资', '奖金', '红包', '理财', '报销', '兼职', '其他'],
    '转账': ['转账'],
}

const allCategories: Record<string, string[]> = {
    '支出': ['买菜', '交通', '娱乐', '日用', '水果', '水电', '购物', '餐饮美食', '零食', '运动', '通讯', '服饰', '其他'],
    '收入': ['工资', '奖金', '红包', '理财', '报销', '兼职', '其他'],
    '转账': ['转账'],
}

// Category popup
const showCategoryPopup = ref(false)

const displayCategories = computed(() => {
    // 只显示8个主要分类
    return mainCategories[activeTab.value] || []
})

const allDisplayCategories = computed(() => {
    const userCats = categories.value
        .filter(c => c.type === activeTab.value)
        .map(c => c.name)
    const all = allCategories[activeTab.value] || []
    // 合并所有分类，包括用户自定义的
    const extraUserCats = userCats.filter(c => !all.includes(c))
    return [...all, ...extraUserCats]
})

const formatCalculatedValue = (value: number) => {
    if (!Number.isFinite(value)) return '0'
    const fixed = value.toFixed(10)
    const trimmed = fixed.replace(/\.0+$/, '').replace(/(\.\d*?)0+$/, '$1')
    return trimmed === '-0' ? '0' : trimmed
}

const evaluateExpression = (expression: string): number | null => {
    const sanitized = expression.replace(/\s+/g, '').replace(/×/g, '*').replace(/÷/g, '/')
    if (!sanitized) return null

    const tokens: Array<number | string> = []
    let index = 0

    const isDigitOrDot = (char: string) => /[0-9.]/.test(char)
    const previousToken = () => (tokens.length ? tokens[tokens.length - 1] : null)

    while (index < sanitized.length) {
        const char = sanitized[index]
        if (!char) break

        if (isDigitOrDot(char) || (char === '-' && (index === 0 || ['+', '-', '*', '/', '('].includes(String(previousToken() ?? ''))) )) {
            let next = index
            let seenDot = false
            if (sanitized[next] === '-') next += 1

            while (next < sanitized.length) {
                const cursor = sanitized[next]
                if (!cursor) break
                if (cursor === '.') {
                    if (seenDot) return null
                    seenDot = true
                    next += 1
                    continue
                }
                if (!/[0-9]/.test(cursor)) break
                next += 1
            }

            const raw = sanitized.slice(index, next)
            if (raw === '-' || raw === '.' || raw === '-.') return null
            const number = Number(raw)
            if (!Number.isFinite(number)) return null
            tokens.push(number)
            index = next
            continue
        }

        if (['+', '-', '*', '/', '(', ')'].includes(char)) {
            tokens.push(char)
            index += 1
            continue
        }

        return null
    }

    const values: number[] = []
    const operators: string[] = []
    const precedence = (op: string) => (op === '+' || op === '-' ? 1 : 2)

    const applyTopOperator = () => {
        const operator = operators.pop()
        const right = values.pop()
        const left = values.pop()
        if (!operator || left === undefined || right === undefined) return false

        if (operator === '+') values.push(left + right)
        else if (operator === '-') values.push(left - right)
        else if (operator === '*') values.push(left * right)
        else if (operator === '/') {
            if (right === 0) return false
            values.push(left / right)
        }
        return true
    }

    for (const token of tokens) {
        if (typeof token === 'number') {
            values.push(token)
            continue
        }

        if (token === '(') {
            operators.push(token)
            continue
        }

        if (token === ')') {
            while (operators.length && operators[operators.length - 1] !== '(') {
                if (!applyTopOperator()) return null
            }
            if (operators[operators.length - 1] !== '(') return null
            operators.pop()
            continue
        }

        while (
            operators.length
            && operators[operators.length - 1] !== '('
            && precedence(operators[operators.length - 1] || '+') >= precedence(token)
        ) {
            if (!applyTopOperator()) return null
        }
        operators.push(token)
    }

    while (operators.length) {
        if (operators[operators.length - 1] === '(') return null
        if (!applyTopOperator()) return null
    }

    if (values.length !== 1) return null
    return values[0] ?? null
}

const evaluateCurrentExpression = () => {
    const result = evaluateExpression(amountStr.value)
    if (result === null) return
    amountStr.value = formatCalculatedValue(result)
}

const appendOperator = (operator: string) => {
    const current = amountStr.value
    const last = current.slice(-1)

    if (current === '0' && operator !== '-') return
    if (arithmeticOperators.has(last)) {
        amountStr.value = `${current.slice(0, -1)}${operator}`
        return
    }
    if (last === '(' && operator !== '-') return
    amountStr.value += operator
}

const toggleParenthesis = () => {
    const current = amountStr.value
    const leftCount = (current.match(/\(/g) || []).length
    const rightCount = (current.match(/\)/g) || []).length
    const last = current.slice(-1)

    const shouldOpen = leftCount === rightCount || arithmeticOperators.has(last) || last === '('
    if (shouldOpen) {
        if (current === '0') {
            amountStr.value = '('
            return
        }
        amountStr.value += '('
        return
    }

    if (/[0-9)]/.test(last)) {
        amountStr.value += ')'
    }
}

const appendNumber = (digit: string) => {
    if (amountStr.value === '0') {
        amountStr.value = digit
        return
    }
    amountStr.value += digit
}

const appendDot = () => {
    const current = amountStr.value
    const last = current.slice(-1)
    if (arithmeticOperators.has(last) || last === '(' || last === ')') {
        amountStr.value += '0.'
        return
    }

    const segment = current.split(/[+\-×÷()]/).pop() || ''
    if (segment.includes('.')) return
    amountStr.value += '.'
}

const handleKeyPress = (key: string) => {
    if (key === 'C') {
        amountStr.value = '0'
        return
    }

    if (key === '⌫') {
        if (amountStr.value.length > 1) {
            amountStr.value = amountStr.value.slice(0, -1)
        } else {
            amountStr.value = '0'
        }
        return
    }

    if (key === 'OK') {
        if (actionKeyLabel.value === '=') {
            evaluateCurrentExpression()
        } else {
            handleSave()
        }
        return
    }

    if (key === '.') {
        appendDot()
        return
    }

    if (key === '()') {
        toggleParenthesis()
        return
    }

    if (arithmeticOperators.has(key)) {
        appendOperator(key)
        return
    }

    if (/^[0-9]$/.test(key)) {
        appendNumber(key)
    }
}

const buildRemarkWithDimensions = () => {
    const parts: string[] = []
    if (selectedProject.value) parts.push(`项目:${selectedProject.value}`)
    if (selectedTag.value) parts.push(`标签:${selectedTag.value}`)
    if (remark.value.trim()) parts.push(remark.value.trim())
    return parts.join(' · ')
}

const handleSave = async () => {
    const amount = parseFloat(amountStr.value)
    if (!amount || amount <= 0) return

    if (activeTab.value === '转账' && selectedAccount.value && selectedTargetAccount.value
        && selectedAccount.value === selectedTargetAccount.value) {
        accountingToastError('转入账户不能与转出账户相同')
        return
    }

    saving.value = true
    try {
        await createRecord(props.bookId, {
            type: activeTab.value,
            amount,
            category_name: selectedCategory.value || '未分类',
            account_name: selectedAccount.value,
            target_account_name: selectedTargetAccount.value,
            payee: payee.value.trim() || undefined,
            remark: buildRemarkWithDimensions(),
            record_time: buildRecordTime(),
        })
        appendOperationLog(
            props.bookId,
            '新增交易',
            `${activeTab.value} · ${formatAccountingMoney(amount)} · ${selectedCategory.value || '未分类'}`,
        )
        accountingToastSuccess('记账成功')
        emit('saved')
    } catch (e) {
        accountingToastError(accountingErrorMessage(e, '保存失败'))
    } finally {
        saving.value = false
    }
}

const systemKeyboardVisible = ref(false)
let fullVisualViewportHeight = 0
let visualViewportFrame: number | undefined

const updateSystemKeyboardVisibility = () => {
    visualViewportFrame = undefined
    const viewport = window.visualViewport
    if (!viewport) return

    fullVisualViewportHeight = Math.max(fullVisualViewportHeight, viewport.height)
    systemKeyboardVisible.value = fullVisualViewportHeight - viewport.height > 120
}

const scheduleSystemKeyboardVisibilityUpdate = () => {
    if (visualViewportFrame !== undefined) {
        window.cancelAnimationFrame(visualViewportFrame)
    }
    visualViewportFrame = window.requestAnimationFrame(updateSystemKeyboardVisibility)
}

const resetVisualViewportBaseline = () => {
    fullVisualViewportHeight = 0
    systemKeyboardVisible.value = false
    scheduleSystemKeyboardVisibilityUpdate()
}

onMounted(async () => {
    const viewport = window.visualViewport
    if (viewport) {
        fullVisualViewportHeight = viewport.height
        viewport.addEventListener('resize', scheduleSystemKeyboardVisibilityUpdate)
    }
    window.addEventListener('orientationchange', resetVisualViewportBaseline)

    initDateTime()
    projects.value = loadNamedItems(props.bookId, 'projects')
    tags.value = loadNamedItems(props.bookId, 'tags')
    merchants.value = loadNamedItems(props.bookId, 'merchants-custom')
    try {
        const [catRes, accRes] = await Promise.all([
            getCategories(props.bookId),
            getAccounts(props.bookId),
        ])
        categories.value = catRes.data
        accounts.value = accRes.data
    } catch {
        // ignore
    }
})

onBeforeUnmount(() => {
    if (visualViewportFrame !== undefined) {
        window.cancelAnimationFrame(visualViewportFrame)
    }
    window.visualViewport?.removeEventListener('resize', scheduleSystemKeyboardVisibilityUpdate)
    window.removeEventListener('orientationchange', resetVisualViewportBaseline)
})

const keyRows = [
    ['C', '÷', '×', '⌫'],
    ['1', '2', '3', '-'],
    ['4', '5', '6', '+'],
    ['7', '8', '9', 'OK_TOP'],
    ['()', '0', '.', 'OK_BOT'],
]
</script>

<template>
  <!-- Full screen overlay (mobile-first, safe areas) -->
  <Teleport to="body">
  <div class="accounting-warm-dialog accounting-record-dialog fixed inset-0 z-[80] flex flex-col bg-theme-primary accounting-fullscreen">
    <!-- Header -->
    <div class="accounting-entry-header flex items-center justify-between px-3 sm:px-4 py-2.5 sm:py-3 safe-top safe-x flex-shrink-0">
      <button
        type="button"
        class="accounting-touch-target inline-flex items-center justify-center rounded-full p-2 -ml-1"
        aria-label="关闭"
        @click="emit('close')"
      >
        <X class="w-5 h-5" />
      </button>
      <span class="font-semibold">记一笔</span>
      <span class="w-10" />
    </div>

    <!-- Scrollable Content -->
    <div class="accounting-entry-sheet flex-1 min-h-0 overflow-auto accounting-scroll safe-x">
      <!-- Type Tabs -->
      <div class="flex px-4 pt-3 gap-2 overflow-x-auto no-scrollbar">
        <button
          v-for="tab in tabs"
          :key="tab"
          type="button"
          @click="activeTab = tab; selectedCategory = ''"
          :class="[
            'px-5 py-2.5 rounded-full text-sm font-medium transition flex-shrink-0 min-h-[40px]',
            activeTab === tab
              ? 'bg-accounting-brand text-white shadow-sm'
              : 'bg-theme-secondary text-theme-secondary'
          ]"
        >
          {{ tab }}
        </button>
      </div>

      <!-- Amount -->
      <div class="px-4 py-3">
        <p :class="['text-3xl sm:text-4xl font-bold tabular-nums break-all leading-tight', moneyTypeTextClass(activeTab)]">
          {{ activeTab === '支出' ? '-' : activeTab === '收入' ? '+' : '' }}{{ amountStr }}
        </p>
      </div>

      <div class="border-t border-theme-secondary" />

      <!-- Categories Grid -->
      <div class="px-4 py-3">
        <div class="grid grid-cols-3 gap-2">
          <button
            v-for="cat in displayCategories"
            :key="cat"
            type="button"
            @click="selectedCategory = cat"
            :class="[
              'py-2.5 rounded-xl text-sm font-medium border transition',
              selectedCategory === cat
                ? 'border-accounting-brand text-accounting-brand bg-theme-secondary'
                : 'border-theme-primary text-theme-secondary hover:bg-theme-secondary'
            ]"
          >
            {{ cat }}
          </button>
          <button
            type="button"
            @click="showCategoryPopup = true"
            class="py-2.5 rounded-xl text-sm font-medium border border-theme-primary text-accounting-brand hover:bg-theme-secondary transition flex items-center justify-center gap-1"
          >
            全部 <ChevronRight class="w-3 h-3" />
          </button>
        </div>
      </div>

      <!-- Category Popup -->
      <div
        v-if="showCategoryPopup"
        class="fixed inset-0 z-[60] bg-black/45 flex items-end justify-center"
        @click.self="showCategoryPopup = false"
      >
        <div class="w-full max-h-[75dvh] bg-theme-elevated rounded-t-3xl shadow-xl p-4 overflow-y-auto accounting-scroll safe-bottom">
          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold text-theme-primary">选择分类</h3>
            <button type="button" class="accounting-touch-target inline-flex items-center justify-center p-2 text-theme-secondary" @click="showCategoryPopup = false">
              <X class="w-5 h-5" />
            </button>
          </div>
          <div class="grid grid-cols-3 gap-2">
            <button
              v-for="cat in allDisplayCategories"
              :key="cat"
              type="button"
              @click="selectedCategory = cat; showCategoryPopup = false"
              :class="[
                'py-2.5 rounded-xl text-sm font-medium border transition',
                selectedCategory === cat
                  ? 'border-accounting-brand text-accounting-brand bg-theme-secondary'
                  : 'border-theme-primary text-theme-secondary hover:bg-theme-secondary'
              ]"
            >
              {{ cat }}
            </button>
          </div>
        </div>
      </div>

      <!-- Account Selector -->
      <div class="px-4 py-2 border-t border-theme-secondary">
        <label class="text-xs text-accounting-brand font-medium">账户</label>
        <select
          v-model="selectedAccount"
          class="accounting-field mt-1"
        >
          <option value="">未指定</option>
          <option v-for="acc in accounts" :key="acc.id" :value="acc.name">
            {{ acc.name }} ({{ acc.type }})
          </option>
        </select>
      </div>

      <!-- Target account (for transfer) -->
      <div v-if="activeTab === '转账'" class="px-4 py-2">
        <label class="text-xs text-accounting-brand font-medium">转入账户</label>
        <select
          v-model="selectedTargetAccount"
          class="accounting-field mt-1"
        >
          <option value="">未指定</option>
          <option v-for="acc in accounts" :key="acc.id" :value="acc.name">
            {{ acc.name }}
          </option>
        </select>
      </div>

      <!-- Payee / merchant -->
      <div v-if="activeTab !== '转账'" class="px-4 py-2 border-t border-theme-secondary">
        <label class="text-xs text-accounting-brand font-medium">商家 / 付款对象</label>
        <input
          v-model="payee"
          type="text"
          list="accounting-merchant-list"
          placeholder="可选，如超市、公司"
          class="accounting-field mt-1"
        />
        <datalist id="accounting-merchant-list">
          <option v-for="m in merchants" :key="m.id" :value="m.name" />
        </datalist>
      </div>

      <!-- Project & tag -->
      <div class="px-4 py-2 grid grid-cols-2 gap-2 border-t border-theme-secondary">
        <div>
          <label class="text-xs text-accounting-brand font-medium">项目</label>
          <select
            v-model="selectedProject"
            class="accounting-field mt-1"
          >
            <option value="">无</option>
            <option v-for="p in projects" :key="p.id" :value="p.name">{{ p.name }}</option>
          </select>
        </div>
        <div>
          <label class="text-xs text-accounting-brand font-medium">标签</label>
          <select
            v-model="selectedTag"
            class="accounting-field mt-1"
          >
            <option value="">无</option>
            <option v-for="t in tags" :key="t.id" :value="t.name">{{ t.name }}</option>
          </select>
        </div>
      </div>

      <!-- Remark -->
      <div class="px-4 py-2 border-t border-theme-secondary">
        <label class="text-xs text-accounting-brand font-medium">备注</label>
        <input
          v-model="remark"
          type="text"
          placeholder="点击添加备注"
          class="accounting-field mt-1"
        />
      </div>

      <!-- Date Time Selector -->
      <div class="px-4 py-2 border-t border-theme-secondary">
        <label class="text-xs text-accounting-brand font-medium">日期时间</label>
        <div class="grid grid-cols-2 gap-2 mt-1">
          <input
            v-model="selectedDate"
            type="date"
            class="accounting-field"
          />
          <input
            v-model="selectedTime"
            type="time"
            class="accounting-field"
          />
        </div>
      </div>
    </div>

    <!-- Calculator Keyboard -->
    <div v-show="!systemKeyboardVisible" class="accounting-entry-keypad bg-theme-elevated border-t border-theme-secondary flex-shrink-0 safe-x safe-bottom">
      <div class="grid grid-cols-4">
        <template v-for="(row, ri) in keyRows" :key="ri">
          <template v-for="key in row" :key="key">
            <!-- OK button spans 2 rows -->
            <button
              v-if="key === 'OK_TOP'"
              type="button"
              @click="handleKeyPress('OK')"
              :disabled="saving"
              class="row-span-2 bg-accounting-brand text-white text-lg font-bold min-h-[96px] transition active:opacity-90 disabled:opacity-50 col-start-4 row-start-4 row-end-6"
              style="grid-row: span 2"
            >
              <Loader2 v-if="saving" class="w-5 h-5 animate-spin mx-auto" />
              <span v-else>{{ actionKeyLabel }}</span>
            </button>
            <button
              v-else-if="key === 'OK_BOT'"
              class="hidden"
            />
            <button
              v-else-if="key === '⌫'"
              type="button"
              @click="handleKeyPress('⌫')"
              class="min-h-[48px] text-lg font-medium text-theme-primary active:bg-theme-secondary transition"
            >
              <Delete class="w-5 h-5 mx-auto" />
            </button>
            <button
              v-else-if="key === 'C'"
              type="button"
              @click="handleKeyPress('C')"
              class="min-h-[48px] text-lg font-medium text-theme-secondary active:bg-theme-secondary transition"
            >
              C
            </button>
            <button
              v-else-if="['÷', '×', '-', '+'].includes(key)"
              type="button"
              @click="handleKeyPress(key)"
              class="min-h-[48px] text-lg font-medium text-theme-secondary active:bg-theme-secondary transition"
            >
              {{ key }}
            </button>
            <button
              v-else-if="key === '()'"
              type="button"
              @click="handleKeyPress(key)"
              class="min-h-[48px] text-lg font-medium text-theme-secondary active:bg-theme-secondary transition"
            >
              ( )
            </button>
            <button
              v-else
              type="button"
              @click="handleKeyPress(key)"
              class="min-h-[48px] text-xl font-medium text-theme-primary active:bg-theme-secondary transition"
            >
              {{ key }}
            </button>
          </template>
        </template>
      </div>
    </div>
  </div>
  </Teleport>
</template>
