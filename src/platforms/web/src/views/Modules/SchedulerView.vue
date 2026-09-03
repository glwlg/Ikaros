<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CalendarClock, Clock, Loader2, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-vue-next'

import request from '@/api/request'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'

type RunCalendar = 'always' | 'weekdays' | 'trading_days'

interface SchedulerTask {
  id: number
  crontab: string
  instruction: string
  is_active: boolean
  run_calendar?: RunCalendar
}

const tasks = ref<SchedulerTask[]>([])
const loading = ref(false)
const showDialog = ref(false)
const editingId = ref<number | null>(null)
const expandedIds = ref<Set<number>>(new Set())
const formData = ref({
  crontab: '',
  instruction: '',
  run_calendar: 'always' as RunCalendar,
})

const PREVIEW_LIMIT = 96

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

const loadData = async () => {
  loading.value = true
  try {
    const res = await request('/scheduler', { method: 'GET' })
    tasks.value = res.data || []
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  editingId.value = null
  formData.value = { crontab: '', instruction: '', run_calendar: 'always' }
  showDialog.value = true
}

const closeDialog = () => {
  showDialog.value = false
  formData.value = { crontab: '', instruction: '', run_calendar: 'always' }
  editingId.value = null
}

const openEdit = (task: SchedulerTask) => {
  editingId.value = task.id
  formData.value = {
    crontab: task.crontab,
    instruction: task.instruction,
    run_calendar: (task.run_calendar || 'always') as RunCalendar,
  }
  showDialog.value = true
}

const handleSave = async () => {
  if (!formData.value.crontab || !formData.value.instruction) return
  try {
    if (editingId.value) {
      await request(`/scheduler/${editingId.value}`, {
        method: 'PUT',
        data: formData.value,
      })
    } else {
      await request('/scheduler', {
        method: 'POST',
        data: formData.value,
      })
    }
    closeDialog()
    loadData()
  } catch (e: any) {
    alert(e?.response?.data?.detail || '操作失败')
  }
}

const handleDelete = async (id: number) => {
  if (!confirm('确定删除该定时任务吗？')) return
  try {
    await request(`/scheduler/${id}`, { method: 'DELETE' })
    loadData()
  } catch (e) {
    console.error(e)
  }
}

const toggleStatus = async (task: SchedulerTask) => {
  try {
    await request(`/scheduler/${task.id}/status`, {
      method: 'PUT',
      data: { is_active: !task.is_active },
    })
    loadData()
  } catch (e) {
    console.error(e)
  }
}

const collapsedPreview = (instruction: string) => {
  const text = String(instruction || '').replace(/\s+/g, ' ').trim()
  if (text.length <= PREVIEW_LIMIT) return text
  return `${text.slice(0, PREVIEW_LIMIT).trimEnd()}...`
}

const needsExpand = (instruction: string) =>
  String(instruction || '').replace(/\s+/g, ' ').trim().length > PREVIEW_LIMIT

const isExpanded = (id: number) => expandedIds.value.has(id)

const toggleExpand = (id: number) => {
  const next = new Set(expandedIds.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  expandedIds.value = next
}

const calendarLabel = (value?: string) => {
  if (value === 'weekdays') return '仅工作日'
  if (value === 'trading_days') return '仅交易日'
  return '每天'
}

onMounted(() => {
  loadData()
})

const activeCount = computed(() => tasks.value.filter((task) => task.is_active).length)
const pausedCount = computed(() => tasks.value.length - activeCount.value)
</script>

<template>
  <div class="ikaros-page scheduler-page">
    <header class="ikaros-page-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Scheduler</p>
        <h1 class="ikaros-page-title">定时任务</h1>
        <p class="ikaros-page-description">按 Cron 计划自动执行指令，并把结果推送到绑定的消息渠道。</p>
      </div>
      <div class="header-actions">
        <button type="button" class="ikaros-secondary-action refresh-button" :disabled="loading" title="刷新" @click="loadData">
          <RefreshCw :class="{ 'is-spinning': loading }" />
        </button>
        <button type="button" class="ikaros-primary-action create-button" @click="openCreate">
          <Plus />
          创建定时任务
        </button>
      </div>
    </header>

    <div class="stat-chips">
      <span class="stat-chip">
        <span class="stat-dot is-total" />
        总任务
        <strong>{{ tasks.length }}</strong>
      </span>
      <span class="stat-chip">
        <span class="stat-dot is-live" />
        运行中
        <strong class="is-live">{{ activeCount }}</strong>
      </span>
      <span class="stat-chip">
        <span class="stat-dot is-paused" />
        已暂停
        <strong>{{ pausedCount }}</strong>
      </span>
    </div>

    <LiquidGlass :radius="24" :optics="panelOptics" class="scheduler-panel">
      <div class="panel-shell">
        <header class="panel-header">
          <div class="panel-title">
            <span class="panel-title-icon"><CalendarClock /></span>
            <h2>任务列表</h2>
          </div>
          <span class="panel-count">{{ tasks.length }} 项</span>
        </header>

        <div v-if="loading" class="panel-loading">
          <Loader2 class="is-spinning" />
        </div>

        <div v-else-if="!tasks.length" class="panel-empty">
          <CalendarClock />
          <div>
            <strong>暂无定时任务</strong>
            <p>创建第一个任务，Ikaros 会按计划自动执行。</p>
          </div>
        </div>

        <div v-else class="task-list">
          <article
            v-for="task in tasks"
            :key="task.id"
            class="task-row"
            :class="{ 'is-paused': !task.is_active }"
          >
            <div class="task-main">
              <p class="task-instruction" :class="{ 'is-expanded': isExpanded(task.id) }">
                {{ isExpanded(task.id) ? task.instruction : collapsedPreview(task.instruction) }}
              </p>
              <div class="task-meta">
                <span class="task-chip">
                  <Clock />
                  {{ calendarLabel(task.run_calendar) }}
                </span>
                <button
                  v-if="needsExpand(task.instruction)"
                  type="button"
                  class="task-expand"
                  @click="toggleExpand(task.id)"
                >
                  {{ isExpanded(task.id) ? '收起' : '展开全文' }}
                </button>
              </div>
            </div>

            <div class="task-cron">
              <span class="task-block-label">Cron 表达式</span>
              <code>{{ task.crontab }}</code>
            </div>

            <div class="task-state">
              <span class="state-chip" :class="task.is_active ? 'is-live' : 'is-paused'">
                <span class="state-dot" />
                {{ task.is_active ? '运行中' : '已暂停' }}
              </span>
            </div>

            <div class="task-actions">
              <label class="switch" :title="task.is_active ? '暂停任务' : '启用任务'">
                <input type="checkbox" :checked="task.is_active" @change="toggleStatus(task)">
                <span class="switch-track" />
              </label>
              <button type="button" class="row-button" title="编辑" @click="openEdit(task)">
                <Pencil />
              </button>
              <button type="button" class="row-button is-danger" title="删除" @click="handleDelete(task.id)">
                <Trash2 />
              </button>
            </div>
          </article>
        </div>
      </div>
    </LiquidGlass>

    <div v-if="showDialog" class="modal-layer" @click.self="closeDialog">
      <LiquidGlass :radius="24" :optics="panelOptics" class="modal-panel">
        <header class="modal-header">
          <h2>{{ editingId ? '编辑定时任务' : '创建定时任务' }}</h2>
          <button type="button" class="modal-close" title="关闭" @click="closeDialog">
            <X />
          </button>
        </header>
        <div class="modal-body">
          <div class="field-group">
            <label class="field-label" for="scheduler-instruction">任务指令</label>
            <textarea
              id="scheduler-instruction"
              v-model="formData.instruction"
              rows="5"
              class="field-textarea"
              placeholder="例如：播报今天的天气"
            />
          </div>
          <div class="field-group">
            <label class="field-label" for="scheduler-cron">Cron 表达式</label>
            <input
              id="scheduler-cron"
              v-model="formData.crontab"
              type="text"
              class="field-input is-mono"
              placeholder="0 8 * * *"
            >
          </div>
          <div class="field-group">
            <label class="field-label" for="scheduler-calendar">运行日类型</label>
            <select id="scheduler-calendar" v-model="formData.run_calendar" class="field-input">
              <option value="always">每天（按 cron 原样）</option>
              <option value="weekdays">仅工作日（周一至周五）</option>
              <option value="trading_days">仅 A 股交易日（排除法定节假日）</option>
            </select>
            <p class="field-hint">交易日会按中国法定节假日跳过；调休上班日会执行。</p>
          </div>
        </div>
        <footer class="modal-footer">
          <button type="button" class="ikaros-secondary-action" @click="closeDialog">取消</button>
          <button type="button" class="ikaros-primary-action" @click="handleSave">保存</button>
        </footer>
      </LiquidGlass>
    </div>
  </div>
</template>

<style scoped>
.scheduler-page {
  width: min(1280px, 100%);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.create-button svg,
.modal-footer svg {
  width: 16px;
  height: 16px;
}

.refresh-button {
  width: 40px;
  padding: 0;
}

.refresh-button svg {
  width: 16px;
  height: 16px;
}

.refresh-button .is-spinning {
  animation: scheduler-spin 850ms linear infinite;
}

.stat-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.stat-chip {
  display: inline-flex;
  min-height: 38px;
  align-items: center;
  gap: 8px;
  padding: 0 14px;
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 12px;
  background: var(--ikaros-glass-fill);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 650;
  backdrop-filter: blur(16px) saturate(140%);
  -webkit-backdrop-filter: blur(16px) saturate(140%);
}

.stat-chip strong {
  color: var(--ikaros-ink);
  font-size: 15px;
  font-weight: 800;
}

.stat-chip strong.is-live {
  color: var(--ikaros-eye);
}

.stat-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ikaros-muted);
}

.stat-dot.is-live {
  background: var(--ikaros-eye);
  box-shadow: 0 0 0 4px rgba(42, 140, 138, 0.12);
}

.stat-dot.is-paused {
  background: rgba(232, 93, 142, 0.45);
}

.scheduler-panel {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .scheduler-panel {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.86);
}

.panel-shell {
  padding: 20px;
}

.panel-header,
.panel-title {
  display: flex;
  align-items: center;
}

.panel-header {
  justify-content: space-between;
  gap: 14px;
}

.panel-title {
  min-width: 0;
  gap: 10px;
}

.panel-title h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.panel-title-icon {
  display: grid;
  width: 34px;
  height: 34px;
  flex: none;
  place-items: center;
  border-radius: 11px;
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.panel-title-icon svg {
  width: 17px;
  height: 17px;
}

.panel-count {
  flex: none;
  padding: 4px 10px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 750;
}

.panel-loading {
  display: flex;
  min-height: 180px;
  align-items: center;
  justify-content: center;
  color: var(--ikaros-pink);
}

.panel-loading svg {
  width: 26px;
  height: 26px;
}

.panel-loading .is-spinning {
  animation: scheduler-spin 850ms linear infinite;
}

.panel-empty {
  display: flex;
  min-height: 150px;
  align-items: center;
  justify-content: center;
  gap: 12px;
  margin-top: 18px;
  border: 1px dashed var(--ikaros-line);
  border-radius: 16px;
  color: var(--ikaros-copy);
}

.panel-empty > svg {
  width: 22px;
  height: 22px;
  flex: none;
  color: var(--ikaros-muted);
}

.panel-empty strong {
  color: var(--ikaros-ink);
  font-size: 13px;
}

.panel-empty p {
  margin: 4px 0 0;
  color: var(--ikaros-muted);
  font-size: 12px;
}

.task-list {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}

.task-row {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto auto;
  align-items: center;
  gap: 18px;
  padding: 14px 16px 14px 20px;
  border: 1px solid var(--ikaros-line);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.42);
}

:global(.dark) .task-row {
  background: rgba(255, 255, 255, 0.04);
}

.task-row::before {
  position: absolute;
  top: 12px;
  bottom: 12px;
  left: 0;
  width: 3px;
  border-radius: 999px;
  background: var(--ikaros-eye);
  content: '';
}

.task-row.is-paused::before {
  background: rgba(23, 19, 26, 0.18);
}

:global(.dark) .task-row.is-paused::before {
  background: rgba(255, 255, 255, 0.18);
}

.task-row.is-paused .task-main,
.task-row.is-paused .task-cron,
.task-row.is-paused .task-state {
  opacity: 0.55;
}

.task-main {
  min-width: 0;
}

.task-instruction {
  margin: 0;
  overflow: hidden;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 650;
  line-height: 1.55;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-instruction.is-expanded {
  text-overflow: clip;
  white-space: pre-wrap;
  word-break: break-word;
}

.task-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
}

.task-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 650;
}

