export type SubscriptionStatus = 'active' | 'renewal_due' | 'expired'

export interface SubscriptionRecord {
    id: number
    name: string
    category: string
    provider: string
    cost: string
    start_date: string
    cycle_months: number
    expiry_date: string
    reminder_enabled: boolean
    reminder_days_before: number
    reminder_date: string
    delivery_platform: string
    delivery_configured: boolean
    notes: string
    last_reminded_at: string
    days_remaining: number
    status: SubscriptionStatus
    created_at: string
    updated_at: string
}

export interface SubscriptionPayload {
    name: string
    category: string
    provider: string
    cost: string
    start_date: string
    cycle_months: number
    expiry_date: string
    reminder_enabled: boolean
    reminder_days_before: number
    delivery_platform?: string
    notes: string
}
