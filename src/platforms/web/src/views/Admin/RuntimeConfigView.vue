<script setup lang="ts">
import axios from 'axios'
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
    Bot,
    CheckCircle2,
    FileText,
    Eye,
    Loader2,
    RadioTower,
    RefreshCw,
    Save,
    Settings2,
    ShieldUser,
    Sparkles,
} from 'lucide-vue-next'

import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import {
    generateRuntimeDoc,
    getRuntimeSnapshot,
    patchRuntimeSnapshot,
    type RuntimeGeneratePayload,
    type RuntimePatchPayload,
    type RuntimeSnapshot,
} from '@/api/runtime'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const authStore = useAuthStore()

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

const loading = ref(false)
const saving = ref(false)
const generatingSoul = ref(false)
const generatingUser = ref(false)
const errorText = ref('')
const successText = ref('')
const restartRequired = ref(false)
const corsInput = ref('')

const form = ref<RuntimeSnapshot | null>(null)
const adminPassword = ref('')
const adminIdsInput = ref('')
const soulBrief = ref('')
const userBrief = ref('')

const featureDescriptions: Record<string, string> = {
    web_chat_uploads: '允许在 Web 对话中上传文件和图片',
    web_chat_tts: '允许在 Web 对话中使用文字转语音',
    admin_console: '启用 Web 管理后台入口',
    routing_model_enabled: '回复前调用 Routing 模型判断请求类型并筛选 Skill；关闭后由主模型直接处理',
}

const describeFeature = (name: string) =>
    featureDescriptions[name] || '控制对应的运行时功能'

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

const cloneSnapshot = (payload: RuntimeSnapshot) =>
    JSON.parse(JSON.stringify(payload)) as RuntimeSnapshot

const hydrate = (payload: RuntimeSnapshot) => {
    form.value = cloneSnapshot(payload)
    adminIdsInput.value = (payload.channels.admin_user_ids || []).join('\n')
    corsInput.value = (payload.cors_allowed_origins || []).join('\n')
    restartRequired.value = false
}

const load = async () => {
    loading.value = true
    errorText.value = ''
    try {
        const response = await getRuntimeSnapshot()
        hydrate(response.data)
    } catch (error) {
        errorText.value = parseErrorMessage(error, '运行配置加载失败')
    } finally {
        loading.value = false
    }
}

const checklist = computed(() => {
    if (!form.value) return []
    const status = form.value.status
    return [
        { label: '管理员绑定', ok: status.admin_bound },
        { label: 'Primary 模型', ok: status.primary_ready },
        { label: 'Routing 模型', ok: status.routing_ready },
        { label: 'SOUL.MD', ok: status.soul_ready },
        { label: 'USER.md', ok: status.user_ready },
        { label: '渠道配置', ok: status.channels_ready },
    ]
})

const parseAdminUserIds = () =>
    adminIdsInput.value
        .split(/[\n,]/)
        .map(item => item.trim())
        .filter(Boolean)

const primaryModelKey = computed(() => form.value?.model_status.primary.model_key || '')
const canGenerateDocs = computed(() => Boolean(form.value?.model_status.primary.ready && primaryModelKey.value))

