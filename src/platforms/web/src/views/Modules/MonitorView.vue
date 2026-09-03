<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Activity, ListChecks, Loader2, Pencil, Plus, Trash2, X } from 'lucide-vue-next'

import request from '@/api/request'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'

const items = ref<string[]>([])
const loading = ref(false)
const showDialog = ref(false)
const editingIndex = ref<number | null>(null)
const formData = ref({ item: '' })

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

const loadData = async () => {
    loading.value = true
    try {
        const res = await request('/monitor', { method: 'GET' })
        items.value = res.data || []
    } catch (e) {
        console.error(e)
    } finally {
        loading.value = false
    }
}

const openCreate = () => {
    editingIndex.value = null
    formData.value = { item: '' }
    showDialog.value = true
}

const closeDialog = () => {
    showDialog.value = false
    editingIndex.value = null
    formData.value = { item: '' }
}

const openEdit = (index: number, text: string) => {
    editingIndex.value = index
    formData.value = { item: text }
    showDialog.value = true
}

const handleSave = async () => {
    if (!formData.value.item) return
    try {
        if (editingIndex.value !== null) {
            // Delete old, then add new (checklist is index-based, no PUT)
            await request(`/monitor/${editingIndex.value + 1}`, { method: 'DELETE' })
            await request('/monitor', { method: 'POST', data: formData.value })
        } else {
            await request('/monitor', { method: 'POST', data: formData.value })
        }
        closeDialog()
        loadData()
    } catch (e: any) {
        alert(e?.response?.data?.detail || '操作失败')
    }
}

const handleDelete = async (index: number) => {
    if (!confirm('确定删除该检查项吗？')) return
    try {
        await request(`/monitor/${index + 1}`, { method: 'DELETE' })
        loadData()
    } catch (e) {
        console.error(e)
    }
}

onMounted(() => {
    loadData()
})

const itemCount = computed(() => items.value.length)
</script>

<template>
  <div class="ikaros-page monitor-page">
    <header class="ikaros-page-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Heartbeat Checklist</p>
        <h1 class="ikaros-page-title">心跳巡检</h1>
        <p class="ikaros-page-description">自动周期性执行你配置的检查指令，并在发现状态异常时主动汇报。</p>
      </div>
      <button type="button" class="ikaros-primary-action monitor-create" @click="openCreate">
        <Plus />
        添加检查项
      </button>
    </header>

    <div class="monitor-layout">
      <LiquidGlass :radius="24" :optics="panelOptics" class="monitor-panel checklist-panel">
        <div class="panel-shell">
          <header class="panel-header">
            <div class="panel-title">
              <span class="panel-title-icon"><ListChecks /></span>
              <h2>巡检清单</h2>
            </div>
            <span class="panel-count">{{ itemCount }} 项</span>
          </header>

          <div v-if="loading" class="panel-loading">
            <Loader2 class="is-spinning" />
          </div>

          <template v-else>
            <div v-if="!items.length" class="panel-empty">
              <Activity />
              <div>
                <strong>暂无巡检指令</strong>
                <p>添加第一条检查指令，Ikaros 会在心跳巡检时执行它。</p>
              </div>
            </div>

            <div v-else class="checklist">
              <article v-for="(item, index) in items" :key="index" class="check-row">
                <span class="check-index">{{ index + 1 }}</span>
                <p class="check-text">{{ item }}</p>
                <div class="check-actions">
                  <button type="button" title="编辑" @click="openEdit(index, item)">
                    <Pencil />
                  </button>
                  <button type="button" title="删除" class="is-danger" @click="handleDelete(index)">
                    <Trash2 />
                  </button>
                </div>
              </article>
            </div>

            <button type="button" class="check-add" @click="openCreate">
              <span class="check-add-icon"><Plus /></span>
              点击添加新的巡检指令…
            </button>
          </template>
        </div>
      </LiquidGlass>

      <LiquidGlass :radius="24" :optics="compactOptics" class="monitor-panel summary-panel">
        <div class="panel-shell">
          <span class="summary-label">检查项</span>
          <strong class="summary-value">{{ itemCount }}</strong>
          <p class="summary-detail">当前清单中已配置的巡检指令</p>
        </div>
      </LiquidGlass>
    </div>

    <div v-if="showDialog" class="modal-layer" @click.self="closeDialog">
      <LiquidGlass :radius="24" :optics="panelOptics" class="modal-panel">
        <header class="modal-header">
          <h2>{{ editingIndex !== null ? '编辑检查项' : '添加检查项' }}</h2>
          <button type="button" class="modal-close" title="关闭" @click="closeDialog">
            <X />
          </button>
        </header>
        <div class="modal-body">
          <label class="field-label" for="monitor-item">检查项指令</label>
          <textarea
            id="monitor-item"
            v-model="formData.item"
            rows="4"
            class="field-textarea"
            placeholder="例如：检查是否有超过 2 小时未处理的任务"
          />
          <p class="field-hint">使用自然语言描述 Ikaros 在每次心跳时需要执行的检查逻辑。</p>
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
.monitor-page {
  width: min(1280px, 100%);
}

