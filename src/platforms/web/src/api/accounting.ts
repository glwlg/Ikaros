import request from './request'

export interface Book {
    id: number
    name: string
}

export interface BookUpdatePayload {
    name: string
}

export interface RecordItem {
    id: number
    type: string
    amount: number
    category: string
    account: string
    target_account: string
    payee: string
    remark: string
    record_time: string
    is_large_expense?: boolean
    exclude_from_budget?: boolean
}

export interface AccountItem {
    id: number
    name: string
    type: string
    initial_balance: number
    balance: number
    include_in_assets: boolean
    book_id?: number
    aliases?: string[]
    trade_account_id?: number | null
}

export interface BalanceTrendItem {
    date: string
    balance: number
}

export type BalanceTrendScope =
    | 'net'
    | 'assets'
    | 'liabilities'
    | 'account_type'
    | 'account'

export interface AccountChangeItem {
    account_id: number
    account_name: string
    account_type: string
    start_balance: number
    end_balance: number
    change: number
    income: number
    expense: number
}

export interface ScopedBalanceTrendItem {
    period: string
    period_start: string
    period_end: string
    balance: number
    change: number
    income: number
    expense: number
    account_changes?: AccountChangeItem[]
}

export interface CategoryItem {
    id: number
    name: string
    type: string
    parent_id: number | null
}

export interface MonthlySummary {
    income: number
    expense: number
    balance: number
}

export interface AutoRecordFromImageResult {
    ok: boolean
    message: string
    book_id: number
    record_id: number
}

export interface DailySummaryItem {
    date: string
    income: number
    expense: number
}

export interface CategorySummaryItem {
    category: string
    amount: number
}

export interface YearlySummaryItem {
    year: string
    income: number
    expense: number
}

export interface PeriodSummaryItem {
    period: string
    income: number
    expense: number
    income_count?: number
    expense_count?: number
}

export interface StatsOverview {
    days: number
    transactions: number
    net_assets: number
}

export interface Budget {
    id: number
    month: string
    period_key?: string
    budget_type?: string
    monthly_provision?: number
    pool_name?: string
    total_amount: number
    category_id: number | null
    category_name: string | null
}

export interface DualTrackRoutineCategory {
    category_id: number
    category_name: string
    budget_amount: number
    spent_amount: number
    remaining_amount: number
    usage_percent: number
}

export interface DualTrackSummary {
    month: string
    year: string
    routine_budget: {
        budget_amount: number
        spent_amount: number
        remaining_amount: number
        usage_percent: number
        categories: DualTrackRoutineCategory[]
    }
    annual_pool: {
        pool_name: string
        annual_budget_limit: number
        monthly_provision: number
        accumulated_provision: number
        spent_total: number
        current_balance: number
        usage_percent: number
        records: RecordItem[]
    }
}

// ─── Books ──────────────────────────────────────────────────────────
export const getBooks = () =>
    request.get<Book[]>('/accounting/books')

export const createBook = (name: string) =>
    request.post<Book>('/accounting/books', { name })

export const updateBook = (bookId: number, data: BookUpdatePayload) =>
    request.put<Book>(`/accounting/books/${bookId}`, data)

export const deleteBook = (bookId: number) =>
    request.delete<{ message: string }>(`/accounting/books/${bookId}`)

// ─── Records ────────────────────────────────────────────────────────
export const getRecords = (
    bookId: number,
    limit: number = 50,
    keyword?: string,
    start_date?: string,
    end_date?: string,
    type?: string,
    category?: string,
    account?: string,
    offset: number = 0,
    is_large_expense?: boolean,
    min_amount?: number,
    max_amount?: number,
) =>
    request.get<RecordItem[]>('/accounting/records', {
        params: {
            book_id: bookId,
            limit,
            offset,
            keyword,
            start_date,
            end_date,
            type,
            category,
            account,
            is_large_expense,
            min_amount,
            max_amount,
        },
    })

export const createRecord = (bookId: number, data: {
    type: string
    amount: number
    category_name?: string
    account_name?: string
    target_account_name?: string
    payee?: string
    remark?: string
    record_time?: string
    is_large_expense?: boolean
    exclude_from_budget?: boolean
}) =>
    request.post('/accounting/records', data, { params: { book_id: bookId } })

export const autoCreateRecordFromImage = (
    bookId: number,
    image: File,
    note: string = '',
) => {
    const formData = new FormData()
    formData.append('image', image)
    if (note.trim()) {
        formData.append('note', note.trim())
    }
    return request.post<AutoRecordFromImageResult>('/accounting/records/auto-from-image', formData, {
        params: { book_id: bookId },
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 150000,
    })
}

export const getRecordDetail = (bookId: number, recordId: number) =>
    request.get<RecordItem>(`/accounting/records/${recordId}`, {
        params: { book_id: bookId }
    })

