<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref } from 'vue'
import {
    Boxes,
    Info,
    Loader2,
    PencilLine,
    RefreshCw,
    SlidersHorizontal,
    TriangleAlert,
    UserCog,
} from 'lucide-vue-next'

import {
    deleteChannelUserToolPolicy,
    getChannelUsers,
    updateChannelUserAccess,
    updateChannelUserRemark,
    updateChannelUserToolPolicy,
} from '@/api/channel-access'
import type { ChannelUserItem } from '@/api/channel-access'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'

const panelOptics = {
    mapSize: 256,
    strength: 0.06,
    depth: 0.72,
    dispersion: 0.46,
    frost: 4,
    saturate: 1.22,
    specular: 1.15,
    glow: 0.22,
    sheen: 0.78,
    curvature: 0.38,
    bend: 0.62,
}

const compactOptics = {
    mapSize: 256,
    strength: 0.11,
    depth: 0.9,
    dispersion: 0.58,
    frost: 3,
    saturate: 1.26,
    specular: 1.25,
    glow: 0.3,
    sheen: 1.05,
    curvature: 0.48,
    bend: 0.7,
}

const users = ref<ChannelUserItem[]>([])
const featureLabels = ref<Record<string, string>>({})
const groupCatalog = ref<Record<string, string>>({})
const loading = ref(false)
const listError = ref('')
const actionError = ref('')
const successText = ref('')
const savingKey = ref('')
const editingKey = ref('')
const editSelection = ref<string[]>([])
const remarkEditingKey = ref('')
const remarkDraft = ref('')

const featureKeys = computed(() => Object.keys(featureLabels.value))
const groupKeys = computed(() => Object.keys(groupCatalog.value).filter(key => key !== 'group:all'))
const customPolicyCount = computed(() => users.value.filter(user => user.tool_policy).length)

const userKey = (user: ChannelUserItem) => user.platform + ':' + user.user_id

const parseErrorMessage = (error: unknown, fallback: string) => {
    if (axios.isAxiosError(error)) {
        const detail = error.response?.data?.detail
        if (Array.isArray(detail) && detail.length > 0) {
            return String(detail[0]?.msg || fallback)
        }
        if (typeof detail === 'string' && detail.trim()) {
            return detail
        }
    }
    return fallback
}

const load = async () => {
    loading.value = true
    listError.value = ''
    try {
        const response = await getChannelUsers()
        users.value = Array.isArray(response.data?.items) ? response.data.items : []
        featureLabels.value = response.data?.feature_labels || {}
        groupCatalog.value = response.data?.group_catalog || {}
    } catch (error) {
        listError.value = parseErrorMessage(error, '渠道用户加载失败')
    } finally {
        loading.value = false
    }
}

const toggleFeature = async (user: ChannelUserItem, feature: string) => {
    actionError.value = ''
    successText.value = ''
    const next = { ...user.access, [feature]: !user.access[feature] }
    savingKey.value = userKey(user)
    try {
        const response = await updateChannelUserAccess(user.platform, user.user_id, next)
        user.access = response.data?.access || next
    } catch (error) {
        actionError.value = parseErrorMessage(error, '功能开关保存失败')
    } finally {
        savingKey.value = ''
    }
}

const openEditor = (user: ChannelUserItem) => {
    actionError.value = ''
    successText.value = ''
    if (editingKey.value === userKey(user)) {
        editingKey.value = ''
        return
    }
    editingKey.value = userKey(user)
    editSelection.value = user.tool_policy ? [...user.tool_policy.allow] : []
}

const toggleGroup = (group: string) => {
    if (editSelection.value.includes(group)) {
        editSelection.value = editSelection.value.filter(item => item !== group)
    } else {
        editSelection.value = [...editSelection.value, group]
    }
}

const openRemarkEditor = (user: ChannelUserItem) => {
    actionError.value = ''
    successText.value = ''
    remarkEditingKey.value = userKey(user)
    remarkDraft.value = user.remark || ''
}

const saveRemark = async (user: ChannelUserItem) => {
    actionError.value = ''
    successText.value = ''
    savingKey.value = userKey(user)
    try {
        const response = await updateChannelUserRemark(user.platform, user.user_id, remarkDraft.value.trim())
        user.remark = response.data?.remark || ''
        remarkEditingKey.value = ''
        successText.value = '备注已保存'
    } catch (error) {
        actionError.value = parseErrorMessage(error, '备注保存失败')
    } finally {
        savingKey.value = ''
    }
}

