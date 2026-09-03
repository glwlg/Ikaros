<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref } from 'vue'
import { Ban, CheckCircle2, Loader2, PencilLine, Plus, RefreshCw, Trash2, TriangleAlert, X } from 'lucide-vue-next'

import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import { createUser, deleteUser, listUsers, updateUser } from '@/api/admin'
import type { UserInfo } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const users = ref<UserInfo[]>([])
const loading = ref(false)
const creating = ref(false)
const showCreate = ref(false)
const formError = ref('')
const listError = ref('')
const successText = ref('')
const form = ref({
    email: '',
    password: '',
    display_name: '',
    username: '',
    role: 'viewer',
})

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

const normalizedUsers = computed(() => {
    const rows = [...users.value]
    const current = authStore.user
    if (current && !rows.some(item => item.id === current.id)) {
        rows.unshift(current)
    }
    return rows
})

const totalCount = computed(() => normalizedUsers.value.length)
const adminCount = computed(() => normalizedUsers.value.filter(item => item.role === 'admin').length)
const activeCount = computed(() => normalizedUsers.value.filter(item => item.is_active).length)
const disabledCount = computed(() => normalizedUsers.value.filter(item => !item.is_active).length)

const userInitials = (user: UserInfo) => {
    const source = (user.display_name || user.username || user.email || '?').trim()
    const ascii = source.replace(/[^A-Za-z0-9]/g, '')
    if (ascii.length >= 2) return ascii.slice(0, 2).toUpperCase()
    return source.slice(0, 1).toUpperCase()
}

const formatLastLogin = (value: string | null) => {
    if (!value) return '—'
    const time = new Date(value).getTime()
    if (Number.isNaN(time)) return value
    const minutes = Math.floor((Date.now() - time) / 60000)
    if (minutes < 1) return '刚刚'
    if (minutes < 60) return `${minutes} 分钟前`
    const hours = Math.floor(minutes / 60)
    if (hours < 24) return `${hours} 小时前`
    const days = Math.floor(hours / 24)
    if (days < 30) return `${days} 天前`
    return value.slice(0, 10)
}

const normalizeCreatePayload = () => {
    const payload = {
        email: form.value.email.trim(),
        password: form.value.password,
        role: form.value.role,
        username: form.value.username.trim() || undefined,
        display_name: form.value.display_name.trim() || undefined,
    }
    return payload
}

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
        const response = await listUsers()
        users.value = Array.isArray(response.data) ? response.data : []
    } catch (error) {
        listError.value = parseErrorMessage(error, '用户列表加载失败')
    } finally {
        loading.value = false
    }
}

const submit = async () => {
    formError.value = ''
    successText.value = ''
    const payload = normalizeCreatePayload()
    if (!payload.email.includes('.') || !payload.email.includes('@')) {
        formError.value = '邮箱格式不正确，请使用类似 name@example.com 的地址。'
        return
    }
    creating.value = true
    try {
        await createUser(payload)
        form.value = {
            email: '',
            password: '',
            display_name: '',
            username: '',
            role: 'viewer',
        }
        successText.value = '用户已创建'
        await load()
    } catch (error) {
        formError.value = parseErrorMessage(error, '创建用户失败')
    } finally {
        creating.value = false
    }
}

const cycleRole = async (user: UserInfo) => {
    const order: Array<UserInfo['role']> = ['viewer', 'operator', 'admin']
    const nextRole = order[(order.indexOf(user.role) + 1) % order.length]
    await updateUser(user.id, { role: nextRole })
    await load()
}

const toggleActive = async (user: UserInfo) => {
    await updateUser(user.id, { is_active: !user.is_active })
    await load()
}

const removeUser = async (user: UserInfo) => {
    if (!confirm(`确定要删除用户 "${user.display_name || user.username || user.email}" 吗？此操作不可撤销。`)) {
        return
    }
    try {
        await deleteUser(user.id)
        await load()
    } catch (error) {
        listError.value = parseErrorMessage(error, '删除用户失败')
    }
}

onMounted(load)
</script>