const save = async () => {
    if (!form.value) return
    saving.value = true
    errorText.value = ''
    successText.value = ''
    try {
        const payload: RuntimePatchPayload = {
            admin_user: {
                email: form.value.admin_user.email.trim(),
                username: form.value.admin_user.username?.trim() || '',
                display_name: form.value.admin_user.display_name?.trim() || '',
                ...(adminPassword.value.trim() ? { password: adminPassword.value } : {}),
            },
            docs: {
                soul_content: form.value.docs.soul_content,
                user_content: form.value.docs.user_content,
            },
            channels: {
                admin_user_ids: parseAdminUserIds(),
                telegram: {
                    enabled: form.value.channels.telegram.enabled,
                    bot_token: form.value.channels.telegram.bot_token,
                },
                discord: {
                    enabled: form.value.channels.discord.enabled,
                    bot_token: form.value.channels.discord.bot_token,
                },
                dingtalk: {
                    enabled: form.value.channels.dingtalk.enabled,
                    client_id: form.value.channels.dingtalk.client_id,
                    client_secret: form.value.channels.dingtalk.client_secret,
                },
                weixin: {
                    enabled: form.value.channels.weixin.enabled,
                    base_url: form.value.channels.weixin.base_url,
                    cdn_base_url: form.value.channels.weixin.cdn_base_url,
                },
                web: {
                    enabled: form.value.channels.web.enabled,
                },
            },
            features: form.value.features,
            cors_allowed_origins: corsInput.value
                .split('\n')
                .map(item => item.trim())
                .filter(Boolean),
            memory_provider: form.value.memory.provider,
        }
        const response = await patchRuntimeSnapshot(payload)
        hydrate(response.data.snapshot)
        adminPassword.value = ''
        restartRequired.value = response.data.restart_required
        successText.value = response.data.restart_required
            ? '运行配置已保存，凭证相关改动需要重启 ikaros core。'
            : '运行配置已保存'
        await authStore.fetchUser()
    } catch (error) {
        errorText.value = parseErrorMessage(error, '保存运行配置失败')
    } finally {
        saving.value = false
    }
}

const generateDoc = async (payload: RuntimeGeneratePayload) => {
    if (!form.value) return
    errorText.value = ''
    successText.value = ''
    const isSoul = payload.kind === 'soul'
    if (isSoul) {
        generatingSoul.value = true
    } else {
        generatingUser.value = true
    }
    try {
        const response = await generateRuntimeDoc(payload)
        if (response.data.kind === 'soul') {
            form.value.docs.soul_content = response.data.content
        } else {
            form.value.docs.user_content = response.data.content
        }
        successText.value = `${response.data.kind.toUpperCase()} 文档已生成，确认后记得保存。`
    } catch (error) {
        errorText.value = parseErrorMessage(error, 'AI 生成文档失败')
    } finally {
        if (isSoul) {
            generatingSoul.value = false
        } else {
            generatingUser.value = false
        }
    }
}

onMounted(load)
</script>

