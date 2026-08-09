import request from './request'

export interface ModelsQuickRoleSnapshot {
    configured: boolean
    ready: boolean
    role: string
    model_key: string
    provider_name: string
    base_url: string
    api_key: string
    headers: Record<string, string>
    api_style: string
    model_id: string
    display_name: string
    reasoning: boolean
    input_types: string[]
}

export interface ModelsSnapshot {
    quick_roles: {
        primary: ModelsQuickRoleSnapshot
        routing: ModelsQuickRoleSnapshot
    }
    status: {
        primary_ready: boolean
        routing_ready: boolean
    }
    models_config: {
        path: string
        exists: boolean
        payload: Record<string, unknown>
    }
}

export interface ModelsPatchPayload {
    models_config: Record<string, unknown>
}

export interface ModelsPatchResponse {
    snapshot: ModelsSnapshot
}

export type ModelsLatencyRole = 'primary' | 'routing' | 'vision' | 'image_generation' | 'voice'

export interface ModelsLatencyCheckPayload {
    role: ModelsLatencyRole
    provider_name: string
    base_url?: string
    api_key?: string
    headers?: Record<string, string>
    api_style?: string
    model_id: string
}

export interface ModelsLatencyCheckResponse {
    role: ModelsLatencyRole
    model_key: string
    elapsed_ms: number
    response_preview: string
    prompt: string
}

export interface ModelsProviderFetchPayload {
    base_url: string
    api_key?: string
    headers?: Record<string, string>
}

export interface ProviderFetchedModel {
    id: string
    name: string
    /** 以下字段为 null/空 表示 Provider 未上报，保持手动配置 */
    input: string[] | null
    reasoning: boolean | null
    reasoningEffort: string | null
    reasoningEfforts: string[]
    contextWindow: number | null
    maxTokens: number | null
}

export interface ModelsProviderFetchResponse {
    base_url: string
    total: number
    models: ProviderFetchedModel[]
}

export const getModelsSnapshot = () =>
    request.get<ModelsSnapshot>('/admin/models')

export const patchModelsSnapshot = (payload: ModelsPatchPayload) =>
    request.patch<ModelsPatchResponse>('/admin/models', payload)

export const postModelsLatencyCheck = (payload: ModelsLatencyCheckPayload) =>
    request.post<ModelsLatencyCheckResponse>('/admin/models/latency-check', payload)

export const postModelsProviderFetch = (payload: ModelsProviderFetchPayload) =>
    request.post<ModelsProviderFetchResponse>('/admin/models/fetch-provider-models', payload)
