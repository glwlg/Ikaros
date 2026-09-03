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
    X,
} from 'lucide-vue-next'

import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
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

const skillStats = computed(() => ({
    total: skills.value.length,
    enabled: skills.value.filter(skill => skill.enabled).length,
    builtin: skills.value.filter(skill => skill.source === 'builtin').length,
    learned: skills.value.filter(skill => skill.source === 'learned').length,
}))

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
        const { data } = await deleteSkill(skill.name)
        pushViewToast(
            'success',
            data.backup
                ? `技能 ${skill.name} 已删除，备份已保存：${data.backup}`
                : `技能 ${skill.name} 已删除`
        )
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
  <div class="ikaros-page skills-page">
    <header class="ikaros-page-header skills-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Admin · Skills</p>
        <h1 class="ikaros-page-title">技能管理</h1>
        <p class="ikaros-page-description">管理系统中的技能模块，启用或禁用特定技能，配置能力与权限。</p>
      </div>
      <div class="skills-actions">
        <button type="button" class="skills-icon-action" title="刷新列表" :disabled="loading" @click="load">
          <RefreshCw :class="{ 'is-spinning': loading }" />
        </button>
        <button type="button" class="ikaros-secondary-action" :disabled="importing" @click="triggerImport">
          <Loader2 v-if="importing" class="is-spinning" />
          <Import v-else />
          {{ importing ? '导入中' : '导入技能' }}
        </button>
        <button type="button" class="ikaros-primary-action" @click="openCreateDialog">
          <Plus />
          新增技能
        </button>
      </div>
    </header>

    <input ref="importInput" type="file" accept=".md,.zip" hidden @change="onImportFile">

    <LiquidGlass :radius="20" :optics="compactOptics" class="skills-metrics">
      <div class="skills-metrics-inner">
        <div class="skills-metric">
          <span>技能总数</span>
          <strong>{{ skillStats.total }}</strong>
        </div>
        <i class="skills-metric-divider" aria-hidden="true" />
        <div class="skills-metric">
          <span>已启用</span>
          <strong class="is-green">{{ skillStats.enabled }}</strong>
        </div>
        <i class="skills-metric-divider" aria-hidden="true" />
        <div class="skills-metric">
          <span>系统内置</span>
          <strong>{{ skillStats.builtin }}</strong>
        </div>
        <i class="skills-metric-divider" aria-hidden="true" />
        <div class="skills-metric">
          <span>已学习</span>
          <strong class="is-teal">{{ skillStats.learned }}</strong>
        </div>
      </div>
    </LiquidGlass>

    <LiquidGlass :radius="24" :optics="panelOptics" class="skills-catalog">
      <div class="catalog-shell">
        <div class="catalog-filterbar">
          <div class="catalog-filters">
            <label class="catalog-select">
              <select v-model="filterCategory">
                <option value="">所有类别</option>
                <option v-for="option in categoryOptions" :key="option" :value="option">{{ option }}</option>
              </select>
            </label>
            <label class="catalog-select">
              <select v-model="filterStatus">
                <option value="">状态（全部）</option>
                <option value="enabled">已启用</option>
                <option value="disabled">已禁用</option>
              </select>
            </label>
            <label class="catalog-select">
              <select v-model="filterTrigger">
                <option value="">能力类型</option>
                <option v-for="option in triggerOptions" :key="option" :value="option">{{ option }}</option>
              </select>
            </label>
          </div>
          <label class="catalog-search">
            <Search />
            <input v-model="searchText" type="search" placeholder="搜索名称/描述/标签...">
          </label>
        </div>

        <div v-if="loading" class="catalog-loading">
          <Loader2 class="is-spinning" />
          正在加载技能列表
        </div>

        <div v-else class="catalog-table-wrap">
          <table>
            <thead>
              <tr>
                <th>技能名称</th>
                <th>分类</th>
                <th>能力标签</th>
                <th>来源</th>
                <th>状态</th>
                <th><span class="sr-only">操作</span></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="skill in skillRows" :key="skill.name">
                <td>
                  <div class="skill-name-cell">
                    <div class="skill-icon" :class="{ learned: skill.source === 'learned' }">
                      <component :is="iconFor(skill)" />
                    </div>
                    <div>
                      <strong>{{ skill.name }}</strong>
                      <p>{{ skill.description || '暂无描述' }}</p>
                    </div>
                  </div>
                </td>
                <td class="skill-category">{{ categoryFor(skill) }}</td>
                <td>
                  <div class="tag-list">
                    <span v-for="trigger in skill.triggers.slice(0, 4)" :key="trigger">{{ trigger }}</span>
                    <span v-if="skill.triggers.length > 4">+{{ skill.triggers.length - 4 }}</span>
                  </div>
                </td>
                <td>
                  <span class="source-chip" :class="{ learned: skill.source === 'learned' }">
                    {{ skill.source === 'builtin' ? '系统内置' : '已学习' }}
                  </span>
                </td>
                <td>
                  <button
                    type="button"
                    class="switch"
                    :class="{ on: skill.enabled }"
                    :disabled="toggling === skill.name"
                    :title="skill.enabled ? '点击禁用' : '点击启用'"
                    @click="toggleSkill(skill)"
                  >
                    <span />
                  </button>
                </td>
                <td>
                  <button type="button" class="row-menu" title="更多操作" @click="toggleRowMenu(skill, $event)">
                    <MoreHorizontal />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>

          <div v-if="!skillRows.length" class="catalog-empty">
            暂无技能
          </div>
        </div>
      </div>
    </LiquidGlass>

    <ViewToastStack :toasts="viewToasts" @dismiss="dismissViewToast" />

    <template v-if="rowMenu && rowMenuSkill">
      <div class="menu-overlay" @click="rowMenu = null" />
      <div class="row-action-menu" :style="{ top: `${rowMenu.top}px`, left: `${rowMenu.left}px` }">
        <button type="button" @click="openSkillDetail(rowMenuSkill)">查看详情</button>
        <button
          v-if="rowMenuSkill.source === 'learned'"
          type="button"
          class="is-danger"
          :disabled="deleting === rowMenuSkill.name"
          @click="requestDeleteSkill(rowMenuSkill)"
        >
          {{ confirmDeleteFor === rowMenuSkill.name ? '确认删除？' : '删除' }}
        </button>
      </div>
    </template>

    <div v-if="showCreateDialog" class="dialog-backdrop" @click.self="showCreateDialog = false">
      <div class="dialog-card ikaros-surface ikaros-surface-strong">
        <header class="dialog-head">
          <h3>新增技能</h3>
          <button type="button" class="dialog-close" title="关闭" @click="showCreateDialog = false">
            <X />
          </button>
        </header>
        <div class="dialog-body">
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
        </div>
        <footer class="dialog-actions">
          <button type="button" class="ikaros-secondary-action" :disabled="creating" @click="showCreateDialog = false">取消</button>
          <button type="button" class="ikaros-primary-action" :disabled="creating" @click="submitCreate">
            <Loader2 v-if="creating" class="is-spinning" />
            {{ creating ? '创建中' : '创建' }}
          </button>
        </footer>
      </div>
    </div>

    <div v-if="showDetailDialog" class="dialog-backdrop" @click.self="showDetailDialog = false">
      <div class="dialog-card detail-card ikaros-surface ikaros-surface-strong">
        <header class="dialog-head">
          <h3>{{ detailSkill?.name || '技能详情' }}</h3>
          <button type="button" class="dialog-close" title="关闭" @click="showDetailDialog = false">
            <X />
          </button>
        </header>
        <div v-if="detailSkill" class="dialog-body">
          <p class="detail-desc">{{ detailSkill.description || '暂无描述' }}</p>
          <div v-if="detailSkill.triggers.length" class="tag-list">
            <span v-for="trigger in detailSkill.triggers" :key="trigger">{{ trigger }}</span>
          </div>
          <div v-if="detailSkill.scripts.length" class="detail-scripts">
            <strong>脚本</strong>
            <code v-for="script in detailSkill.scripts" :key="script">scripts/{{ script }}</code>
          </div>
          <pre class="skill-md-preview">{{ detailSkill.content }}</pre>
        </div>
        <div v-else class="catalog-loading dialog-loading">
          <Loader2 class="is-spinning" />
          正在加载技能详情
        </div>
        <footer class="dialog-actions">
          <button type="button" class="ikaros-secondary-action" @click="showDetailDialog = false">关闭</button>
        </footer>
      </div>
    </div>
  </div>
