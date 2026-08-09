<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref } from 'vue'
import {
    Bot,
    Braces,
    Cloud,
    Code2,
    Download,
    Github,
    Import,
    Loader2,
    MoreHorizontal,
    Plus,
    RefreshCw,
    Search,
    KeyRound,
    Terminal,
    Wrench,
} from 'lucide-vue-next'

import ViewToastStack from '@/components/ViewToastStack.vue'
import { useViewToasts } from '@/composables/useViewToasts'
import {
    createSkill,
    deleteSkill,
    getSkillDetail,
    getSkills,
    importSkill,
    setSkillEnabled,
    type SkillDetail,
    type SkillInfo,
} from '@/api/skills'

const skills = ref<SkillInfo[]>([])
const loading = ref(false)
const toggling = ref<string | null>(null)
const searchText = ref('')
const filterCategory = ref('')
const filterStatus = ref('')
const filterTrigger = ref('')

const { toasts: viewToasts, push: pushViewToast, dismiss: dismissViewToast } = useViewToasts()

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
    if (error instanceof Error && error.message.trim()) {
        return error.message
    }
    return fallback
}

const categoryFor = (skill: SkillInfo) => {
    if (skill.name.includes('credential')) return '安全与凭证'
    if (skill.name.includes('deploy')) return '部署与运维'
    if (skill.name.includes('docker')) return '容器与镜像'
    if (skill.name.includes('git') || skill.name.includes('gh')) return '版本控制'
    if (skill.name.includes('video')) return '媒体工具'
    if (skill.name.includes('coding')) return '开发工具'
    if (skill.source === 'learned') return '已学习技能'
    return '命令行工具'
}

const iconFor = (skill: SkillInfo) => {
    if (skill.name.includes('credential')) return KeyRound
    if (skill.name.includes('deploy')) return Cloud
    if (skill.name.includes('docker')) return Bot
    if (skill.name.includes('download')) return Download
    if (skill.name.includes('gh')) return Github
    if (skill.name.includes('git')) return Braces
    if (skill.name.includes('opencli')) return Terminal
    if (skill.name.includes('coding')) return Code2
    return Wrench
}

const categoryOptions = computed(() =>
    [...new Set(skills.value.map(skill => categoryFor(skill)))].sort()
)

const triggerOptions = computed(() =>
    [...new Set(skills.value.flatMap(skill => skill.triggers))].sort()
)

const skillRows = computed(() => {
    const keyword = searchText.value.trim().toLowerCase()
    return [...skills.value]
        .filter(skill => {
            if (filterCategory.value && categoryFor(skill) !== filterCategory.value) {
                return false
            }
            if (filterStatus.value === 'enabled' && !skill.enabled) {
                return false
            }
            if (filterStatus.value === 'disabled' && skill.enabled) {
                return false
            }
            if (filterTrigger.value && !skill.triggers.includes(filterTrigger.value)) {
                return false
            }
            if (keyword) {
                const haystack = `${skill.name} ${skill.description} ${skill.triggers.join(' ')}`.toLowerCase()
                if (!haystack.includes(keyword)) {
                    return false
                }
            }
            return true
        })
        .sort((a, b) => a.name.localeCompare(b.name))
})

const load = async () => {
    loading.value = true
    try {
        const response = await getSkills()
        skills.value = response.data.skills || []
    } catch (error) {
        pushViewToast('error', parseErrorMessage(error, '技能列表加载失败'))
    } finally {
        loading.value = false
    }
}

const toggleSkill = async (skill: SkillInfo) => {
    toggling.value = skill.name
    try {
        const response = await setSkillEnabled(skill.name, !skill.enabled)
        skill.enabled = response.data.enabled
    } catch (error) {
        pushViewToast('error', parseErrorMessage(error, `${skill.name} 状态切换失败`))
    } finally {
        toggling.value = null
    }
}

const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({ name: '', description: '', triggersText: '', content: '' })

const openCreateDialog = () => {
    createForm.value = { name: '', description: '', triggersText: '', content: '' }
    showCreateDialog.value = true
}