.monitor-create svg,
.modal-footer svg {
  width: 16px;
  height: 16px;
}

.monitor-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 20px;
  align-items: start;
}

.monitor-panel {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .monitor-panel {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.86);
}

.panel-shell {
  padding: 22px;
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
  animation: monitor-spin 850ms linear infinite;
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

.checklist {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}

.check-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 13px 14px;
  border: 1px solid var(--ikaros-line);
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.42);
}

:global(.dark) .check-row {
  background: rgba(255, 255, 255, 0.04);
}

.check-index {
  display: grid;
  width: 30px;
  height: 30px;
  flex: none;
  place-items: center;
  border-radius: 50%;
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
  font-size: 13px;
  font-weight: 800;
}

.check-text {
  min-width: 0;
  flex: 1;
  margin: 5px 0 0;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 550;
  line-height: 1.6;
  word-break: break-word;
}

.check-actions {
  display: flex;
  flex: none;
  gap: 4px;
}

.check-actions button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--ikaros-muted);
}

.check-actions button:hover {
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.check-actions button.is-danger:hover {
  background: rgba(198, 55, 65, 0.1);
  color: #c63741;
}

.check-actions svg {
  width: 15px;
  height: 15px;
}

.check-add {
  display: flex;
  width: 100%;
  min-height: 54px;
  align-items: center;
  gap: 11px;
  margin-top: 12px;
  padding: 0 14px;
  border: 1px dashed var(--ikaros-line);
  border-radius: 16px;
  background: transparent;
  color: var(--ikaros-muted);
  font-size: 13px;
  font-weight: 600;
}

.check-add:hover {
  border-color: rgba(232, 93, 142, 0.4);
  color: var(--ikaros-pink);
}

.check-add-icon {
  display: grid;
  width: 28px;
  height: 28px;
  flex: none;
  place-items: center;
  border: 1px solid var(--ikaros-line);
  border-radius: 50%;
}

.check-add:hover .check-add-icon {
  border-color: rgba(232, 93, 142, 0.4);
}

.check-add-icon svg {
  width: 14px;
  height: 14px;
}

.summary-panel .panel-shell {
  display: grid;
  gap: 6px;
}

.summary-label {
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 750;
}

.summary-value {
  color: var(--ikaros-ink);
  font-size: 34px;
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 1.05;
}

.summary-detail {
  margin: 0;
  color: var(--ikaros-muted);
  font-size: 12px;
  line-height: 1.5;
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
  width: min(520px, 100%);
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
  padding: 20px;
}

.field-label {
  display: block;
  margin-bottom: 8px;
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 750;
}

.field-textarea {
  width: 100%;
  resize: none;
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

:global(.dark) .field-textarea {
  background: rgba(255, 255, 255, 0.06);
}

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

@keyframes monitor-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1024px) {
  .monitor-layout {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 640px) {
  .panel-shell {
    padding: 17px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .panel-loading .is-spinning {
    animation: none;
  }

  .field-textarea {
    transition: none;
  }
}
</style>