</template>

<style scoped>
.skills-page {
  gap: 22px;
}

.skills-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 10px;
}

.skills-actions :is(.ikaros-primary-action, .ikaros-secondary-action) svg {
  width: 16px;
  height: 16px;
}

.skills-icon-action {
  display: grid;
  width: 40px;
  height: 40px;
  flex: none;
  place-items: center;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.4);
  color: var(--ikaros-copy);
}

:global(.dark) .skills-icon-action { background: rgba(255, 255, 255, 0.06); }
.skills-icon-action:hover { border-color: rgba(232, 93, 142, 0.32); color: var(--ikaros-pink); }
.skills-icon-action:disabled { cursor: wait; opacity: 0.65; }
.skills-icon-action svg { width: 16px; height: 16px; }

.is-spinning { animation: skills-spin 850ms linear infinite; }

.skills-metrics {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.8);
}

:global(.dark) .skills-metrics { --ikaros-glass-fill: rgba(43, 34, 40, 0.82); }

.skills-metrics-inner {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 22px;
  padding: 16px 24px;
}

.skills-metric {
  display: grid;
  gap: 3px;
}

.skills-metric span {
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
}

.skills-metric strong {
  color: var(--ikaros-ink);
  font-size: 21px;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.skills-metric strong.is-green { color: var(--ikaros-rind); }
.skills-metric strong.is-teal { color: var(--ikaros-eye); }

.skills-metric-divider {
  width: 1px;
  height: 30px;
  background: var(--ikaros-line);
}

.skills-catalog {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .skills-catalog { --ikaros-glass-fill: rgba(43, 34, 40, 0.86); }

.catalog-shell {
  display: grid;
  min-height: 480px;
  align-content: start;
}

.catalog-filterbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 15px 20px;
  border-bottom: 1px solid var(--ikaros-line);
}

.catalog-filters {
  display: flex;
  flex-wrap: wrap;
  gap: 9px;
}

.catalog-select select {
  height: 36px;
  padding: 0 30px 0 12px;
  border: 1px solid var(--ikaros-line);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--ikaros-ink);
  font-size: 12px;
  font-weight: 650;
  outline: none;
  cursor: pointer;
}

