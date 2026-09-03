<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Globe, Loader2, Pencil, Plus, RefreshCw, Rss, Trash2, X } from 'lucide-vue-next'

import request from '@/api/request'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'

const subs = ref<any[]>([])
const loading = ref(false)
const showDialog = ref(false)
const editingId = ref<number | null>(null)
const formData = ref({
    title: '',
    feed_url: ''
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

const loadData = async () => {
    loading.value = true
    try {
        const res = await request('/rss', { method: 'GET' })
        subs.value = res.data || []
    } catch (e) {
        console.error(e)
    } finally {
        loading.value = false
    }
}

const resetForm = () => {
    formData.value = { title: '', feed_url: '' }
    editingId.value = null
}

const closeDialog = () => {
    showDialog.value = false
    resetForm()
}

const openCreate = () => {
    resetForm()
    showDialog.value = true
}

const openEdit = (sub: any) => {
    editingId.value = sub.id
    formData.value = {
        title: sub.title || '',
        feed_url: sub.feed_url || ''
    }
    showDialog.value = true
}

const handleSave = async () => {
    if (!formData.value.title || !formData.value.feed_url) return

    const payload = {
        title: formData.value.title,
        feed_url: formData.value.feed_url
    }

    try {
        if (editingId.value) {
            await request(`/rss/${editingId.value}`, {
                method: 'PUT',
                data: payload
            })
        } else {
            await request('/rss', {
                method: 'POST',
                data: payload
            })
        }
        closeDialog()
        loadData()
    } catch (e: any) {
        alert(e?.response?.data?.detail || '操作失败')
    }
}

const handleDelete = async (id: number) => {
    if (!confirm('确定取消订阅吗？')) return
    try {
        await request(`/rss/${id}`, { method: 'DELETE' })
        loadData()
    } catch (e) {
        console.error(e)
    }
}

onMounted(() => {
    loadData()
})

const totalFeeds = computed(() => subs.value.length)
const domainCount = computed(() => {
    const hosts = new Set<string>()
    subs.value.forEach((sub) => {
        try {
            hosts.add(new URL(sub.feed_url).host)
        } catch {
            // ignore invalid url
        }
    })
    return hosts.size
})

const hostOf = (url: string) => {
    try {
        return new URL(url).host
    } catch {
        return '—'
    }
}

const avatarLetter = (title: string) => {
    const text = String(title || '').trim()
    return text ? text[0]!.toUpperCase() : 'R'
}
</script>

<template>
  <div class="ikaros-page rss-page">
    <header class="ikaros-page-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">RSS</p>
        <h1 class="ikaros-page-title">RSS 订阅源管理</h1>
        <p class="ikaros-page-description">集中管理 Ikaros 抓取的 RSS 订阅源。</p>
      </div>
      <div class="header-actions">
        <button type="button" class="ikaros-secondary-action refresh-button" :disabled="loading" title="刷新" @click="loadData">
          <RefreshCw :class="{ 'is-spinning': loading }" />
          刷新
        </button>
        <button type="button" class="ikaros-primary-action create-button" @click="openCreate">
          <Plus />
          新增订阅
        </button>
      </div>
    </header>

    <section class="metric-grid" aria-label="订阅概览">
      <LiquidGlass :radius="20" :optics="compactOptics" class="metric-card">
        <div class="metric-inner">
          <div class="metric-label">
            <span>总订阅数</span>
            <span class="metric-icon"><Rss /></span>
          </div>
          <strong class="metric-value">{{ totalFeeds }}</strong>
        </div>
      </LiquidGlass>
      <LiquidGlass :radius="20" :optics="compactOptics" class="metric-card">
        <div class="metric-inner">
          <div class="metric-label">
            <span>涉及域名</span>
            <span class="metric-icon"><Globe /></span>
          </div>
          <strong class="metric-value">{{ domainCount }}</strong>
        </div>
      </LiquidGlass>
    </section>

    <LiquidGlass :radius="24" :optics="panelOptics" class="rss-panel">
      <div class="panel-shell">
        <header class="panel-header">
          <h2>活跃订阅源</h2>
          <span class="panel-count">{{ totalFeeds }} 项</span>
        </header>

        <div v-if="loading" class="panel-loading">
          <Loader2 class="is-spinning" />
        </div>

        <div v-else-if="!subs.length" class="panel-empty">
          <Rss />
          <div>
            <strong>暂无 RSS 订阅</strong>
            <p>新增第一个订阅源，Ikaros 会开始跟踪它的更新。</p>
          </div>
        </div>

        <template v-else>
          <div class="sub-head">
            <span>名称</span>
            <span>域名</span>
            <span>链接</span>
            <span class="is-right">操作</span>
          </div>
          <div class="sub-list">
            <article v-for="sub in subs" :key="sub.id" class="sub-row">
              <div class="sub-name">
                <span class="sub-avatar">{{ avatarLetter(sub.title) }}</span>
                <strong>{{ sub.title }}</strong>
              </div>
              <span class="sub-domain">{{ hostOf(sub.feed_url) }}</span>
              <span class="sub-url" :title="sub.feed_url">{{ sub.feed_url }}</span>
              <div class="row-actions">
                <button type="button" title="编辑" @click="openEdit(sub)">
                  <Pencil />
                </button>
                <button type="button" title="删除" class="is-danger" @click="handleDelete(sub.id)">
                  <Trash2 />
                </button>
              </div>
            </article>
          </div>
        </template>
      </div>
    </LiquidGlass>

    <div v-if="showDialog" class="modal-layer" @click.self="closeDialog">
      <LiquidGlass :radius="24" :optics="panelOptics" class="modal-panel">
        <header class="modal-header">
          <h2>{{ editingId ? '编辑订阅' : '新增订阅' }}</h2>
          <button type="button" class="modal-close" title="关闭" @click="closeDialog">
            <X />
          </button>
        </header>
        <div class="modal-body">
          <div class="field-group">
            <label class="field-label" for="rss-title">订阅名称</label>
            <input
              id="rss-title"
              v-model="formData.title"
              type="text"
              class="field-input"
              placeholder="例如：极客公园"
            >
          </div>
          <div class="field-group">
            <label class="field-label" for="rss-url">RSS 链接</label>
            <textarea
              id="rss-url"
              v-model="formData.feed_url"
              rows="3"
              class="field-textarea"
              placeholder="https://..."
            />
            <p class="field-hint">请确保链接可公开访问且格式有效。</p>
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
.rss-page {
  width: min(1280px, 100%);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-actions svg,
.modal-footer svg {
  width: 16px;
  height: 16px;
}

.refresh-button .is-spinning {
  animation: rss-spin 850ms linear infinite;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 14px;
}

.metric-card {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.82);
}

:global(.dark) .metric-card {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.84);
}

.metric-inner {
  display: grid;
  gap: 10px;
  padding: 18px;
}

.metric-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 750;
}

