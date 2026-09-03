import request from './request'

export interface AliyunTrafficItem {
    billing_item: string
    billing_item_code: string
    region: string
    usage_gb: number
}

export interface AliyunTrafficSummary {
    billing_cycle: string
    quota_gb: number
    used_gb: number
    remaining_gb: number
    overage_gb: number
    usage_percent: number
    queried_at: string
    items: AliyunTrafficItem[]
}

export const getAliyunTraffic = () =>
    request.get<AliyunTrafficSummary>('/admin/aliyun-traffic')