<template>
  <div class="ikaros-page runtime-page">
    <header class="ikaros-page-header runtime-header">
      <div class="ikaros-page-heading">
        <p class="ikaros-page-kicker">Admin · Runtime</p>
        <h1 class="ikaros-page-title">运行配置</h1>
        <p class="ikaros-page-description">首次安装就在这里完成管理员、文档、渠道和运行项的配置，再进入模型配置补齐或调整模型目录。</p>
      </div>
      <div class="runtime-actions">
        <button type="button" class="ikaros-secondary-action" :disabled="loading" @click="router.push('/admin/models')">
          <Settings2 />
          去模型配置
        </button>
        <button type="button" class="ikaros-primary-action" :disabled="saving || loading || !form" @click="save">
          <Loader2 v-if="saving" class="is-spinning" />
          <Save v-else />
          保存运行配置
        </button>
      </div>
    </header>

    <div v-if="checklist.length" class="runtime-checks">
      <span
        v-for="item in checklist"
        :key="item.label"
        class="runtime-check"
        :class="{ ok: item.ok }"
      >
        <i aria-hidden="true" />
        {{ item.label }}
      </span>
    </div>

    <div v-if="errorText" class="runtime-notice is-danger">{{ errorText }}</div>
    <div v-if="successText" class="runtime-notice is-success">{{ successText }}</div>
    <div v-if="restartRequired && form" class="runtime-notice is-restart">
      <RefreshCw />
      {{ form.restart_notice }}
    </div>

    <div v-if="loading" class="runtime-loading ikaros-surface">
      <Loader2 class="is-spinning" />
      正在加载运行配置
    </div>

    <template v-else-if="form">
      <div class="runtime-top-grid">
        <LiquidGlass :radius="24" :optics="panelOptics" class="runtime-card admin-card">
          <div class="card-shell">
            <div class="card-title-row">
              <span class="card-icon is-pink"><ShieldUser /></span>
              <h2>管理员与访问</h2>
            </div>

          <div class="admin-form-grid">
            <label>
              <span>邮箱</span>
              <input v-model="form.admin_user.email" type="email">
            </label>
            <label>
              <span>用户名</span>
              <input v-model="form.admin_user.username" type="text">
            </label>
            <label>
              <span>显示名称</span>
              <input v-model="form.admin_user.display_name" type="text">
            </label>
            <label>
              <span>重设密码</span>
              <div class="password-field">
                <input v-model="adminPassword" type="password" minlength="8" placeholder="留空表示不修改">
                <Eye class="h-4 w-4" />
              </div>
            </label>
          </div>

          <label class="full-field">
            <span>ADMIN_USER_IDS（每行一个 ID）</span>
            <textarea v-model="adminIdsInput" placeholder="每行一个 ID，也支持逗号分隔" />
          </label>

            <div class="info-strip">
              <CheckCircle2 />
              当前 Web 管理员用户 ID：<strong>{{ form.admin_user.current_admin_user_id }}</strong>
            </div>
          </div>
        </LiquidGlass>

        <div class="runtime-side">
          <LiquidGlass :radius="24" :optics="panelOptics" class="runtime-card sequence-card">
            <div class="card-shell">
              <h2>配置推荐顺序</h2>
            <ol>
              <li class="done"><span>1</span>先完成模型配置并补齐 Primary / Routing <CheckCircle2 class="h-4 w-4" /></li>
              <li class="done"><span>2</span>生成或编辑 SOUL / USER 文档 <CheckCircle2 class="h-4 w-4" /></li>
              <li class="done"><span>3</span>开启你需要的渠道并填写凭证 <CheckCircle2 class="h-4 w-4" /></li>
              <li><span>4</span>保存本页运行配置 <i /></li>
              <li><span>5</span>返回控制面板开始使用系统 <i /></li>
              </ol>
            </div>
          </LiquidGlass>

          <LiquidGlass :radius="24" :optics="panelOptics" class="runtime-card model-status-card">
            <div class="card-shell">
              <div class="side-card-head">
                <div class="card-title-row compact">
                  <span class="card-icon is-teal"><Bot /></span>
                  <h2>模型状态</h2>
                </div>
                <button type="button" @click="router.push('/admin/models')">查看详情</button>
              </div>
            <div class="model-status-table">
              <div>
                <span>Primary 模型</span>
                <strong><i />{{ form.model_status.primary.model_key || '未配置' }}</strong>
              </div>
              <div>
                <span>Routing 模型</span>
                <strong><i />{{ form.model_status.routing.model_key || '未配置' }}</strong>
              </div>
              </div>
            </div>
          </LiquidGlass>
        </div>
      </div>

      <div class="doc-grid">
        <LiquidGlass :radius="24" :optics="panelOptics" class="runtime-card doc-card">
          <div class="card-shell">
            <div class="doc-head">
              <div class="card-title-row compact">
                <span class="card-icon is-pink"><Sparkles /></span>
                <div>
                  <h2>IKAROS SOUL.md</h2>
                  <p>文件路径：{{ form.docs.soul_path }}</p>
                </div>
              </div>
              <button type="button" :disabled="generatingSoul || !canGenerateDocs" @click="generateDoc({ kind: 'soul', brief: soulBrief, current_content: form.docs.soul_content, model_key: primaryModelKey })">
                <Loader2 v-if="generatingSoul" class="is-spinning" />
                <Sparkles v-else />
                AI 生成 SOUL
              </button>
            </div>
          <label>
            <span>AI 生成补充要求（可选）</span>
            <textarea v-model="soulBrief" class="brief-field" placeholder="例如：性格设定、价值观、行为准则、核心能力、安全边界等..." />
          </label>
            <textarea v-model="form.docs.soul_content" class="doc-editor" />
            <footer>字数：{{ form.docs.soul_content.length }}</footer>
          </div>
        </LiquidGlass>

        <LiquidGlass :radius="24" :optics="panelOptics" class="runtime-card doc-card">
          <div class="card-shell">
            <div class="doc-head">
              <div class="card-title-row compact">
                <span class="card-icon is-pink"><FileText /></span>
                <div>
                  <h2>管理员 USER.md</h2>
                  <p>文件路径：{{ form.docs.user_path }}</p>
                </div>
              </div>
              <button type="button" :disabled="generatingUser || !canGenerateDocs" @click="generateDoc({ kind: 'user', brief: userBrief, current_content: form.docs.user_content, model_key: primaryModelKey })">
                <Loader2 v-if="generatingUser" class="is-spinning" />
                <Sparkles v-else />
                AI 生成 USER
              </button>
            </div>
          <label>
            <span>AI 生成补充要求（可选）</span>
            <textarea v-model="userBrief" class="brief-field" placeholder="例如：我希望称呼我阿伟、沟通风格、注意事项、响应偏好等..." />
          </label>
            <textarea v-model="form.docs.user_content" class="doc-editor" />
            <footer>字数：{{ form.docs.user_content.length }}</footer>
          </div>
        </LiquidGlass>
      </div>

      <LiquidGlass :radius="24" :optics="panelOptics" class="runtime-card channels-card">
        <div class="card-shell">
          <div class="card-title-row">
            <span class="card-icon is-pink"><RadioTower /></span>
            <div>
              <h2>渠道与运行项</h2>
              <p class="card-subtitle">开关控制是否启用；凭证/连接参数决定能否真正连通。</p>
            </div>
          </div>

        <div class="channel-grid">
          <article class="channel-item" :class="{ enabled: form.channels.telegram.enabled, ready: form.channels.telegram.configured }">
            <header>
              <div class="channel-identity">
                <strong>Telegram</strong>
                <span class="status-pill" :class="form.channels.telegram.configured ? 'ok' : 'warn'">
                  {{ form.channels.telegram.configured ? '凭证已配置' : '缺少凭证' }}
                </span>
              </div>
              <label class="switch">
                <input v-model="form.channels.telegram.enabled" type="checkbox">
                <span class="slider" />
                <em>{{ form.channels.telegram.enabled ? '启用' : '关闭' }}</em>
              </label>
            </header>
            <label class="field">
              <span>Bot Token</span>
              <input v-model="form.channels.telegram.bot_token" type="password" autocomplete="off" placeholder="123456:AA...">
            </label>
          </article>

          <article class="channel-item" :class="{ enabled: form.channels.discord.enabled, ready: form.channels.discord.configured }">
            <header>
              <div class="channel-identity">
                <strong>Discord</strong>
                <span class="status-pill" :class="form.channels.discord.configured ? 'ok' : 'warn'">
                  {{ form.channels.discord.configured ? '凭证已配置' : '缺少凭证' }}
                </span>
              </div>
              <label class="switch">
                <input v-model="form.channels.discord.enabled" type="checkbox">
                <span class="slider" />
                <em>{{ form.channels.discord.enabled ? '启用' : '关闭' }}</em>
              </label>
            </header>
            <label class="field">
              <span>Bot Token</span>
              <input v-model="form.channels.discord.bot_token" type="password" autocomplete="off" placeholder="Bot token">
            </label>
          </article>

          <article class="channel-item" :class="{ enabled: form.channels.dingtalk.enabled, ready: form.channels.dingtalk.configured }">
            <header>
              <div class="channel-identity">
                <strong>DingTalk</strong>
                <span class="status-pill" :class="form.channels.dingtalk.configured ? 'ok' : 'warn'">
                  {{ form.channels.dingtalk.configured ? '凭证已配置' : '缺少凭证' }}
                </span>
              </div>
              <label class="switch">
                <input v-model="form.channels.dingtalk.enabled" type="checkbox">
                <span class="slider" />
                <em>{{ form.channels.dingtalk.enabled ? '启用' : '关闭' }}</em>
              </label>
            </header>
            <div class="field-grid">
              <label class="field">
                <span>Client ID</span>
                <input v-model="form.channels.dingtalk.client_id" type="text" autocomplete="off">
              </label>
              <label class="field">
                <span>Client Secret</span>
                <input v-model="form.channels.dingtalk.client_secret" type="password" autocomplete="off">
              </label>
            </div>
          </article>

          <article class="channel-item" :class="{ enabled: form.channels.weixin.enabled, ready: form.channels.weixin.configured }">
            <header>
              <div class="channel-identity">
                <strong>Weixin</strong>
                <span class="status-pill" :class="form.channels.weixin.configured ? 'ok' : 'warn'">
                  {{ form.channels.weixin.configured ? '连接参数就绪' : '缺少连接参数' }}
                </span>
              </div>
              <label class="switch">
                <input v-model="form.channels.weixin.enabled" type="checkbox">
                <span class="slider" />
                <em>{{ form.channels.weixin.enabled ? '启用' : '关闭' }}</em>
              </label>
            </header>
            <div class="field-grid">
              <label class="field">
                <span>Base URL</span>
                <input v-model="form.channels.weixin.base_url" type="text" autocomplete="off" placeholder="https://...">
              </label>
              <label class="field">
                <span>CDN Base URL</span>
                <input v-model="form.channels.weixin.cdn_base_url" type="text" autocomplete="off" placeholder="https://...">
              </label>
            </div>
          </article>

          <article class="channel-item web-channel" :class="{ enabled: form.channels.web.enabled, ready: true }">
            <header>
              <div class="channel-identity">
                <strong>Web</strong>
                <span class="status-pill ok">内置渠道 · 无需额外凭证</span>
              </div>
              <label class="switch">
                <input v-model="form.channels.web.enabled" type="checkbox">
                <span class="slider" />
                <em>{{ form.channels.web.enabled ? '启用' : '关闭' }}</em>
              </label>
            </header>
            <p class="channel-note">Web 控制台对话与后台共用，开启后用户可在「聊天对话」使用 AI。</p>
          </article>
          </div>
        </div>
      </LiquidGlass>

      <LiquidGlass :radius="24" :optics="panelOptics" class="runtime-card options-panel">
        <div class="card-shell options-grid">
          <section class="option-group">
            <h2>功能开关</h2>
            <label v-for="name in Object.keys(form.features)" :key="name" class="toggle-row">
              <span>{{ name }}<small>{{ describeFeature(name) }}</small></span>
              <input v-model="form.features[name]" type="checkbox">
            </label>
          </section>

          <section class="option-group">
            <h2>CORS Allowlist</h2>
            <p>每行一个 Origin，生产环境不要使用宽泛通配。</p>
            <textarea v-model="corsInput" placeholder="https://app.example.com&#10;http://127.0.0.1:8764" />
          </section>

          <section class="option-group">
            <h2>Memory Provider</h2>
            <p>这里只切换 provider，不在 Web 里直接改密钥。</p>
            <select v-model="form.memory.provider">
              <option v-for="provider in form.memory.providers" :key="provider" :value="provider">{{ provider }}</option>
            </select>
            <pre>{{ JSON.stringify(form.memory.active_settings, null, 2) }}</pre>
          </section>

          <section class="option-group">
            <h2>配置路径</h2>
            <div class="path-list">
              <div><strong>.env</strong><span>{{ form.paths.env }}</span></div>
              <div><strong>models.json</strong><span>{{ form.paths.models }}</span></div>
              <div><strong>memory.json</strong><span>{{ form.paths.memory }}</span></div>
            </div>
          </section>
        </div>
      </LiquidGlass>
    </template>
  </div>