const savePolicy = async (user: ChannelUserItem) => {
    actionError.value = ''
    successText.value = ''
    savingKey.value = userKey(user)
    try {
        if (!editSelection.value.length) {
            if (user.tool_policy) {
                await deleteChannelUserToolPolicy(user.platform, user.user_id)
            }
            successText.value = '已恢复为跟随全局策略'
        } else {
            await updateChannelUserToolPolicy(user.platform, user.user_id, editSelection.value)
            successText.value = '工具白名单已保存'
        }
        editingKey.value = ''
        await load()
    } catch (error) {
        actionError.value = parseErrorMessage(error, '工具策略保存失败')
    } finally {
        savingKey.value = ''
    }
}

const clearPolicy = async (user: ChannelUserItem) => {
    if (!confirm('确定要清除该用户的自定义工具策略吗？清除后将跟随全局策略（全部放行）。')) {
        return
    }
    actionError.value = ''
    successText.value = ''
    savingKey.value = userKey(user)
    try {
        await deleteChannelUserToolPolicy(user.platform, user.user_id)
        editingKey.value = ''
        successText.value = '已恢复为跟随全局策略'
        await load()
    } catch (error) {
        actionError.value = parseErrorMessage(error, '清除工具策略失败')
    } finally {
        savingKey.value = ''
    }
}

onMounted(load)
</script>

