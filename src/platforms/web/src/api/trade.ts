import request from '@/api/request'

export interface TradeAccount {
    id: number
    name: string
    broker: string
    cash_balance: number
    total_assets: number
    market_value: number
    position_ratio_percent: number
    today_pnl: number
    unrealized_pnl: number
    accumulated_pnl: number
    commission_rate: number
    min_commission: number
    stamp_duty_rate: number
    transfer_fee_rate: number
    notes?: string
    positions_count: number
    created_at?: string
}

export interface TradePosition {
    id: number
    account_id: number
    stock_code: string
    stock_name: string
    quantity: number
    cost_price: number
    accumulated_pnl: number
    current_price: number
    change: number
    percent: number
    market_value: number
    cost_amount: number
    unrealized_pnl: number
    unrealized_pnl_percent: number
    today_pnl: number
    weight_percent?: number
    updated_at?: string
}

export interface AssetDistributionItem {
    label: string
    category: 'cash' | 'stock'
    amount: number
    ratio_percent: number
}

export interface PortfolioSummary {
    total_assets: number
    total_market_value: number
    total_cash: number
    total_today_pnl: number
    total_unrealized_pnl: number
    total_accumulated_pnl: number
    position_ratio_percent: number
    accounts_count: number
    positions_count: number
    asset_distribution: AssetDistributionItem[]
}

export interface TradeOrder {
    id: number
    account_id: number
    stock_code: string
    stock_name: string
    trade_type: 'buy' | 'sell'
    price: number
    quantity: number
    amount: number
    commission: number
    stamp_duty: number
    transfer_fee: number
    total_fee: number
    net_amount: number
    realized_pnl: number
    cost_price_after: number
    holding_after: number
    notes?: string
    transacted_at?: string
}

export interface TradeCashFlow {
    id: number
    flow_type: 'deposit' | 'withdraw' | 'trade_buy' | 'trade_sell' | 'dividend'
    amount: number
    balance_after: number
    notes?: string
    transacted_at?: string
}

export interface SimulationResult {
    stock_code: string
    stock_name: string
    price: number
    simulated_quantity: number
    simulated_lots: number
    trade_amount: number
    fees: {
        commission: number
        stamp_duty: number
        transfer_fee: number
        total_fee: number
    }
    total_required: number
    current_cash: number
    is_sufficient: boolean
    cash_shortage: number
    diluted_cost_price: number
    new_quantity: number
    new_stock_market_value: number
    new_total_assets: number
    position_ratio_percent: number
    transfer_suggestions: Array<{
        account_id: number
        name: string
        available_cash: number
        can_cover_fully: boolean
    }>
}

export const getTradeAccounts = () => request.get<TradeAccount[]>('/trade/accounts')
export const createTradeAccount = (data: Partial<TradeAccount> & { initial_cash?: number }) =>
    request.post<{ success: boolean; id: number }>('/trade/accounts', data)
export const updateTradeAccount = (id: number, data: Partial<TradeAccount>) =>
    request.put<{ success: boolean }>('/trade/accounts/' + id, data)
export const deleteTradeAccount = (id: number) =>
    request.delete<{ success: boolean }>('/trade/accounts/' + id)

export const addCashFlow = (accountId: number, data: { flow_type: 'deposit' | 'withdraw'; amount: number; notes?: string }) =>
    request.post<{ success: boolean; flow_id: number; balance_after: number }>('/trade/accounts/' + accountId + '/cash-flow', data)
export const getCashFlows = (accountId: number) =>
    request.get<TradeCashFlow[]>('/trade/accounts/' + accountId + '/cash-flows')

export const getAccountPositions = (accountId: number) =>
    request.get<TradePosition[]>('/trade/accounts/' + accountId + '/positions')

export const getPortfolioSummary = () =>
    request.get<PortfolioSummary>('/trade/summary')

export const createTradeOrder = (data: {
    account_id: number
    stock_code: string
    stock_name: string
    trade_type: 'buy' | 'sell'
    price: number
    quantity: number
    custom_commission?: number
    custom_stamp_duty?: number
    custom_transfer_fee?: number
    notes?: string
}) => request.post<{
    success: boolean
    order_id: number
    trade_type: string
    net_amount: number
    total_fee: number
    realized_pnl: number
    holding_after: number
    cost_price_after: number
}>('/trade/orders', data)

export const getTradeOrders = (params?: { account_id?: number; stock_code?: string; limit?: number }) =>
    request.get<TradeOrder[]>('/trade/orders', { params })

export const simulateOrder = (data: {
    account_id: number
    stock_code: string
    stock_name: string
    price: number
    target_amount?: number
    quantity?: number
}) => request.post<SimulationResult>('/trade/simulate', data)