</template>

<style scoped>
.runtime-page {
  gap: 22px;
}

.runtime-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 10px;
}

.runtime-actions svg { width: 16px; height: 16px; }

.is-spinning { animation: runtime-spin 850ms linear infinite; }

.runtime-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.runtime-check {
  display: inline-flex;
  min-height: 28px;
  align-items: center;
  gap: 7px;
  padding: 0 12px;
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 999px;
  background: rgba(255, 249, 252, 0.72);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.6);
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 750;
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

:global(.dark) .runtime-check { background: rgba(43, 34, 40, 0.72); }

.runtime-check i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: rgba(23, 19, 26, 0.22);
}

:global(.dark) .runtime-check i { background: rgba(255, 255, 255, 0.25); }
.runtime-check.ok { color: var(--ikaros-rind); }

.runtime-check.ok i {
  background: var(--ikaros-rind);
  box-shadow: 0 0 0 3px rgba(47, 125, 74, 0.12);
}

.runtime-notice {
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 12px;
  padding: 11px 14px;
  font-size: 12px;
  font-weight: 650;
}

.runtime-notice svg { width: 15px; height: 15px; flex: none; }
.runtime-notice.is-danger { border: 1px solid rgba(198, 55, 65, 0.2); background: rgba(198, 55, 65, 0.07); color: #c63741; }
.runtime-notice.is-success { border: 1px solid rgba(47, 125, 74, 0.2); background: rgba(47, 125, 74, 0.08); color: var(--ikaros-rind); }
.runtime-notice.is-restart { border: 1px solid rgba(232, 93, 142, 0.22); background: rgba(232, 93, 142, 0.08); color: var(--ikaros-pink-dark); }
:global(.dark) .runtime-notice.is-restart { color: #f3a1c1; }

.runtime-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 18px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.runtime-loading svg { width: 16px; height: 16px; }

.runtime-top-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.55fr) minmax(340px, 0.95fr);
  gap: 18px;
  align-items: start;
}

