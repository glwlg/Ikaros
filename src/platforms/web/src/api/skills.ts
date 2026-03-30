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