export const updateRecord = (bookId: number, recordId: number, data: {
    type?: string
    amount?: number
    category_name?: string
    account_name?: string
    target_account_name?: string
    payee?: string
    remark?: string
    record_time?: string
    is_large_expense?: boolean
    exclude_from_budget?: boolean
}) =>
    request.put<{ message: string; record: RecordItem }>(`/accounting/records/${recordId}`, data, {
        params: { book_id: bookId }
    })

export const deleteRecord = (bookId: number, recordId: number) =>
    request.delete<{ message: string }>(`/accounting/records/${recordId}`, {
        params: { book_id: bookId }
    })

export const batchUpdateLargeExpense = (bookId: number, data: {
    record_ids?: number[]
    is_large_expense: boolean
    category_names?: string[]
    min_amount?: number
    year?: number
}) =>
    request.post<{ message: string; updated_count: number }>('/accounting/records/batch-large-expense', data, {
        params: { book_id: bookId }
    })
// ─── Statistics ─────────────────────────────────────────────────────
export const getRecordsSummary = (bookId: number, year: number, month: number) =>
    request.get<MonthlySummary>('/accounting/records/summary', { params: { book_id: bookId, year, month } })

export const getDailySummary = (bookId: number, year: number, month: number) =>
    request.get<DailySummaryItem[]>('/accounting/records/daily-summary', { params: { book_id: bookId, year, month } })

export const getCategorySummary = (bookId: number, year: number, month: number, type: string = '支出') =>
    request.get<CategorySummaryItem[]>('/accounting/records/category-summary', { params: { book_id: bookId, year, month, type } })

export const getCategorySummaryByRange = (
    bookId: number,
    start_date: string,
    end_date: string,
    type: string = '支出',
    category: string = '',
) =>
    request.get<CategorySummaryItem[]>('/accounting/records/category-summary-range', {
        params: { book_id: bookId, start_date, end_date, type, category }
    })

export const getRangeSummary = (
    bookId: number,
    start_date: string,
    end_date: string,
    granularity: 'day' | 'week' | 'month' | 'quarter' | 'year' = 'month',
    category: string = '',
) =>
    request.get<PeriodSummaryItem[]>('/accounting/records/range-summary', {
        params: { book_id: bookId, start_date, end_date, granularity, category }
    })

export const getBalanceTrend = (
    bookId: number,
    start_date: string,
    end_date: string,
    granularity: 'day' | 'week' | 'month' | 'quarter' | 'year' = 'month',
    scope: BalanceTrendScope = 'net',
    account_type: string = '',
    account_id?: number,
) =>
    request.get<ScopedBalanceTrendItem[]>('/accounting/balance-trend', {
        params: {
            book_id: bookId,
            start_date,
            end_date,
            granularity,
            scope,
            account_type: account_type || undefined,
            account_id,
        }
    })

export const getYearlySummary = (bookId: number) =>
    request.get<YearlySummaryItem[]>('/accounting/records/yearly-summary', { params: { book_id: bookId } })

// ─── Accounts ───────────────────────────────────────────────────────
export const getAccounts = (bookId: number) =>
    request.get<AccountItem[]>('/accounting/accounts', { params: { book_id: bookId } })

export const createAccount = (bookId: number, data: { name: string; type: string; balance: number; include_in_assets?: boolean }) =>
    request.post<AccountItem>('/accounting/accounts', data, { params: { book_id: bookId } })

export const updateAccount = (accountId: number, data: { name?: string; type?: string; balance?: number; include_in_assets?: boolean }) =>
    request.put<AccountItem>(`/accounting/accounts/${accountId}`, data)

export const deleteAccount = (accountId: number) =>
    request.delete(`/accounting/accounts/${accountId}`)

export const bindTradeAccount = (accountId: number, tradeAccountId: number | null) =>
    request.post<{ success: boolean }>(`/accounting/accounts/${accountId}/bind-trade-account`, {
        trade_account_id: tradeAccountId,
    })

export const syncTradeAsset = (accountId: number) =>
    request.post<{
        account_id: number
        account_name: string
        trade_account_name: string
        previous_balance: number
        target_assets: number
        diff: number
        record_id: number | null
        record_type: string | null
        new_balance: number
    }>(`/accounting/accounts/${accountId}/sync-trade-asset`)

export const mergeAccount = (accountId: number, targetAccountId: number) =>
    request.post<{ message: string; account: AccountItem }>(`/accounting/accounts/${accountId}/merge`, {
        target_account_id: targetAccountId,
    })

export const getAccountDetail = (accountId: number) =>
    request.get<AccountItem>(`/accounting/accounts/${accountId}`)

