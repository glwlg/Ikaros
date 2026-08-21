<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref } from 'vue'
import { Loader2, PencilLine, RefreshCw, ShieldCheck, SlidersHorizontal, TriangleAlert, UserCog } from 'lucide-vue-next'

import {
    deleteChannelUserToolPolicy,
    getChannelUsers,
    updateChannelUserAccess,
    updateChannelUserRemark,
    updateChannelUserToolPolicy,
} from '@/api/channel-access'
import type { ChannelUserItem } from '@/api/channel-access'

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
  <div class="grid gap-6 p-6 md:grid-cols-[380px_minmax(0,1fr)] md:p-8">
    <section class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex items-center gap-3">
        <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-cyan-100 text-cyan-700">
          <ShieldCheck class="h-5 w-5" />
        </div>
        <div>
          <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Channel Access</div>
          <h2 class="text-xl font-semibold text-slate-900">渠道权限说明</h2>
        </div>
      </div>

      <div class="mt-4 space-y-3 text-sm leading-7 text-slate-500">
        <p>这里管理来自微信等渠道的用户能使用的功能与 AI 工具。</p>
        <p><span class="font-medium text-slate-700">功能开关</span>：控制聊天、定时任务等业务入口，关闭后对应功能对该用户不可用。</p>
        <p><span class="font-medium text-slate-700">工具白名单</span>：控制 AI 在处理该用户消息时能调用哪些工具组。未设置时跟随全局策略（全部放行）；一旦设置，只有勾选的组可用，其余一律拒绝。</p>
        <p class="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-amber-800">
          例如只勾选 group:media 和 group:delivery，对方就只能在聊天里下载、分析视频并接收结果文件，无法让 AI 读取服务器上的其他文件。
        </p>
      </div>
    </section>

    <section class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
      <div class="flex items-center justify-between">
        <div>
          <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Channel Users</div>
          <h2 class="text-xl font-semibold text-slate-900">渠道用户列表</h2>
        </div>
        <button class="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100" @click="load">
          <RefreshCw class="h-4 w-4" />
          刷新
        </button>
      </div>

      <div v-if="loading" class="mt-6 flex items-center gap-2 text-sm text-slate-500">
        <Loader2 class="h-4 w-4 animate-spin" />
        正在加载渠道用户
      </div>

      <div v-else-if="listError" class="mt-6 rounded-[24px] border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
        {{ listError }}
      </div>

      <template v-else>
        <div v-if="actionError" class="mt-6 rounded-[24px] border border-rose-200 bg-rose-50 p-4 text-sm text-rose-700">
          {{ actionError }}
        </div>
        <div v-if="successText" class="mt-6 rounded-[24px] border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-700">
          {{ successText }}
        </div>

        <div class="mt-6 overflow-x-auto rounded-[24px] border border-slate-200">
          <table class="min-w-full divide-y divide-slate-200 text-sm">
            <thead class="bg-slate-50 text-left text-slate-500">
              <tr>
                <th class="px-4 py-3 font-medium">用户</th>
                <th class="px-4 py-3 font-medium">功能开关</th>
                <th class="px-4 py-3 font-medium">工具策略</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-100 bg-white">
              <template v-for="user in users" :key="userKey(user)">
                <tr>
                  <td class="px-4 py-4">
                    <div class="flex items-center gap-3">
                      <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-slate-100 text-slate-700">
                        <UserCog class="h-4 w-4" />
                      </div>
                      <div v-if="remarkEditingKey === userKey(user)" class="flex items-center gap-2">
                        <input
                          v-model="remarkDraft"
                          type="text"
                          maxlength="64"
                          class="w-44 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm outline-none focus:border-cyan-400 focus:bg-white"
                          placeholder="输入备注，例如：张三"
                          @keyup.enter="saveRemark(user)"
                        >
                        <button
                          class="rounded-xl bg-slate-950 px-3 py-2 text-xs font-medium text-white transition hover:bg-slate-800 disabled:opacity-60"
                          :disabled="savingKey === userKey(user)"
                          @click="saveRemark(user)"
                        >
                          保存
                        </button>
                        <button
                          class="rounded-xl border border-slate-200 px-3 py-2 text-xs text-slate-600 transition hover:bg-slate-100"
                          @click="remarkEditingKey = ''"
                        >
                          取消
                        </button>
                      </div>
                      <div v-else>
                        <div class="flex items-center gap-2 font-medium text-slate-900">
                          {{ user.remark || '未备注' }}
                          <button
                            class="text-slate-400 transition hover:text-slate-600"
                            title="编辑备注"
                            @click="openRemarkEditor(user)"
                          >
                            <PencilLine class="h-3.5 w-3.5" />
                          </button>
                        </div>
                        <div class="text-xs text-slate-500">{{ user.platform }}</div>
                        <div class="max-w-[260px] truncate text-xs text-slate-400" :title="user.user_id">{{ user.user_id }}</div>
                      </div>
                    </div>
                  </td>
                  <td class="px-4 py-4">
                    <div class="flex flex-wrap gap-2">
                      <button
                        v-for="feature in featureKeys"
                        :key="feature"
                        class="rounded-full border px-3 py-1.5 text-xs transition"
                        :class="user.access[feature]
                          ? 'border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
                          : 'border-slate-200 bg-slate-50 text-slate-500 hover:bg-slate-100'"
                        :disabled="savingKey === userKey(user)"
                        @click="toggleFeature(user, feature)"
                      >
                        {{ featureLabels[feature] || feature }}
                      </button>
                    </div>
                  </td>
                  <td class="px-4 py-4">
                    <div class="flex flex-wrap items-center gap-2">
                      <template v-if="user.tool_policy">
                        <span
                          v-for="group in user.tool_policy.allow"
                          :key="group"
                          class="rounded-full bg-cyan-50 px-2.5 py-1 text-xs text-cyan-700"
                        >
                          {{ group }}
                        </span>
                      </template>
                      <span v-else class="rounded-full bg-slate-100 px-2.5 py-1 text-xs text-slate-500">
                        跟随全局（全部放行）
                      </span>
                      <button
                        class="inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-3 py-1.5 text-xs text-slate-700 transition hover:bg-slate-50"
                        @click="openEditor(user)"
                      >
                        <SlidersHorizontal class="h-3.5 w-3.5" />
                        {{ editingKey === userKey(user) ? '收起' : '配置工具权限' }}
                      </button>
                    </div>
                  </td>
                </tr>
                <tr v-if="editingKey === userKey(user)">
                  <td colspan="3" class="bg-slate-50 px-4 py-4">
                    <div class="rounded-[20px] border border-slate-200 bg-white p-4">
                      <div class="text-sm font-medium text-slate-900">工具白名单</div>
                      <p class="mt-1 text-xs leading-5 text-slate-500">
                        只勾选要放行的工具组，其余对该用户一律拒绝；一个都不勾则视为清除自定义策略、恢复跟随全局。
                      </p>
                      <div class="mt-3 grid gap-2 md:grid-cols-2">
                        <label
                          v-for="group in groupKeys"
                          :key="group"
                          class="flex cursor-pointer items-start gap-2 rounded-2xl border border-slate-200 px-3 py-2 transition hover:bg-slate-50"
                          :class="{ 'border-cyan-300 bg-cyan-50': editSelection.includes(group) }"
                        >
                          <input
                            type="checkbox"
                            class="mt-1"
                            :checked="editSelection.includes(group)"
                            @change="toggleGroup(group)"
                          >
                          <span>
                            <span class="block text-xs font-medium text-slate-800">{{ group }}</span>
                            <span class="block text-xs text-slate-500">{{ groupCatalog[group] }}</span>
                          </span>
                        </label>
                      </div>
                      <div class="mt-4 flex flex-wrap gap-2">
                        <button
                          class="inline-flex items-center gap-2 rounded-2xl bg-slate-950 px-4 py-2 text-xs font-medium text-white transition hover:bg-slate-800 disabled:opacity-60"
                          :disabled="savingKey === userKey(user)"
                          @click="savePolicy(user)"
                        >
                          <Loader2 v-if="savingKey === userKey(user)" class="h-3.5 w-3.5 animate-spin" />
                          保存
                        </button>
                        <button
                          v-if="user.tool_policy"
                          class="rounded-2xl border border-rose-200 px-4 py-2 text-xs text-rose-600 transition hover:bg-rose-50"
                          :disabled="savingKey === userKey(user)"
                          @click="clearPolicy(user)"
                        >
                          清除自定义策略
                        </button>
                        <button
                          class="rounded-2xl border border-slate-200 px-4 py-2 text-xs text-slate-600 transition hover:bg-slate-100"
                          @click="editingKey = ''"
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>

          <div v-if="!users.length" class="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center text-slate-500">
            <TriangleAlert class="h-5 w-5" />
            <div>还没有渠道用户。用户第一次在微信等渠道发消息后会自动出现在这里。</div>
          </div>
        </div>
      </template>
    </section>
  </div>
</template>