<template>
  <div class="ikaros-page channel-access-page">
    <header class="ikaros-page-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Channel Access</p>
        <h1 class="ikaros-page-title">渠道权限</h1>
        <p class="ikaros-page-description">
          管理来自微信等渠道的用户能使用的功能入口与 AI 工具范围。
        </p>
      </div>
      <div class="channel-access-header-actions">
        <button type="button" class="ikaros-secondary-action" :disabled="loading" @click="load">
          <RefreshCw :class="{ 'is-spinning': loading }" />
          刷新
        </button>
      </div>
    </header>

    <section class="channel-access-stats" aria-label="渠道权限概览">
      <LiquidGlass :radius="20" :optics="compactOptics" class="channel-access-stat">
        <div class="channel-access-stat-inner">
          <span class="channel-access-stat-icon"><UserCog /></span>
          <div class="channel-access-stat-copy">
            <span>渠道用户</span>
            <strong>{{ users.length }}</strong>
          </div>
        </div>
      </LiquidGlass>
      <LiquidGlass :radius="20" :optics="compactOptics" class="channel-access-stat">
        <div class="channel-access-stat-inner">
          <span class="channel-access-stat-icon"><SlidersHorizontal /></span>
          <div class="channel-access-stat-copy">
            <span>自定义工具策略</span>
            <strong>{{ customPolicyCount }}</strong>
          </div>
        </div>
      </LiquidGlass>
      <LiquidGlass :radius="20" :optics="compactOptics" class="channel-access-stat">
        <div class="channel-access-stat-inner">
          <span class="channel-access-stat-icon"><Boxes /></span>
          <div class="channel-access-stat-copy">
            <span>可用工具组</span>
            <strong>{{ groupKeys.length }}</strong>
          </div>
        </div>
      </LiquidGlass>
    </section>

    <div class="channel-access-layout">
      <LiquidGlass :radius="22" :optics="panelOptics" class="channel-access-guide">
        <div class="channel-access-guide-shell">
          <header class="channel-access-guide-head">
            <span class="channel-access-guide-icon"><Info /></span>
            <h2>权限说明</h2>
          </header>
          <div class="channel-access-guide-body">
            <p>
              <strong>功能开关</strong>：控制聊天、定时任务等业务入口，关闭后对应功能对该用户不可用。
            </p>
            <p>
              <strong>工具白名单</strong>：控制 AI 在处理该用户消息时能调用哪些工具组。未设置时跟随全局策略（全部放行）；一旦设置，只有勾选的组可用，其余一律拒绝。
            </p>
            <p class="channel-access-guide-example">
              例如只勾选 group:media 和 group:delivery，对方就只能在聊天里下载、分析视频并接收结果文件，无法让 AI 读取服务器上的其他文件。
            </p>
          </div>
        </div>
      </LiquidGlass>

      <LiquidGlass :radius="22" :optics="panelOptics" class="channel-access-table-panel">
        <div class="channel-access-table-shell">
          <header class="channel-access-table-head">
            <div class="channel-access-table-title">
              <h2>渠道用户列表</h2>
              <p>按用户控制功能开关与工具白名单</p>
            </div>
            <span class="channel-access-count-chip">{{ users.length }} 人</span>
          </header>

          <div v-if="loading" class="channel-access-loading">
            <Loader2 class="is-spinning" />
            正在加载渠道用户
          </div>

          <div v-else-if="listError" class="channel-access-note is-error">
            {{ listError }}
          </div>

          <template v-else>
            <div v-if="actionError" class="channel-access-note is-error">
              {{ actionError }}
            </div>
            <div v-if="successText" class="channel-access-note is-success">
              {{ successText }}
            </div>

            <div class="channel-access-table-wrap">
              <table class="channel-access-table">
                <thead>
                  <tr>
                    <th>用户</th>
                    <th>功能开关</th>
                    <th>工具策略</th>
                  </tr>
                </thead>
                <tbody>
                  <template v-for="user in users" :key="userKey(user)">
                    <tr :class="{ 'is-editing': editingKey === userKey(user) }">
                      <td>
                        <div class="channel-access-user">
                          <span class="channel-access-avatar"><UserCog /></span>
                          <div v-if="remarkEditingKey === userKey(user)" class="channel-access-remark-edit">
                            <input
                              v-model="remarkDraft"
                              type="text"
                              maxlength="64"
                              class="channel-access-remark-input"
                              placeholder="输入备注，例如：张三"
                              @keyup.enter="saveRemark(user)"
                            >
                            <button
                              type="button"
                              class="channel-access-remark-save"
                              :disabled="savingKey === userKey(user)"
                              @click="saveRemark(user)"
                            >
                              保存
                            </button>
                            <button
                              type="button"
                              class="channel-access-remark-cancel"
                              @click="remarkEditingKey = ''"
                            >
                              取消
                            </button>
                          </div>
                          <div v-else class="channel-access-user-copy">
                            <div class="channel-access-user-name">
                              <span>{{ user.remark || '未备注' }}</span>
                              <button
                                type="button"
                                title="编辑备注"
                                @click="openRemarkEditor(user)"
                              >
                                <PencilLine />
                              </button>
                            </div>
                            <span class="channel-access-user-platform">{{ user.platform }}</span>
                            <span class="channel-access-user-id" :title="user.user_id">{{ user.user_id }}</span>
                          </div>
                        </div>
                      </td>
                      <td>
                        <div class="channel-access-features">
                          <button
                            v-for="feature in featureKeys"
                            :key="feature"
                            type="button"
                            class="channel-access-feature"
                            :class="{ 'is-on': user.access[feature] }"
                            :disabled="savingKey === userKey(user)"
                            @click="toggleFeature(user, feature)"
                          >
                            {{ featureLabels[feature] || feature }}
                          </button>
                        </div>
                      </td>
                      <td>
                        <div class="channel-access-policy">
                          <template v-if="user.tool_policy">
                            <span
                              v-for="group in user.tool_policy.allow"
                              :key="group"
                              class="channel-access-policy-group"
                            >
                              {{ group }}
                            </span>
                          </template>
                          <span v-else class="channel-access-policy-global">
                            跟随全局（全部放行）
                          </span>
                          <button
                            type="button"
                            class="channel-access-policy-edit"
                            :class="{ 'is-open': editingKey === userKey(user) }"
                            @click="openEditor(user)"
                          >
                            <SlidersHorizontal />
                            {{ editingKey === userKey(user) ? '收起' : '配置工具权限' }}
                          </button>
                        </div>
                      </td>
                    </tr>
                    <tr v-if="editingKey === userKey(user)" class="channel-access-editor-row">
                      <td colspan="3">
                        <div class="channel-access-editor">
                          <div class="channel-access-editor-main">
                            <h3>工具白名单</h3>
                            <p>
                              只勾选要放行的工具组，其余对该用户一律拒绝；一个都不勾则视为清除自定义策略、恢复跟随全局。
                            </p>
                            <div class="channel-access-groups">
                              <label
                                v-for="group in groupKeys"
                                :key="group"
                                class="channel-access-group"
                                :class="{ 'is-checked': editSelection.includes(group) }"
                              >
                                <input
                                  type="checkbox"
                                  :checked="editSelection.includes(group)"
                                  @change="toggleGroup(group)"
                                >
                                <span class="channel-access-group-copy">
                                  <strong>{{ group }}</strong>
                                  <small>{{ groupCatalog[group] }}</small>
                                </span>
                              </label>
                            </div>
                          </div>
                          <div class="channel-access-editor-actions">
                            <button
                              type="button"
                              class="ikaros-primary-action channel-access-save"
                              :disabled="savingKey === userKey(user)"
                              @click="savePolicy(user)"
                            >
                              <Loader2 v-if="savingKey === userKey(user)" class="is-spinning" />
                              保存
                            </button>
                            <button
                              type="button"
                              class="channel-access-cancel"
                              @click="editingKey = ''"
                            >
                              取消
                            </button>
                            <button
                              v-if="user.tool_policy"
                              type="button"
                              class="channel-access-clear"
                              :disabled="savingKey === userKey(user)"
                              @click="clearPolicy(user)"
                            >
                              清除自定义策略
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  </template>
                </tbody>
              </table>

              <div v-if="!users.length" class="channel-access-empty">
                <TriangleAlert />
                <div>还没有渠道用户。用户第一次在微信等渠道发消息后会自动出现在这里。</div>
              </div>
            </div>
          </template>
        </div>
      </LiquidGlass>
    </div>
  </div>