.runtime-side {
  display: grid;
  gap: 18px;
}

.runtime-card {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .runtime-card { --ikaros-glass-fill: rgba(43, 34, 40, 0.86); }

.card-shell {
  padding: 20px;
}

.card-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.card-title-row.compact {
  gap: 10px;
}

.card-title-row h2,
.sequence-card h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.card-icon {
  display: grid;
  width: 36px;
  height: 36px;
  flex: none;
  place-items: center;
  border-radius: 12px;
}

.card-icon svg { width: 18px; height: 18px; }
.card-icon.is-pink { background: rgba(232, 93, 142, 0.1); color: var(--ikaros-pink); }
.card-icon.is-teal { background: rgba(42, 140, 138, 0.1); color: var(--ikaros-eye); }

.admin-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px 26px;
  margin-top: 20px;
}

.admin-card label,
.doc-card label {
  display: grid;
  gap: 7px;
}

.admin-card label span,
.doc-card label span {
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 750;
}

.admin-card input,
.admin-card textarea,
.doc-card textarea,
.channel-item input,
.option-group textarea,
.option-group select {
  width: 100%;
  border: 1px solid var(--ikaros-line);
  border-radius: 11px !important;
  padding: 10px 13px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--ikaros-ink);
  font-size: 13px;
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

