import request from './request'

export interface ChannelToolPolicy {
    allow: string[]
    deny: string[]
}

export interface ChannelUserItem {
    platform: string
    user_id: string
    status: string
    role: string
    remark: string
    access: Record<string, boolean>
    tool_policy: ChannelToolPolicy | null
}

export interface ChannelUserListResponse {
    items: ChannelUserItem[]
    feature_labels: Record<string, string>
    group_catalog: Record<string, string>
}

const userUrl = (platform: string, userId: string) =>
    `/admin/channel-access/users/${encodeURIComponent(platform)}/${encodeURIComponent(userId)}`

export const getChannelUsers = () =>
    request.get<ChannelUserListResponse>('/admin/channel-access/users')

export const updateChannelUserAccess = (
    platform: string,
    userId: string,
    access: Record<string, boolean>,
) => request.put<ChannelUserItem>(`${userUrl(platform, userId)}/access`, { access })

export const updateChannelUserRemark = (
    platform: string,
    userId: string,
    remark: string,
) => request.put<ChannelUserItem>(`${userUrl(platform, userId)}/remark`, { remark })

export const updateChannelUserToolPolicy = (
    platform: string,
    userId: string,
    allow: string[],
) =>
    request.put<{ tool_policy: ChannelToolPolicy }>(`${userUrl(platform, userId)}/tool-policy`, {
        allow,
        deny: [],
    })

export const deleteChannelUserToolPolicy = (platform: string, userId: string) =>
    request.delete<{ tool_policy: null }>(`${userUrl(platform, userId)}/tool-policy`)