<template>
  <div class="ikaros-page users-page">
    <header class="ikaros-page-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Admin · Users</p>
        <h1 class="ikaros-page-title">用户与权限</h1>
        <p class="ikaros-page-description">管理控制台账号、角色与启用状态；账号只能由管理员创建，不开放公开注册。</p>
      </div>
      <div class="users-actions">
        <button type="button" class="users-icon-action" title="刷新列表" :disabled="loading" @click="load">
          <RefreshCw :class="{ 'is-spinning': loading }" />
        </button>
        <button type="button" class="ikaros-primary-action" @click="showCreate = true">
          <Plus />
          创建用户
        </button>
      </div>
    </header>

    <LiquidGlass :radius="20" :optics="compactOptics" class="users-metrics">
      <div class="users-metrics-inner">
        <div class="users-metric">
          <span>用户总数</span>
          <strong>{{ totalCount }}</strong>
        </div>
        <i class="users-metric-divider" aria-hidden="true" />
        <div class="users-metric">
          <span>管理员</span>
          <strong>{{ adminCount }}</strong>
        </div>
        <i class="users-metric-divider" aria-hidden="true" />
        <div class="users-metric">
          <span>已启用</span>
          <strong class="is-green">{{ activeCount }}</strong>
        </div>
        <i class="users-metric-divider" aria-hidden="true" />
        <div class="users-metric">
          <span>已停用</span>
          <strong class="is-red">{{ disabledCount }}</strong>
        </div>
      </div>
    </LiquidGlass>

    <LiquidGlass :radius="24" :optics="panelOptics" class="users-directory">
      <div class="directory-shell">
        <div class="directory-toolbar">
          <h2>Directory</h2>
          <span class="directory-count">{{ totalCount }} 个账号</span>
        </div>

        <div v-if="loading" class="directory-loading">
          <Loader2 class="is-spinning" />
          正在加载用户
        </div>

        <div v-else-if="listError" class="directory-error">{{ listError }}</div>

        <div v-else class="directory-table-wrap">
          <table>
            <thead>
              <tr>
                <th>用户</th>
                <th>邮箱</th>
                <th>角色</th>
                <th>状态</th>
                <th>最近活动</th>
                <th><span class="sr-only">操作</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="user in normalizedUsers" :key="user.id">
                <td>
                  <div class="user-cell">
                    <span class="user-avatar" :class="`role-${user.role}`">{{ userInitials(user) }}</span>
                    <div class="user-meta">
                      <strong>
                        {{ user.display_name || user.username || user.email }}
                        <em v-if="authStore.user?.id === user.id" class="current-badge">当前用户</em>
                      </strong>
                      <span v-if="user.username">@{{ user.username }}</span>
                    </div>
                  </div>
                </td>
                <td class="user-email">{{ user.email }}</td>
                <td>
                  <span class="role-chip" :class="`role-${user.role}`">{{ user.role }}</span>
                </td>
                <td>
                  <span class="status-chip" :class="user.is_active ? 'is-active' : 'is-disabled'">
                    {{ user.is_active ? 'active' : 'disabled' }}
                  </span>
                </td>
                <td class="user-activity">{{ formatLastLogin(user.last_login_at) }}</td>
                <td>
                  <div class="row-actions">
                    <button type="button" class="row-action" title="切换角色" @click="cycleRole(user)">
                      <PencilLine />
                    </button>
                    <button
                      type="button"
                      class="row-action"
                      :title="user.is_active ? '停用' : '启用'"
                      @click="toggleActive(user)"
                    >
                      <Ban v-if="user.is_active" />
                      <CheckCircle2 v-else />
                    </button>
                    <button
                      type="button"
                      class="row-action is-danger"
                      :title="authStore.user?.id === user.id ? '不能删除当前登录账号' : '删除'"
                      :disabled="authStore.user?.id === user.id"
                      @click="removeUser(user)"
                    >
                      <Trash2 />
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>

          <div v-if="!normalizedUsers.length" class="directory-empty">
            <TriangleAlert />
            当前没有可展示的用户数据。
          </div>
        </div>

        <footer class="directory-footer">
          <CheckCircle2 />
          当前登录账号：<strong>{{ authStore.user?.display_name || authStore.user?.email || '未知用户' }}</strong>
        </footer>
      </div>
    </LiquidGlass>

    <div v-if="showCreate" class="drawer-backdrop" @click.self="showCreate = false">
      <aside class="drawer-card ikaros-surface ikaros-surface-strong">
        <header class="drawer-head">
          <h3>创建用户</h3>
          <button type="button" class="drawer-close" title="关闭" @click="showCreate = false">
            <X />
          </button>
        </header>
        <form class="drawer-body" @submit.prevent="submit">
          <label>
            显示名称
            <input v-model="form.display_name" type="text" placeholder="例如：Ops_Lee">
          </label>
          <label>
            用户名<span class="label-hint">（选填）</span>
            <input v-model="form.username" type="text" placeholder="例如：ops_lee">
          </label>
          <label>
            邮箱
            <input v-model="form.email" type="email" required placeholder="name@example.com">
          </label>
          <div class="role-field">
            <span class="role-field-label">角色分配</span>
            <div class="role-options">
              <label class="role-option" :class="{ selected: form.role === 'viewer' }">
                <input v-model="form.role" type="radio" value="viewer">
                <strong>Viewer</strong>
                <span>只读访问，无法执行敏感操作</span>
              </label>
              <label class="role-option" :class="{ selected: form.role === 'operator' }">
                <input v-model="form.role" type="radio" value="operator">
                <strong>Operator</strong>
                <span>日常操作权限，可管理普通资源</span>
              </label>
              <label class="role-option" :class="{ selected: form.role === 'admin' }">
                <input v-model="form.role" type="radio" value="admin">
                <strong>Admin</strong>
                <span>系统全局管理，分配权限</span>
              </label>
            </div>
          </div>
          <label>
            临时密码
            <input v-model="form.password" type="password" required minlength="8" placeholder="最小长度 8 个字符">
            <small>最小长度 8 个字符，请提醒用户首次登录后修改。</small>
          </label>

          <div v-if="formError" class="drawer-error">{{ formError }}</div>
          <div v-if="successText" class="drawer-success">{{ successText }}</div>

          <footer class="drawer-actions">
            <button type="button" class="ikaros-secondary-action" :disabled="creating" @click="showCreate = false">取消</button>
            <button type="submit" class="ikaros-primary-action" :disabled="creating">
              <Loader2 v-if="creating" class="is-spinning" />
              {{ creating ? '创建中' : '创建' }}
            </button>
          </footer>
        </form>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.users-page {
  gap: 22px;
}