:global(.dark) :is(.admin-card input, .admin-card textarea, .doc-card textarea, .channel-item input, .option-group textarea, .option-group select) {
  background: rgba(255, 255, 255, 0.06);
}

:is(.admin-card input, .admin-card textarea, .doc-card textarea, .channel-item input, .option-group textarea, .option-group select):focus {
  border-color: rgba(232, 93, 142, 0.45);
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.1);
}

.password-field {
  position: relative;
}

.password-field svg {
  position: absolute;
  top: 50%;
  right: 13px;
  width: 15px;
  height: 15px;
  color: var(--ikaros-muted);
  transform: translateY(-50%);
}

.full-field {
  margin-top: 16px;
}

.full-field textarea {
  min-height: 110px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.info-strip {
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

.info-strip svg { width: 15px; height: 15px; flex: none; }
.info-strip strong { font-weight: 750; }

.sequence-card ol {
  display: grid;
  gap: 15px;
  margin: 18px 0 0;
  padding: 0;
  list-style: none;
}

.sequence-card li {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) 18px;
  align-items: center;
  gap: 12px;
  color: var(--ikaros-copy);
  font-size: 12px;
}

.sequence-card li span {
  display: grid;
  width: 20px;
  height: 20px;
  place-items: center;
  border-radius: 50%;
  background: rgba(23, 19, 26, 0.07);
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 800;
}

:global(.dark) .sequence-card li span { background: rgba(255, 255, 255, 0.08); }

.sequence-card li.done span {
  background: var(--ikaros-pink);
  color: #fff;
}

.sequence-card li.done svg {
  width: 15px;
  height: 15px;
  color: var(--ikaros-rind);
}

.sequence-card li i {
  width: 15px;
  height: 15px;
  border: 1px solid var(--ikaros-line);
  border-radius: 50%;
}

.side-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.side-card-head button {
  height: 32px;
  border: 1px solid rgba(232, 93, 142, 0.28);
  border-radius: 10px;
  background: rgba(232, 93, 142, 0.08);
  padding: 0 12px;
  color: var(--ikaros-pink-dark);
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
  transition: background 160ms ease;
}

:global(.dark) .side-card-head button { color: #f3a1c1; }
.side-card-head button:hover { background: rgba(232, 93, 142, 0.14); }

.model-status-table {
  display: grid;
  gap: 10px;
  margin-top: 18px;
}

.model-status-table div {
  display: grid;
  grid-template-columns: 110px minmax(0, 1fr);
  align-items: center;
  gap: 12px;
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.42);
  padding: 11px 13px;
}

:global(.dark) .model-status-table div { background: rgba(255, 255, 255, 0.05); }

.model-status-table span {
  color: var(--ikaros-muted);
  font-size: 12px;
  font-weight: 700;
}

.model-status-table strong {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  overflow-wrap: anywhere;
  color: var(--ikaros-ink);
  font-size: 12px;
  font-weight: 700;
}

.model-status-table i {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--ikaros-rind);
  box-shadow: 0 0 0 3px rgba(47, 125, 74, 0.12);
}