export const getAccountRecords = (accountId: number, limit: number = 50) =>
    request.get<RecordItem[]>(`/accounting/accounts/${accountId}/records`, { params: { limit } })

export const getAccountBalanceTrend = (accountId: number, days: number = 30) =>
    request.get<BalanceTrendItem[]>(`/accounting/accounts/${accountId}/balance-trend`, { params: { days } })

export const adjustAccountBalance = (accountId: number, data: { target_balance: number; method: string }) =>
    request.post(`/accounting/accounts/${accountId}/adjust-balance`, data)

// ─── Categories ─────────────────────────────────────────────────────
export const getCategories = (bookId: number) =>
    request.get<CategoryItem[]>('/accounting/categories', { params: { book_id: bookId } })

export const createCategory = (bookId: number, data: {
    name: string
    type: string
    parent_id?: number | null
}) =>
    request.post<CategoryItem>('/accounting/categories', data, {
        params: { book_id: bookId }
    })

export const updateCategory = (bookId: number, categoryId: number, data: {
    name?: string
    type?: string
    parent_id?: number | null
}) =>
    request.put<CategoryItem>(`/accounting/categories/${categoryId}`, data, {
        params: { book_id: bookId }
    })

export const deleteCategory = (bookId: number, categoryId: number) =>
    request.delete<{ message: string }>(`/accounting/categories/${categoryId}`, {
        params: { book_id: bookId }
    })

// ─── Stats Overview ─────────────────────────────────────────────────
export const getStatsOverview = (bookId: number) =>
    request.get<StatsOverview>('/accounting/stats/overview', { params: { book_id: bookId } })

// ─── Budgets ────────────────────────────────────────────────────────
export const getBudgets = (bookId: number, month?: string, periodKey?: string, budgetType?: string) =>
    request.get<Budget[]>('/accounting/budgets', { params: { book_id: bookId, month, period_key: periodKey, budget_type: budgetType } })

export const getDualTrackSummary = (bookId: number, year: number, month: number) =>
    request.get<DualTrackSummary>('/accounting/budgets/dual-track-summary', { params: { book_id: bookId, year, month } })

export const createOrUpdateBudget = (bookId: number, data: {
    month?: string
    period_key?: string
    budget_type?: string
    monthly_provision?: number
    pool_name?: string
    total_amount: number
    category_id?: number | null
}) =>
    request.post('/accounting/budgets', data, { params: { book_id: bookId } })

// ─── CSV Import ─────────────────────────────────────────────────────
export const importCsv = (bookId: number, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return request.post('/accounting/import/csv', formData, {
        params: { book_id: bookId },
        headers: { 'Content-Type': 'multipart/form-data' },
    })
}

export const exportRecordsCsv = (bookId: number) =>
    request.get<Blob>('/accounting/export/csv', {
        params: { book_id: bookId },
        responseType: 'blob',
    })

export interface Debt {
    id: number
    type: string
    contact: string
    total_amount: number
    remaining_amount: number
    due_date: string | null
    remark: string
    is_settled: boolean
    created_at: string
}

export interface ScheduledTask {
    id: number
    name: string
    frequency: string
    next_run: string
    type: string
    amount: number
    account_name: string | null
    target_account_name: string | null
    category_name: string | null
    payee: string | null
    remark: string | null
    is_active: boolean
    creator_id: number
}

// ─── Debts ──────────────────────────────────────────────────────────
export const getDebts = (bookId: number, type?: string, is_settled?: boolean) =>
    request.get<Debt[]>('/accounting/debts', { params: { book_id: bookId, type, is_settled } })

export const createDebt = (bookId: number, data: { type: string, contact: string, amount: number, due_date?: string, remark?: string }) =>
    request.post<{id: number, message: string}>('/accounting/debts', data, { params: { book_id: bookId } })

export const repayDebt = (bookId: number, debtId: number, data: { amount: number }) =>
    request.post<{message: string, remaining_amount: number, is_settled: boolean}>(`/accounting/debts/${debtId}/repay`, data, { params: { book_id: bookId } })

// ─── Scheduled Tasks ────────────────────────────────────────────────
export const getScheduledTasks = (bookId: number) =>
    request.get<ScheduledTask[]>('/accounting/scheduled-tasks', { params: { book_id: bookId } })

export const createScheduledTask = (bookId: number, data: {
    name: string
    frequency: string
    next_run: string
    type: string
    amount: number
    account_id?: number
    target_account_id?: number
    category_id?: number
    payee?: string
    remark?: string
}) =>
    request.post<{id: number, message: string}>('/accounting/scheduled-tasks', data, { params: { book_id: bookId } })

export const deleteScheduledTask = (bookId: number, taskId: number) =>
    request.delete<{message: string}>(`/accounting/scheduled-tasks/${taskId}`, { params: { book_id: bookId } })