const submitCreate = async () => {
    const name = createForm.value.name.trim()
    if (!name) {
        pushViewToast('warning', '请填写技能名称')
        return
    }
    creating.value = true
    try {
        await createSkill({
            name,
            description: createForm.value.description.trim(),
            triggers: createForm.value.triggersText
                .split(/[,，]/)
                .map(item => item.trim())
                .filter(Boolean),
            content: createForm.value.content,
        })
        showCreateDialog.value = false
        pushViewToast('success', `技能 ${name} 已创建`)
        await load()
    } catch (error) {
        pushViewToast('error', parseErrorMessage(error, '创建技能失败'))
    } finally {
        creating.value = false
    }
}

const importInput = ref<HTMLInputElement | null>(null)
const importing = ref(false)

const triggerImport = () => {
    importInput.value?.click()
}

const onImportFile = async (event: Event) => {
    const input = event.target as HTMLInputElement
    const file = input.files?.[0]
    input.value = ''
    if (!file) {
        return
    }
    importing.value = true
    try {
        const response = await importSkill(file)
        pushViewToast('success', `技能 ${response.data.name} 已导入`)
        await load()
    } catch (error) {
        pushViewToast('error', parseErrorMessage(error, '导入技能失败'))
    } finally {
        importing.value = false
    }
}

const rowMenu = ref<{ name: string; top: number; left: number } | null>(null)
const confirmDeleteFor = ref('')
const deleting = ref<string | null>(null)
const showDetailDialog = ref(false)
const detailSkill = ref<SkillDetail | null>(null)

const rowMenuSkill = computed(() =>
    skills.value.find(skill => skill.name === rowMenu.value?.name) || null
)

const toggleRowMenu = (skill: SkillInfo, event: MouseEvent) => {
    confirmDeleteFor.value = ''
    if (rowMenu.value?.name === skill.name) {
        rowMenu.value = null
        return
    }
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
    rowMenu.value = {
        name: skill.name,
        top: Math.min(rect.bottom + 6, window.innerHeight - 120),
        left: Math.max(12, rect.right - 150),
    }
}

const openSkillDetail = async (skill: SkillInfo) => {
    rowMenu.value = null
    detailSkill.value = null
    showDetailDialog.value = true
    try {
        const response = await getSkillDetail(skill.name)
        detailSkill.value = response.data
    } catch (error) {
        showDetailDialog.value = false
        pushViewToast('error', parseErrorMessage(error, '技能详情加载失败'))
    }
}

const requestDeleteSkill = async (skill: SkillInfo) => {
    if (confirmDeleteFor.value !== skill.name) {
        confirmDeleteFor.value = skill.name
        return
    }
    deleting.value = skill.name
    try {
        await deleteSkill(skill.name)
        pushViewToast('success', `技能 ${skill.name} 已删除`)
        rowMenu.value = null
        confirmDeleteFor.value = ''
        await load()
    } catch (error) {
        pushViewToast('error', parseErrorMessage(error, '删除技能失败'))
    } finally {
        deleting.value = null
    }
}

onMounted(load)
</script>