.doc-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.doc-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 0.5px solid var(--ikaros-glass-hairline);
  padding-bottom: 16px;
}

.doc-head p {
  margin: 5px 0 0;
  overflow-wrap: anywhere;
  color: var(--ikaros-muted);
  font-size: 11px;
}

.doc-head button {
  display: inline-flex;
  height: 32px;
  flex: none;
  align-items: center;
  gap: 7px;
  border: 1px solid rgba(42, 140, 138, 0.3);
  border-radius: 10px;
  background: rgba(42, 140, 138, 0.08);
  padding: 0 12px;
  color: var(--ikaros-eye);
  font-size: 12px;
  font-weight: 750;
  cursor: pointer;
  transition: background 160ms ease;
}

.doc-head button svg { width: 14px; height: 14px; }
.doc-head button:hover:not(:disabled) { background: rgba(42, 140, 138, 0.14); }
.doc-head button:disabled { cursor: not-allowed; opacity: 0.5; }

.doc-card label {
  margin-top: 16px;
}

.brief-field {
  min-height: 72px;
  resize: vertical;
}

.doc-editor {
  min-height: 260px;
  margin-top: 12px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px !important;
  line-height: 1.7;
  resize: vertical;
}

.doc-card footer {
  margin-top: 10px;
  color: var(--ikaros-muted);
  font-size: 11px;
}

.card-subtitle {
  margin: 4px 0 0;
  color: var(--ikaros-muted);
  font-size: 12px;
  font-weight: 500;
}

.channel-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-top: 18px;
}

.channel-item {
  display: grid;
  align-content: start;
  gap: 14px;
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.42);
  padding: 16px;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

:global(.dark) .channel-item { background: rgba(255, 255, 255, 0.05); }