:global(.dark) .catalog-select select { background: rgba(255, 255, 255, 0.07); }
.catalog-select select:focus { border-color: rgba(232, 93, 142, 0.4); box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.1); }

.catalog-search {
  display: flex;
  width: min(260px, 100%);
  height: 36px;
  align-items: center;
  gap: 8px;
  padding: 0 12px;
  border: 1px solid var(--ikaros-line);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--ikaros-muted);
}

:global(.dark) .catalog-search { background: rgba(255, 255, 255, 0.07); }
.catalog-search:focus-within { border-color: rgba(232, 93, 142, 0.4); box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.1); }
.catalog-search svg { width: 15px; height: 15px; flex: none; }

.catalog-search input {
  min-width: 0;
  width: 100%;
  border: 0 !important;
  outline: 0;
  background: transparent !important;
  box-shadow: none !important;
  color: var(--ikaros-ink);
  font-size: 12px;
}

.catalog-loading {
  display: flex;
  min-height: 220px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.catalog-loading svg { width: 16px; height: 16px; }

.catalog-table-wrap {
  overflow-x: auto;
}

.catalog-table-wrap table {
  width: 100%;
  min-width: 920px;
  border-collapse: collapse;
  font-size: 13px;
}

.catalog-table-wrap th {
  padding: 13px 16px;
  border-bottom: 1px solid var(--ikaros-line);
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 750;
  letter-spacing: 0.04em;
  text-align: left;
}

.catalog-table-wrap td {
  padding: 13px 16px;
  border-bottom: 1px solid var(--ikaros-line);
  color: var(--ikaros-copy);
  vertical-align: middle;
}

.catalog-table-wrap tbody tr {
  transition: background-color 160ms ease;
}

.catalog-table-wrap tbody tr:hover {
  background: rgba(255, 255, 255, 0.42);
}

:global(.dark) .catalog-table-wrap tbody tr:hover { background: rgba(255, 255, 255, 0.05); }
.catalog-table-wrap tbody tr:last-child td { border-bottom: 0; }

.skill-name-cell {
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr);
  align-items: center;
  gap: 13px;
}

.skill-icon {
  display: grid;
  width: 42px;
  height: 42px;
  place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.62);
  border-radius: 13px;
  background: rgba(232, 93, 142, 0.09);
  color: var(--ikaros-pink);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
}

:global(.dark) .skill-icon { border-color: rgba(255, 255, 255, 0.09); }
.skill-icon.learned { background: rgba(42, 140, 138, 0.1); color: var(--ikaros-eye); }
.skill-icon svg { width: 19px; height: 19px; }

.skill-name-cell strong {
  color: var(--ikaros-ink);
  font-size: 14px;
  font-weight: 750;
}