.metric-icon {
  display: grid;
  width: 28px;
  height: 28px;
  place-items: center;
  border-radius: 9px;
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.metric-icon svg {
  width: 15px;
  height: 15px;
}

.metric-value {
  color: var(--ikaros-ink);
  font-size: 28px;
  font-weight: 800;
  letter-spacing: -0.04em;
  line-height: 1.05;
}

.rss-panel {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .rss-panel {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.86);
}

.panel-shell {
  padding: 20px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.panel-header h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.02em;
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
  animation: rss-spin 850ms linear infinite;
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

.sub-head,
.sub-row {
  display: grid;
  grid-template-columns: minmax(0, 1.2fr) 150px minmax(0, 1fr) 64px;
  align-items: center;
  gap: 14px;
}

.sub-head {
  margin-top: 18px;
  padding: 0 14px 9px;
  border-bottom: 1px solid var(--ikaros-line);
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
}

.sub-head .is-right {
  text-align: right;
}

.sub-list {
  display: grid;
}

.sub-row {
  min-height: 58px;
  padding: 9px 14px;
  border-bottom: 1px solid var(--ikaros-line);
}

.sub-row:last-child {
  border-bottom: 0;
}

.sub-name {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}

.sub-name strong {
  overflow: hidden;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sub-avatar {
  display: grid;
  width: 28px;
  height: 28px;
  flex: none;
  place-items: center;
  border: 1px solid var(--ikaros-line);
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.6);
  color: var(--ikaros-pink);
  font-size: 12px;
  font-weight: 800;
}

:global(.dark) .sub-avatar {
  background: rgba(255, 255, 255, 0.06);
}

.sub-domain {
  overflow: hidden;
  color: var(--ikaros-copy);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.sub-url {
  overflow: hidden;
  color: var(--ikaros-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 4px;
}

.row-actions button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: var(--ikaros-muted);
}

.row-actions button:hover {
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.row-actions button.is-danger:hover {
  background: rgba(198, 55, 65, 0.1);
  color: #c63741;
}

.row-actions svg {
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
  resize: none;
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

@keyframes rss-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 860px) {
  .sub-head {
    display: none;
  }

  .sub-row {
    grid-template-columns: minmax(0, 1fr) 64px;
  }

  .sub-domain {
    display: none;
  }

  .sub-url {
    grid-column: 1 / -1;
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

  .field-input,
  .field-textarea {
    transition: none;
  }
}
</style>