.users-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 10px;
}

.users-actions :is(.ikaros-primary-action, .ikaros-secondary-action) svg {
  width: 16px;
  height: 16px;
}

.users-icon-action {
  display: grid;
  width: 40px;
  height: 40px;
  flex: none;
  place-items: center;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.4);
  color: var(--ikaros-copy);
  cursor: pointer;
  transition: border-color 160ms ease, color 160ms ease;
}

:global(.dark) .users-icon-action { background: rgba(255, 255, 255, 0.06); }
.users-icon-action:hover:not(:disabled) { border-color: rgba(232, 93, 142, 0.35); color: var(--ikaros-pink); }
.users-icon-action:disabled { cursor: not-allowed; opacity: 0.55; }
.users-icon-action svg { width: 16px; height: 16px; }

.is-spinning { animation: users-spin 850ms linear infinite; }

.users-metrics {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.8);
}

:global(.dark) .users-metrics { --ikaros-glass-fill: rgba(43, 34, 40, 0.82); }

.users-metrics-inner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 22px;
  padding: 16px 24px;
}

.users-metric {
  display: grid;
  gap: 3px;
}

.users-metric span {
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
}

.users-metric strong {
  color: var(--ikaros-ink);
  font-size: 21px;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.users-metric strong.is-green { color: var(--ikaros-rind); }
.users-metric strong.is-red { color: #c63741; }

.users-metric-divider {
  width: 1px;
  height: 30px;
  background: var(--ikaros-line);
}

.users-directory {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .users-directory { --ikaros-glass-fill: rgba(43, 34, 40, 0.86); }

.directory-shell {
  padding: 20px;
}

.directory-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.directory-toolbar h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.directory-count {
  display: inline-flex;
  min-height: 24px;
  align-items: center;
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.5);
  padding: 0 10px;
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
}

:global(.dark) .directory-count { background: rgba(255, 255, 255, 0.06); }

.directory-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  padding: 16px 4px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.directory-loading svg { width: 16px; height: 16px; }

.directory-error {
  margin-top: 16px;
  border: 1px solid rgba(198, 55, 65, 0.2);
  border-radius: 12px;
  background: rgba(198, 55, 65, 0.07);
  padding: 12px 14px;
  color: #c63741;
  font-size: 12px;
  font-weight: 650;
}

.directory-table-wrap {
  margin-top: 16px;
  overflow-x: auto;
}

.directory-table-wrap table {
  width: 100%;
  min-width: 720px;
  border-collapse: collapse;
}

.directory-table-wrap th {
  border-bottom: 0.5px solid var(--ikaros-glass-hairline);
  padding: 9px 12px;
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-align: left;
  text-transform: uppercase;
}

.directory-table-wrap td {
  border-bottom: 0.5px solid var(--ikaros-glass-hairline);
  padding: 12px;
  color: var(--ikaros-copy);
  font-size: 12px;
  vertical-align: middle;
}

.directory-table-wrap tbody tr:last-child td { border-bottom: 0; }

.user-cell {
  display: flex;
  align-items: center;
  gap: 11px;
  min-width: 0;
}

.user-avatar {
  display: grid;
  width: 36px;
  height: 36px;
  flex: none;
  place-items: center;
  border-radius: 50%;
  background: rgba(232, 93, 142, 0.12);
  color: var(--ikaros-pink-dark);
  font-size: 12px;
  font-weight: 800;
  letter-spacing: 0.02em;
}

.user-avatar.role-operator { background: rgba(23, 19, 26, 0.08); color: var(--ikaros-ink); }
:global(.dark) .user-avatar.role-operator { background: rgba(255, 255, 255, 0.1); }
.user-avatar.role-viewer { background: rgba(23, 19, 26, 0.05); color: var(--ikaros-muted); }
:global(.dark) .user-avatar.role-viewer { background: rgba(255, 255, 255, 0.06); }
:global(.dark) .user-avatar.role-admin { color: #f3a1c1; }

.user-meta {
  display: grid;
  gap: 2px;
  min-width: 0;
}

.user-meta strong {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 750;
}

.user-meta > span {
  color: var(--ikaros-muted);
  font-size: 11px;
}

.current-badge {
  display: inline-flex;
  min-height: 18px;
  align-items: center;
  border-radius: 999px;
  background: rgba(42, 140, 138, 0.1);
  padding: 0 8px;
  color: var(--ikaros-eye);
  font-size: 10.5px;
  font-style: normal;
  font-weight: 700;
}

.user-email {
  overflow-wrap: anywhere;
}

.role-chip {
  display: inline-flex;
  min-height: 22px;
  align-items: center;
  border-radius: 999px;
  padding: 0 10px;
  font-size: 11px;
  font-weight: 700;
}

.role-chip.role-admin { background: rgba(232, 93, 142, 0.1); color: var(--ikaros-pink-dark); }
:global(.dark) .role-chip.role-admin { color: #f3a1c1; }
.role-chip.role-operator { background: rgba(23, 19, 26, 0.07); color: var(--ikaros-ink); }
:global(.dark) .role-chip.role-operator { background: rgba(255, 255, 255, 0.08); }
.role-chip.role-viewer { background: rgba(23, 19, 26, 0.04); color: var(--ikaros-muted); }
:global(.dark) .role-chip.role-viewer { background: rgba(255, 255, 255, 0.05); }

.status-chip {
  display: inline-flex;
  min-height: 22px;
  align-items: center;
  border-radius: 999px;
  padding: 0 10px;
  font-size: 11px;
  font-weight: 700;
}

.status-chip.is-active { background: rgba(47, 125, 74, 0.1); color: var(--ikaros-rind); }
.status-chip.is-disabled { background: rgba(23, 19, 26, 0.06); color: var(--ikaros-muted); }
:global(.dark) .status-chip.is-disabled { background: rgba(255, 255, 255, 0.07); }

.user-activity {
  color: var(--ikaros-muted);
  white-space: nowrap;
}

.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 6px;
}

.row-action {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid var(--ikaros-line);
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.4);
  color: var(--ikaros-copy);
  cursor: pointer;
  transition: border-color 160ms ease, color 160ms ease, background 160ms ease;
}

:global(.dark) .row-action { background: rgba(255, 255, 255, 0.06); }
.row-action:hover:not(:disabled) { border-color: rgba(232, 93, 142, 0.35); color: var(--ikaros-pink); }
.row-action.is-danger:hover:not(:disabled) { border-color: rgba(198, 55, 65, 0.4); background: rgba(198, 55, 65, 0.08); color: #c63741; }
.row-action:disabled { cursor: not-allowed; opacity: 0.45; }
.row-action svg { width: 14px; height: 14px; }

.directory-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 16px;
  border: 1px dashed var(--ikaros-line);
  border-radius: 12px;
  padding: 30px 16px;
  color: var(--ikaros-muted);
  font-size: 12px;
}

.directory-empty svg { width: 16px; height: 16px; }

.directory-footer {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
  border: 1px solid rgba(42, 140, 138, 0.2);
  border-radius: 11px;
  background: rgba(42, 140, 138, 0.07);
  color: var(--ikaros-eye);
  padding: 10px 13px;
  font-size: 12px;
}

.directory-footer svg { width: 15px; height: 15px; flex: none; }
.directory-footer strong { font-weight: 750; }

.drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  justify-content: flex-end;
  background: rgba(23, 19, 26, 0.3);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.drawer-card {
  display: grid;
  width: min(430px, 100%);
  height: 100%;
  grid-template-rows: auto minmax(0, 1fr);
  overflow: hidden;
  border-radius: 20px 0 0 20px;
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  border-bottom: 1px solid var(--ikaros-line);
  padding: 18px 22px;
}

.drawer-head h3 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 17px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.drawer-close {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--ikaros-muted);
  cursor: pointer;
}

.drawer-close:hover { background: rgba(232, 93, 142, 0.1); color: var(--ikaros-pink); }
.drawer-close svg { width: 16px; height: 16px; }

.drawer-body {
  display: grid;
  align-content: start;
  gap: 15px;
  overflow-y: auto;
  padding: 20px 22px;
}

.drawer-body label {
  display: grid;
  gap: 7px;
  color: var(--ikaros-ink);
  font-size: 12px;
  font-weight: 750;
}

.label-hint {
  color: var(--ikaros-muted);
  font-weight: 500;
}

.drawer-body input {
  width: 100%;
  border: 1px solid var(--ikaros-line);
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.55);
  padding: 10px 13px;
  color: var(--ikaros-ink);
  font-family: inherit;
  font-size: 13px;
  font-weight: 400;
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

:global(.dark) .drawer-body input { background: rgba(255, 255, 255, 0.06); }

.drawer-body input:focus {
  border-color: rgba(232, 93, 142, 0.45);
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.1);
}