</template>

<style scoped>
.channel-access-page {
  gap: 20px;
}

.channel-access-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.channel-access-header-actions svg {
  width: 15px;
  height: 15px;
}

.channel-access-stats {
  display: grid;
  gap: 14px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.channel-access-stat {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.8);
}

:global(.dark) .channel-access-stat {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.82);
}

.channel-access-stat-inner {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 16px 18px;
}

.channel-access-stat-icon {
  display: grid;
  width: 38px;
  height: 38px;
  flex: none;
  place-items: center;
  border: 1px solid rgba(232, 93, 142, 0.2);
  border-radius: 13px;
  background: rgba(232, 93, 142, 0.09);
  color: var(--ikaros-pink);
}

.channel-access-stat-icon svg {
  width: 18px;
  height: 18px;
}

.channel-access-stat-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.channel-access-stat-copy span {
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
}

.channel-access-stat-copy strong {
  color: var(--ikaros-ink);
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.channel-access-layout {
  display: grid;
  min-width: 0;
  gap: 20px;
  align-items: start;
}

.channel-access-guide,
.channel-access-table-panel {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) :is(.channel-access-guide, .channel-access-table-panel) {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.86);
}

.channel-access-guide-shell {
  display: grid;
  gap: 14px;
  padding: 20px;
}

.channel-access-guide-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.channel-access-guide-head h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.channel-access-guide-icon {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid rgba(232, 93, 142, 0.2);
  border-radius: 11px;
  background: rgba(232, 93, 142, 0.09);
  color: var(--ikaros-pink);
}

.channel-access-guide-icon svg {
  width: 16px;
  height: 16px;
}

.channel-access-guide-body {
  display: grid;
  gap: 10px;
  color: var(--ikaros-copy);
  font-size: 12px;
  line-height: 1.7;
}

.channel-access-guide-body p {
  margin: 0;
}

.channel-access-guide-body strong {
  color: var(--ikaros-ink);
  font-weight: 750;
}

.channel-access-guide-example {
  padding: 11px 13px;
  border: 1px solid rgba(200, 120, 32, 0.2);
  border-radius: 12px;
  background: rgba(200, 120, 32, 0.08);
  color: #b86717;
}

:global(.dark) .channel-access-guide-example {
  color: #e0a354;
}

.channel-access-table-shell {
  display: grid;
  gap: 16px;
  padding: 20px;
}

.channel-access-table-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.channel-access-table-title h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.channel-access-table-title p {
  margin: 3px 0 0;
  color: var(--ikaros-muted);
  font-size: 11px;
}

.channel-access-count-chip {
  flex: none;
  padding: 5px 10px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: var(--panel-muted);
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 700;
}

.channel-access-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 2px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.channel-access-loading svg {
  width: 16px;
  height: 16px;
}

.channel-access-note {
  padding: 11px 14px;
  border: 1px solid;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.5;
}

.channel-access-note.is-error {
  border-color: rgba(198, 55, 65, 0.18);
  background: rgba(198, 55, 65, 0.07);
  color: #c63741;
}

.channel-access-note.is-success {
  border-color: rgba(47, 125, 74, 0.2);
  background: rgba(47, 125, 74, 0.08);
  color: var(--ikaros-rind);
}