.task-chip svg {
  width: 12px;
  height: 12px;
}

.task-expand {
  border: 0;
  background: transparent;
  color: var(--ikaros-pink);
  font-size: 11px;
  font-weight: 700;
  padding: 0;
}

.task-expand:hover {
  color: var(--ikaros-pink-dark);
}

.task-cron {
  display: grid;
  gap: 5px;
  justify-items: end;
  padding-right: 18px;
  border-right: 1px solid var(--ikaros-line);
}

.task-block-label {
  color: var(--ikaros-muted);
  font-size: 10px;
  font-weight: 650;
}

.task-cron code {
  padding: 3px 8px;
  border-radius: 8px;
  background: rgba(23, 19, 26, 0.05);
  color: var(--ikaros-ink);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  font-weight: 650;
}

:global(.dark) .task-cron code {
  background: rgba(255, 255, 255, 0.07);
}

.task-state {
  display: flex;
  align-items: center;
}

.state-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.state-chip.is-live {
  color: var(--ikaros-eye);
}

.state-chip.is-paused {
  color: var(--ikaros-muted);
}

.state-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

.state-chip.is-live .state-dot {
  box-shadow: 0 0 0 4px rgba(42, 140, 138, 0.12);
}

.task-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.switch {
  position: relative;
  display: inline-flex;
  flex: none;
  cursor: pointer;
}