.drawer-body small {
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 500;
  line-height: 1.5;
}

.role-field {
  display: grid;
  gap: 8px;
}

.role-field-label {
  color: var(--ikaros-ink);
  font-size: 12px;
  font-weight: 750;
}

.role-options {
  display: grid;
  gap: 8px;
}

.role-option {
  position: relative;
  display: grid;
  gap: 3px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.42);
  padding: 11px 13px;
  cursor: pointer;
  transition: border-color 160ms ease, background 160ms ease;
}

:global(.dark) .role-option { background: rgba(255, 255, 255, 0.05); }

.role-option input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.role-option strong {
  color: var(--ikaros-ink);
  font-size: 12px;
  font-weight: 800;
}

.role-option span {
  color: var(--ikaros-muted);
  font-size: 11px;
  line-height: 1.5;
}

.role-option.selected {
  border-color: rgba(232, 93, 142, 0.45);
  background: rgba(232, 93, 142, 0.07);
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.08);
}

.drawer-error {
  border: 1px solid rgba(198, 55, 65, 0.2);
  border-radius: 12px;
  background: rgba(198, 55, 65, 0.07);
  padding: 11px 13px;
  color: #c63741;
  font-size: 12px;
  font-weight: 650;
}

.drawer-success {
  border: 1px solid rgba(47, 125, 74, 0.22);
  border-radius: 12px;
  background: rgba(47, 125, 74, 0.08);
  padding: 11px 13px;
  color: var(--ikaros-rind);
  font-size: 12px;
  font-weight: 650;
}

.drawer-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  border-top: 1px solid var(--ikaros-line);
  padding-top: 16px;
}

@keyframes users-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 720px) {
  .users-metric-divider { display: none; }

  .drawer-card {
    width: 100%;
    border-radius: 0;
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning { animation: none; }
}
</style>