.skill-name-cell p {
  max-width: 460px;
  margin: 5px 0 0;
  overflow: hidden;
  color: var(--ikaros-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.skill-category {
  font-size: 12px;
  white-space: nowrap;
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag-list span {
  border: 1px solid var(--ikaros-line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--ikaros-copy);
  padding: 4px 8px;
  font-size: 11px;
}

:global(.dark) .tag-list span { background: rgba(255, 255, 255, 0.06); }

.source-chip {
  display: inline-flex;
  align-items: center;
  padding: 4px 9px;
  border-radius: 999px;
  background: rgba(23, 19, 26, 0.08);
  color: var(--ikaros-ink);
  font-size: 11px;
  font-weight: 750;
  white-space: nowrap;
}

:global(.dark) .source-chip { background: rgba(255, 255, 255, 0.1); }
.source-chip.learned { background: rgba(232, 93, 142, 0.14); color: var(--ikaros-pink-dark); }
:global(.dark) .source-chip.learned { color: #f3a1c1; }

.switch {
  position: relative;
  width: 38px;
  height: 22px;
  border: 0;
  border-radius: 999px;
  background: rgba(23, 19, 26, 0.18);
  padding: 2px;
  cursor: pointer;
}

:global(.dark) .switch { background: rgba(255, 255, 255, 0.16); }

.switch span {
  display: block;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(23, 19, 26, 0.25);
  transition: transform 180ms ease;
}

.switch.on {
  background: var(--ikaros-pink);
}

.switch.on span {
  transform: translateX(16px);
}

.switch:disabled {
  cursor: wait;
  opacity: 0.6;
}

.row-menu {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--ikaros-muted);
  cursor: pointer;
}

.row-menu:hover { background: rgba(232, 93, 142, 0.1); color: var(--ikaros-pink); }
.row-menu svg { width: 17px; height: 17px; }

.catalog-empty {
  padding: 52px 20px;
  color: var(--ikaros-muted);
  font-size: 13px;
  text-align: center;
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
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 12px;
  background: var(--ikaros-glass-strong);
  box-shadow: 0 18px 44px rgba(23, 19, 26, 0.16), inset 0 1px 0 rgba(255, 255, 255, 0.7);
  backdrop-filter: blur(26px) saturate(150%);
  -webkit-backdrop-filter: blur(26px) saturate(150%);
}

.row-action-menu button {
  border: 0;
  border-radius: 8px;
  background: transparent;
  padding: 9px 12px;
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 700;
  text-align: left;
  cursor: pointer;
}

.row-action-menu button:hover {
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.row-action-menu button.is-danger {
  color: #c63741;
}

.row-action-menu button.is-danger:hover {
  background: rgba(198, 55, 65, 0.09);
}

.dialog-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1100;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(23, 19, 26, 0.3);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.dialog-card {
  display: grid;
  width: min(600px, 100%);
  max-height: 85vh;
  overflow: hidden;
  border-radius: 18px;
}

.dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 18px 22px;
  border-bottom: 1px solid var(--ikaros-line);
}

.dialog-head h3 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 17px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.dialog-close {
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

.dialog-close:hover { background: rgba(232, 93, 142, 0.1); color: var(--ikaros-pink); }
.dialog-close svg { width: 16px; height: 16px; }

.dialog-body {
  display: grid;
  gap: 14px;
  padding: 20px 22px;
  overflow-y: auto;
}

.dialog-body label {
  display: grid;
  gap: 7px;
  color: var(--ikaros-ink);
  font-size: 12px;
  font-weight: 750;
}

.dialog-body input,
.dialog-body textarea {
  border: 1px solid var(--ikaros-line);
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.55);
  padding: 10px 13px;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-family: inherit;
  font-weight: 400;
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

:global(.dark) .dialog-body :is(input, textarea) { background: rgba(255, 255, 255, 0.06); }

.dialog-body input:focus,
.dialog-body textarea:focus {
  border-color: rgba(232, 93, 142, 0.45);
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.1);
}

.dialog-body textarea {
  resize: vertical;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.6;
}

.dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 15px 22px;
  border-top: 1px solid var(--ikaros-line);
  background: rgba(255, 255, 255, 0.35);
}

:global(.dark) .dialog-actions { background: rgba(255, 255, 255, 0.04); }
.dialog-actions svg { width: 15px; height: 15px; }

.detail-card {
  width: min(680px, 100%);
}

.dialog-loading {
  min-height: 160px;
}

.detail-desc {
  margin: 0;
  color: var(--ikaros-copy);
  font-size: 13px;
  line-height: 1.6;
}

.detail-scripts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  color: var(--ikaros-ink);
  font-size: 12px;
}

.detail-scripts code {
  border: 1px solid var(--ikaros-line);
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.5);
  padding: 3px 8px;
  font-size: 11px;
}

:global(.dark) .detail-scripts code { background: rgba(255, 255, 255, 0.06); }

.skill-md-preview {
  max-height: 320px;
  overflow: auto;
  margin: 0;
  border: 1px solid var(--ikaros-line);
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.42);
  padding: 13px 15px;
  color: var(--ikaros-copy);
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

:global(.dark) .skill-md-preview { background: rgba(255, 255, 255, 0.05); }

@keyframes skills-spin { to { transform: rotate(360deg); } }

@media (max-width: 720px) {
  .skills-actions { width: 100%; }
  .skills-actions .ikaros-primary-action,
  .skills-actions .ikaros-secondary-action { flex: 1; }
  .skills-metrics-inner { gap: 14px; }
  .skills-metric-divider { display: none; }
  .skills-metric { min-width: 40%; }
  .catalog-search { width: 100%; }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning { animation: none; }
  .catalog-table-wrap tbody tr,
  .switch span { transition: none; }
}
</style>