<template>
  <div class="skills-page">
    <section class="skills-hero">
      <div>
        <h1>技能管理 / Skills</h1>
        <p>管理系统中的技能模块，启用或禁用特定技能，配置能力与权限。</p>
      </div>
      <div class="hero-actions">
        <button type="button" class="primary-action" @click="openCreateDialog">
          <Plus class="h-4 w-4" />
          新增技能
        </button>
        <button type="button" class="secondary-action" :disabled="importing" @click="triggerImport">
          <Loader2 v-if="importing" class="h-4 w-4 animate-spin" />
          <Import v-else class="h-4 w-4" />
          {{ importing ? '导入中' : '导入技能' }}
        </button>
        <input ref="importInput" type="file" accept=".md,.zip" hidden @change="onImportFile">
      </div>
    </section>

    <section class="filter-panel">
      <label class="filter-select">
        <span>分类</span>
        <select v-model="filterCategory">
          <option value="">全部分类</option>
          <option v-for="option in categoryOptions" :key="option" :value="option">{{ option }}</option>
        </select>
      </label>
      <label class="filter-select">
        <span>状态</span>
        <select v-model="filterStatus">
          <option value="">全部状态</option>
          <option value="enabled">已启用</option>
          <option value="disabled">已禁用</option>
        </select>
      </label>
      <label class="filter-select">
        <span>能力类型</span>
        <select v-model="filterTrigger">
          <option value="">全部类型</option>
          <option v-for="option in triggerOptions" :key="option" :value="option">{{ option }}</option>
        </select>
      </label>
      <label class="skills-search">
        <Search class="h-4 w-4" />
        <input v-model="searchText" type="search" placeholder="搜索技能名称、描述或标签...">
      </label>
      <button type="button" class="refresh-btn" @click="load">
        <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': loading }" />
      </button>
    </section>

    <section class="skills-table-panel">
      <div class="table-meta">共 {{ skillRows.length }} 个技能</div>

      <div v-if="loading" class="loading-row">
        <Loader2 class="h-4 w-4 animate-spin" />
        正在加载技能列表
      </div>

      <div v-else class="skills-table-wrap">
        <table>
          <thead>
            <tr>
              <th>技能名称</th>
              <th>分类</th>
              <th>能力标签</th>
              <th>来源 / 上次更新</th>
              <th>状态</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="skill in skillRows" :key="skill.name">
              <td>
                <div class="skill-name-cell">
                  <div class="skill-icon" :class="{ learned: skill.source === 'learned' }">
                    <component :is="iconFor(skill)" class="h-5 w-5" />
                  </div>
                  <div>
                    <strong>{{ skill.name }}</strong>
                    <p>{{ skill.description || '暂无描述' }}</p>
                  </div>
                </div>
              </td>
              <td>{{ categoryFor(skill) }}</td>
              <td>
                <div class="tag-list">
                  <span v-for="trigger in skill.triggers.slice(0, 4)" :key="trigger">{{ trigger }}</span>
                  <span v-if="skill.triggers.length > 4">+{{ skill.triggers.length - 4 }}</span>
                </div>
              </td>
              <td>
                <div class="source-cell">
                  <strong>{{ skill.source === 'builtin' ? '系统内置' : '已学习' }}</strong>
                  <span>admin</span>
                </div>
              </td>
              <td>
                <button
                  type="button"
                  class="switch"
                  :class="{ on: skill.enabled }"
                  :disabled="toggling === skill.name"
                  @click="toggleSkill(skill)"
                >
                  <span />
                </button>
              </td>
              <td>
                <button type="button" class="row-menu" @click="toggleRowMenu(skill, $event)">
                  <MoreHorizontal class="h-4 w-4" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>

        <div v-if="!skillRows.length" class="empty-state">
          暂无技能
        </div>
      </div>
    </section>

    <ViewToastStack :toasts="viewToasts" @dismiss="dismissViewToast" />

    <template v-if="rowMenu && rowMenuSkill">
      <div class="menu-overlay" @click="rowMenu = null" />
      <div class="row-action-menu" :style="{ top: `${rowMenu.top}px`, left: `${rowMenu.left}px` }">
        <button type="button" @click="openSkillDetail(rowMenuSkill)">查看详情</button>
        <button
          v-if="rowMenuSkill.source === 'learned'"
          type="button"
          class="danger"
          :disabled="deleting === rowMenuSkill.name"
          @click="requestDeleteSkill(rowMenuSkill)"
        >
          {{ confirmDeleteFor === rowMenuSkill.name ? '确认删除？' : '删除' }}
        </button>
      </div>
    </template>

    <div v-if="showCreateDialog" class="dialog-backdrop" @click.self="showCreateDialog = false">
      <div class="dialog-card">
        <h3>新增技能</h3>
        <label>
          名称
          <input v-model="createForm.name" type="text" placeholder="如 daily_brief（字母、数字、._-）">
        </label>
        <label>
          描述
          <input v-model="createForm.description" type="text" placeholder="这个技能做什么">
        </label>
        <label>
          触发词（逗号分隔，可选）
          <input v-model="createForm.triggersText" type="text" placeholder="如 每日简报, brief">
        </label>
        <label>
          内容（Markdown，可选）
          <textarea v-model="createForm.content" rows="8" placeholder="# 使用说明"></textarea>
        </label>
        <div class="dialog-actions">
          <button type="button" class="secondary-action" :disabled="creating" @click="showCreateDialog = false">取消</button>
          <button type="button" class="primary-action" :disabled="creating" @click="submitCreate">
            <Loader2 v-if="creating" class="h-4 w-4 animate-spin" />
            {{ creating ? '创建中' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="showDetailDialog" class="dialog-backdrop" @click.self="showDetailDialog = false">
      <div class="dialog-card detail-card">
        <template v-if="detailSkill">
          <h3>{{ detailSkill.name }}</h3>
          <p class="detail-desc">{{ detailSkill.description || '暂无描述' }}</p>
          <div v-if="detailSkill.triggers.length" class="tag-list">
            <span v-for="trigger in detailSkill.triggers" :key="trigger">{{ trigger }}</span>
          </div>
          <div v-if="detailSkill.scripts.length" class="detail-scripts">
            <strong>脚本</strong>
            <code v-for="script in detailSkill.scripts" :key="script">scripts/{{ script }}</code>
          </div>
          <pre class="skill-md-preview">{{ detailSkill.content }}</pre>
        </template>
        <div v-else class="loading-row">
          <Loader2 class="h-4 w-4 animate-spin" />
          正在加载技能详情
        </div>
        <div class="dialog-actions">
          <button type="button" class="secondary-action" @click="showDetailDialog = false">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.skills-page {
  display: grid;
  gap: 18px;
}

.skills-hero,
.filter-panel,
.skills-table-panel {
  border: 1px solid var(--panel-border);
  border-radius: 14px;
  background: #fff;
  box-shadow: var(--shadow-card);
}

.skills-hero {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
  padding: 24px 26px;
}

.skills-hero h1 {
  margin: 0;
  color: var(--text-strong);
  font-size: 26px;
  font-weight: 800;
}

.skills-hero p {
  margin: 10px 0 0;
  color: var(--text-muted);
  font-size: 15px;
}

.hero-actions {
  display: flex;
  gap: 12px;
}

.primary-action,
.secondary-action,
.refresh-btn,
.row-menu {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 800;
}

.primary-action {
  gap: 8px;
  height: 42px;
  padding: 0 18px;
  border: 0;
  background: var(--brand-blue);
  color: #fff;
}

.secondary-action {
  gap: 8px;
  height: 42px;
  padding: 0 16px;
  border: 1px solid var(--panel-border);
  background: #fff;
  color: var(--text-body);
}

.filter-panel {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr minmax(260px, 1.5fr) 44px;
  gap: 12px;
  padding: 18px 22px;
}

.filter-select,
.skills-search,
.refresh-btn {
  height: 42px;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #fff;
  color: var(--text-body);
}

.filter-select {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  padding: 0 14px;
  text-align: left;
  cursor: pointer;
}

.filter-select span {
  color: var(--text-muted);
  white-space: nowrap;
}

.filter-select select {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text-body);
  font-size: 14px;
  cursor: pointer;
}

.skills-search {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  color: var(--text-subtle);
}

.skills-search input {
  min-width: 0;
  width: 100%;
  border: 0 !important;
  outline: 0;
  box-shadow: none !important;
}

.refresh-btn,
.row-menu {
  width: 42px;
  color: var(--text-body);
}

.dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(15, 23, 42, 0.45);
}

