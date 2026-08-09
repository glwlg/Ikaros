import request from './request'

export interface SkillInfo {
    name: string
    description: string
    source: 'builtin' | 'learned'
    enabled: boolean
    triggers: string[]
    ikaros_only: boolean
}

export interface SkillsListResponse {
    skills: SkillInfo[]
}

export interface SkillEnabledResponse {
    name: string
    enabled: boolean
}

export const getSkills = () =>
    request.get<SkillsListResponse>('/skills')

export const setSkillEnabled = (name: string, enabled: boolean) =>
    request.patch<SkillEnabledResponse>(`/skills/${encodeURIComponent(name)}/enabled`, { enabled })

export interface SkillDetail extends SkillInfo {
    scripts: string[]
    content: string
}

export const getSkillDetail = (name: string) =>
    request.get<SkillDetail>(`/skills/${encodeURIComponent(name)}/detail`)

export const deleteSkill = (name: string) =>
    request.delete<{ name: string; deleted: boolean }>(`/skills/${encodeURIComponent(name)}`)

export interface SkillCreatePayload {
    name: string
    description: string
    triggers: string[]
    content: string
}

export const createSkill = (payload: SkillCreatePayload) =>
    request.post<SkillInfo>('/skills', payload)

export const importSkill = (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return request.post<SkillInfo>('/skills/import', form)
}