.switch input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
}

.switch-track {
  position: relative;
  width: 38px;
  height: 22px;
  border-radius: 999px;
  background: rgba(23, 19, 26, 0.16);
  transition: background-color 180ms ease;
}

:global(.dark) .switch-track {
  background: rgba(255, 255, 255, 0.16);
}

.switch-track::after {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(23, 19, 26, 0.22);
  content: '';
  transition: transform 180ms ease;
}

.switch input:checked + .switch-track {
  background: var(--ikaros-eye);
}

.switch input:checked + .switch-track::after {
  transform: translateX(16px);
}

.row-button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--ikaros-muted);
}

.row-button:hover {
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.row-button.is-danger:hover {
  background: rgba(198, 55, 65, 0.1);
  color: #c63741;
}

.row-button svg {
  width: 15px;
  height: 15px;
}

.modal-layer {
  position: fixed;
  z-index: 100;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(23, 19, 26, 0.24);
  backdrop-filter: blur(7px);
  -webkit-backdrop-filter: blur(7px);
}

.modal-panel {
  width: min(560px, 100%);
  --ikaros-glass-fill: rgba(255, 249, 252, 0.92);
}

:global(.dark) .modal-panel {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.94);
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 18px 20px;
  border-bottom: 1px solid var(--ikaros-line);
}