.dialog-card {
  display: grid;
  gap: 14px;
  width: min(560px, 100%);
  max-height: 85vh;
  overflow-y: auto;
  border-radius: 14px;
  background: #fff;
  padding: 24px;
}

.dialog-card h3 {
  margin: 0;
  color: var(--text-strong);
  font-size: 18px;
}

.dialog-card label {
  display: grid;
  gap: 6px;
  color: var(--text-body);
  font-size: 13px;
  font-weight: 700;
}

.dialog-card input,
.dialog-card textarea {
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  padding: 9px 12px;
  color: var(--text-body);
  font-size: 14px;
  font-family: inherit;
  font-weight: 400;
}

.dialog-card textarea {
  resize: vertical;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.menu-overlay {
  position: fixed;
  inset: 0;
  z-index: 40;
}

.row-action-menu {
  position: fixed;
  z-index: 41;
  display: grid;
  min-width: 150px;
  padding: 6px;
  border: 1px solid var(--panel-border);
  border-radius: 9px;
  background: #fff;
  box-shadow: 0 18px 40px rgb(15 23 42 / 12%);
}

.row-action-menu button {
  border: 0;
  border-radius: 7px;
  background: transparent;
  padding: 9px 12px;
  color: var(--text-body);
  font-size: 13px;
  font-weight: 700;
  text-align: left;
  cursor: pointer;
}

.row-action-menu button:hover {
  background: #f1f5f9;
}

.row-action-menu button.danger {
  color: #ef4444;
}

.detail-card {
  width: min(680px, 100%);
}

.detail-desc {
  margin: 0;
  color: var(--text-muted);
  font-size: 14px;
}

.detail-scripts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.detail-scripts code {
  border-radius: 6px;
  background: #f1f5f9;
  padding: 3px 8px;
}

.skill-md-preview {
  max-height: 320px;
  overflow: auto;
  margin: 0;
  border: 1px solid var(--panel-border);
  border-radius: 8px;
  background: #f8fafc;
  padding: 12px 14px;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.skills-table-panel {
  padding: 22px 24px;
}

.table-meta {
  margin-bottom: 18px;
  color: var(--text-body);
  font-size: 15px;
}

.loading-row {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-muted);
}

.skills-table-wrap {
  overflow-x: auto;
  border: 1px solid var(--panel-border);
  border-radius: 12px;
}

table {
  width: 100%;
  min-width: 980px;
  border-collapse: collapse;
  font-size: 14px;
}

th {
  padding: 16px 18px;
  border-bottom: 1px solid var(--panel-border);
  color: var(--text-muted);
  font-weight: 800;
  text-align: left;
}

td {
  padding: 14px 18px;
  border-bottom: 1px solid #eef2f7;
  color: var(--text-body);
  vertical-align: middle;
}

tbody tr:last-child td {
  border-bottom: 0;
}

.skill-name-cell {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr);
  align-items: center;
  gap: 14px;
}