.channel-access-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--ikaros-line);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.32);
}

:global(.dark) .channel-access-table-wrap {
  background: rgba(255, 255, 255, 0.03);
}

.channel-access-table {
  width: 100%;
  min-width: 640px;
  font-size: 13px;
}

.channel-access-table thead {
  background: rgba(255, 255, 255, 0.38);
}

:global(.dark) .channel-access-table thead {
  background: rgba(255, 255, 255, 0.045);
}

.channel-access-table th {
  padding: 11px 16px;
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0.06em;
  text-align: left;
}

.channel-access-table td {
  padding: 13px 16px;
  border-top: 1px solid var(--ikaros-line);
  color: var(--ikaros-ink);
  vertical-align: top;
}

.channel-access-table tbody tr {
  transition: background-color 160ms ease;
}

.channel-access-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.3);
}

:global(.dark) .channel-access-table tbody tr:hover {
  background: rgba(255, 255, 255, 0.03);
}

.channel-access-table tbody tr.is-editing {
  background: rgba(232, 93, 142, 0.05);
  box-shadow: inset 3px 0 0 var(--ikaros-pink);
}

.channel-access-user {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 11px;
}

.channel-access-avatar {
  display: grid;
  width: 38px;
  height: 38px;
  flex: none;
  place-items: center;
  border: 1px solid rgba(232, 93, 142, 0.18);
  border-radius: 13px;
  background: rgba(232, 93, 142, 0.08);
  color: var(--ikaros-pink);
}

.channel-access-avatar svg {
  width: 17px;
  height: 17px;
}

.channel-access-user-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.channel-access-user-name {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--ikaros-ink);
  font-weight: 700;
}

.channel-access-user-name button {
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--ikaros-muted);
  transition: color 160ms ease, background-color 160ms ease;
}

.channel-access-user-name button:hover {
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.channel-access-user-name button svg {
  width: 13px;
  height: 13px;
}

.channel-access-user-platform {
  color: var(--ikaros-copy);
  font-size: 11px;
}

.channel-access-user-id {
  max-width: 240px;
  overflow: hidden;
  color: var(--ikaros-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.channel-access-remark-edit {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  gap: 8px;
}

.channel-access-remark-input {
  width: 170px;
  min-width: 0;
  padding: 8px 11px;
  border: 1px solid var(--ikaros-line);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.55);
  color: var(--ikaros-ink);
  font-size: 12px;
  outline: none;
}

:global(.dark) .channel-access-remark-input {
  background: rgba(255, 255, 255, 0.06);
}

.channel-access-remark-input:focus {
  border-color: rgba(232, 93, 142, 0.45);
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.12);
}

.channel-access-remark-save,
.channel-access-remark-cancel {
  flex: none;
  padding: 7px 11px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 700;
}

.channel-access-remark-save {
  border: 1px solid transparent;
  background: var(--ikaros-pink);
  color: #fff;
}

.channel-access-remark-save:hover {
  background: var(--ikaros-pink-dark);
}

.channel-access-remark-save:disabled {
  cursor: wait;
  opacity: 0.7;
}

.channel-access-remark-cancel {
  border: 1px solid var(--ikaros-line);
  background: rgba(255, 255, 255, 0.45);
  color: var(--ikaros-copy);
}

:global(.dark) .channel-access-remark-cancel {
  background: rgba(255, 255, 255, 0.06);
}

.channel-access-features {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.channel-access-feature {
  padding: 6px 11px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: var(--panel-muted);
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
  transition: border-color 160ms ease, color 160ms ease, background-color 160ms ease;
}

.channel-access-feature:hover {
  border-color: rgba(42, 140, 138, 0.3);
}

.channel-access-feature.is-on {
  border-color: rgba(42, 140, 138, 0.26);
  background: rgba(42, 140, 138, 0.1);
  color: var(--ikaros-eye);
}

.channel-access-feature:disabled {
  cursor: wait;
  opacity: 0.65;
}

.channel-access-policy {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
}

.channel-access-policy-group {
  padding: 5px 9px;
  border: 1px solid rgba(232, 93, 142, 0.22);
  border-radius: 8px;
  background: rgba(232, 93, 142, 0.08);
  color: var(--ikaros-pink);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 10px;
  font-weight: 700;
}

.channel-access-policy-global {
  padding: 5px 9px;
  border: 1px solid var(--ikaros-line);
  border-radius: 8px;
  background: var(--panel-muted);
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 650;
}

.channel-access-policy-edit {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 11px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.45);
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 700;
  transition: border-color 160ms ease, color 160ms ease, background-color 160ms ease;
}

:global(.dark) .channel-access-policy-edit {
  background: rgba(255, 255, 255, 0.06);
}

.channel-access-policy-edit:hover,
.channel-access-policy-edit.is-open {
  border-color: rgba(232, 93, 142, 0.34);
  background: rgba(232, 93, 142, 0.08);
  color: var(--ikaros-pink);
}

.channel-access-policy-edit svg {
  width: 12px;
  height: 12px;
}

.channel-access-editor-row > td {
  padding: 0;
  background: rgba(255, 255, 255, 0.34);
  box-shadow: inset 3px 0 0 var(--ikaros-pink);
}

:global(.dark) .channel-access-editor-row > td {
  background: rgba(255, 255, 255, 0.035);
}

.channel-access-editor {
  display: grid;
  gap: 18px;
  padding: 18px;
}

.channel-access-editor-main {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.channel-access-editor-main h3 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 800;
}

.channel-access-editor-main > p {
  margin: 0;
  color: var(--ikaros-pink);
  font-size: 11px;
  font-weight: 650;
  line-height: 1.6;
}

.channel-access-groups {
  display: grid;
  gap: 8px;
}

.channel-access-group {
  display: flex;
  align-items: flex-start;
  gap: 9px;
  padding: 10px 12px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.35);
  cursor: pointer;
  transition: border-color 160ms ease, background-color 160ms ease;
}