.modal-header h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.modal-close {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--ikaros-muted);
}

.modal-close:hover {
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.modal-close svg {
  width: 16px;
  height: 16px;
}

.modal-body {
  display: grid;
  gap: 16px;
  padding: 20px;
}

.field-label {
  display: block;
  margin-bottom: 8px;
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 750;
}

.field-input,
.field-textarea {
  width: 100%;
  border: 1px solid var(--ikaros-line);
  border-radius: 13px;
  background: rgba(255, 255, 255, 0.55);
  padding: 11px 13px;
  color: var(--ikaros-ink);
  font-size: 13px;
  line-height: 1.6;
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

:global(.dark) .field-input,
:global(.dark) .field-textarea {
  background: rgba(255, 255, 255, 0.06);
}

.field-textarea {
  resize: vertical;
}

.field-input.is-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.field-input:focus,
.field-textarea:focus {
  border-color: rgba(232, 93, 142, 0.45);
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.12);
}

.field-hint {
  margin: 8px 0 0;
  color: var(--ikaros-muted);
  font-size: 11px;
  line-height: 1.5;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 14px 20px;
  border-top: 1px solid var(--ikaros-line);
}

@keyframes scheduler-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 900px) {
  .task-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }

  .task-cron {
    display: none;
  }

  .task-state {
    display: none;
  }
}

@media (max-width: 640px) {
  .panel-shell {
    padding: 16px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .refresh-button .is-spinning,
  .panel-loading .is-spinning {
    animation: none;
  }

  .switch-track,
  .switch-track::after,
  .field-input,
  .field-textarea {
    transition: none;
  }
}
</style>