.skill-icon {
  display: grid;
  place-items: center;
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--brand-blue-soft);
  color: var(--brand-blue);
}

.skill-icon.learned {
  background: #ecfdf3;
  color: #16a34a;
}

.skill-name-cell strong {
  color: var(--text-strong);
  font-size: 16px;
}

.skill-name-cell p {
  max-width: 520px;
  margin: 6px 0 0;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-list span {
  border-radius: 7px;
  background: #f2f4f7;
  color: #667085;
  padding: 5px 9px;
  font-size: 12px;
}

.source-cell {
  display: grid;
  gap: 4px;
}

.source-cell strong {
  color: var(--text-body);
  font-size: 13px;
}

.source-cell span {
  color: var(--text-muted);
  font-size: 12px;
}

.switch {
  position: relative;
  width: 46px;
  height: 26px;
  border: 0;
  border-radius: 999px;
  background: #d0d5dd;
  padding: 2px;
}

.switch span {
  display: block;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #fff;
  transition: transform 0.18s ease;
}

.switch.on {
  background: var(--brand-blue);
}

.switch.on span {
  transform: translateX(20px);
}

.empty-state {
  padding: 48px;
  color: var(--text-muted);
  text-align: center;
}

@media (max-width: 980px) {
  .skills-hero {
    flex-direction: column;
  }

  .filter-panel {
    grid-template-columns: 1fr;
  }
}
</style>