:global(.dark) .channel-access-group {
  background: rgba(255, 255, 255, 0.04);
}

.channel-access-group:hover {
  border-color: rgba(232, 93, 142, 0.3);
}

.channel-access-group.is-checked {
  border-color: rgba(232, 93, 142, 0.4);
  background: rgba(232, 93, 142, 0.07);
}

.channel-access-group input {
  width: 15px;
  height: 15px;
  margin-top: 2px;
  accent-color: var(--ikaros-pink);
}

.channel-access-group-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.channel-access-group-copy strong {
  color: var(--ikaros-ink);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  font-weight: 750;
}

.channel-access-group-copy small {
  color: var(--ikaros-muted);
  font-size: 11px;
  line-height: 1.5;
}

.channel-access-editor-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-content: start;
}

.channel-access-save {
  border: 0;
  cursor: pointer;
}

.channel-access-save:disabled {
  cursor: wait;
  opacity: 0.7;
}

.channel-access-save svg {
  width: 13px;
  height: 13px;
}

.channel-access-cancel {
  padding: 0 16px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.45);
  color: var(--ikaros-copy);
  font-size: 13px;
  font-weight: 700;
  min-height: 40px;
}

:global(.dark) .channel-access-cancel {
  background: rgba(255, 255, 255, 0.06);
}

.channel-access-cancel:hover {
  border-color: rgba(232, 93, 142, 0.3);
  color: var(--ikaros-pink);
}

.channel-access-clear {
  min-height: 40px;
  padding: 0 16px;
  border: 1px solid rgba(198, 55, 65, 0.22);
  border-radius: 12px;
  background: rgba(198, 55, 65, 0.06);
  color: #c63741;
  font-size: 13px;
  font-weight: 700;
}

.channel-access-clear:hover {
  background: rgba(198, 55, 65, 0.1);
}

.channel-access-clear:disabled {
  cursor: wait;
  opacity: 0.7;
}

.channel-access-empty {
  display: flex;
  min-height: 180px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  color: var(--ikaros-muted);
  font-size: 13px;
  text-align: center;
}

.channel-access-empty svg {
  width: 22px;
  height: 22px;
}

.is-spinning {
  animation: channel-access-spin 850ms linear infinite;
}

@keyframes channel-access-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (min-width: 1100px) {
  .channel-access-layout {
    grid-template-columns: 330px minmax(0, 1fr);
  }

  .channel-access-groups {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .channel-access-editor {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .channel-access-editor-actions {
    width: 168px;
    flex-direction: column;
  }

  .channel-access-editor-actions > * {
    width: 100%;
    justify-content: center;
  }
}

@media (max-width: 860px) {
  .channel-access-stats {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning {
    animation: none;
  }
}
</style>
