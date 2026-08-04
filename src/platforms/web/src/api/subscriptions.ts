import request from './request'
import type { SubscriptionPayload, SubscriptionRecord } from '@/types/subscription'

const BASE_URL = '/subscriptions'

export function listSubscriptions() {
    return request.get<SubscriptionRecord[]>(BASE_URL)
}

export function createSubscription(data: SubscriptionPayload) {
    return request.post<SubscriptionRecord>(BASE_URL, data)
}

export function updateSubscription(id: number, data: SubscriptionPayload) {
    return request.put<SubscriptionRecord>(`${BASE_URL}/${id}`, data)
}

export function deleteSubscription(id: number) {
    return request.delete<{ success: boolean }>(`${BASE_URL}/${id}`)
}