.channel-item.enabled {
  border-color: rgba(232, 93, 142, 0.32);
  box-shadow: 0 10px 26px rgba(232, 93, 142, 0.08);
}

.channel-item:not(.enabled) {
  opacity: 0.78;
}

.channel-item header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.channel-identity {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.channel-item strong {
  color: var(--ikaros-ink);
  font-size: 14px;
  font-weight: 800;
}

.status-pill {
  display: inline-flex;
  width: fit-content;
  align-items: center;
  border-radius: 999px;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 700;
}

.status-pill.ok {
  background: rgba(47, 125, 74, 0.1);
  color: var(--ikaros-rind);
}

.status-pill.warn {
  background: rgba(200, 120, 32, 0.12);
  color: #b86717;
}

.switch {
  position: relative;
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  user-select: none;
}

.switch input {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  padding: 0;
  border: 0;
  cursor: pointer;
  opacity: 0;
}

.switch .slider {
  position: relative;
  width: 38px;
  height: 22px;
  flex: none;
  border-radius: 999px;
  background: rgba(23, 19, 26, 0.16);
  transition: background 160ms ease;
}

:global(.dark) .switch .slider { background: rgba(255, 255, 255, 0.18); }

.switch .slider::after {
  content: '';
  position: absolute;
  top: 3px;
  left: 3px;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 1px 3px rgba(23, 19, 26, 0.28);
  transition: transform 160ms ease;
}

.switch input:checked + .slider {
  background: var(--ikaros-pink);
}

.switch input:checked + .slider::after {
  transform: translateX(16px);
}

.switch em {
  min-width: 2em;
  color: var(--ikaros-muted);
  font-size: 12px;
  font-style: normal;
  font-weight: 700;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.field {
  display: grid;
  gap: 6px;
}

.field span {
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 700;
}

.channel-note {
  margin: 0;
  color: var(--ikaros-muted);
  font-size: 12px;
  line-height: 1.6;
}

.options-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 26px;
}

.option-group {
  display: grid;
  align-content: start;
  gap: 12px;
}

.option-group h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 800;
}

.option-group p {
  margin: 0;
  color: var(--ikaros-muted);
  font-size: 11px;
  line-height: 1.55;
}

.toggle-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 0.5px solid var(--ikaros-glass-hairline);
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.42);
  padding: 11px 13px;
  cursor: pointer;
}

:global(.dark) .toggle-row { background: rgba(255, 255, 255, 0.05); }

.toggle-row span {
  display: grid;
  gap: 3px;
  min-width: 0;
  color: var(--ikaros-ink);
  font-size: 12px;
  font-weight: 700;
}

.toggle-row small {
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 500;
  line-height: 1.5;
}

.toggle-row input {
  width: 16px;
  height: 16px;
  flex: none;
  accent-color: var(--ikaros-pink);
  cursor: pointer;
}

.option-group textarea {
  min-height: 150px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
  resize: vertical;
}

.option-group pre {
  max-height: 170px;
  overflow: auto;
  margin: 0;
  border-radius: 11px;
  background: var(--ikaros-collar);
  color: rgba(255, 249, 252, 0.92);
  padding: 13px;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 11px;
  line-height: 1.6;
}

.path-list {
  display: grid;
  gap: 11px;
}

.path-list div {
  display: grid;
  gap: 4px;
}

.path-list strong {
  color: var(--ikaros-ink);
  font-size: 12px;
}

.path-list span {
  overflow-wrap: anywhere;
  color: var(--ikaros-muted);
  font-size: 12px;
}

@keyframes runtime-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1500px) {
  .runtime-top-grid,
  .channel-grid,
  .options-grid {
    grid-template-columns: 1fr 1fr;
  }
}

@media (max-width: 980px) {
  .runtime-top-grid,
  .doc-grid,
  .channel-grid,
  .options-grid,
  .admin-form-grid,
  .field-grid {
    grid-template-columns: 1fr;
  }

  .runtime-actions,
  .doc-head {
    flex-wrap: wrap;
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning { animation: none; }
}
</style>
