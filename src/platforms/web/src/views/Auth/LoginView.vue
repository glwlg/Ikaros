<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, CalendarClock, HeartPulse, Info, Loader2, Waypoints } from 'lucide-vue-next'

import IkarosMark from '@/components/layout/IkarosMark.vue'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'
import { bootstrapAdmin, getBootstrapStatus, getCurrentUser, login, type BootstrapStatus } from '@/api/auth'
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
const checking = ref(true)
const error = ref('')
const bootstrapStatus = ref<BootstrapStatus | null>(null)

const email = ref('')
const password = ref('')
const displayName = ref('')

const bootstrapMode = computed(() => bootstrapStatus.value?.needs_bootstrap === true)

onMounted(async () => {
    const token = localStorage.getItem('access_token')
    if (token) {
        try {
            await getCurrentUser()
            await authStore.fetchUser()
            await router.push('/chat')
            return
        } catch {
            localStorage.removeItem('access_token')
        }
    }

    try {
        const response = await getBootstrapStatus()
        bootstrapStatus.value = response.data
    } catch (err: any) {
        error.value = err?.response?.data?.detail || '无法获取初始化状态'
    } finally {
        checking.value = false
    }
})

const handleSubmit = async () => {
    if (!email.value.trim() || !password.value.trim()) {
        error.value = '请输入邮箱和密码'
        return
    }

    loading.value = true
    error.value = ''
    try {
        if (bootstrapMode.value) {
            await bootstrapAdmin({
                email: email.value.trim(),
                password: password.value,
                display_name: displayName.value.trim() || undefined,
                username: email.value.split('@')[0],
            })
        }

        const response = await login(email.value.trim(), password.value)
        authStore.setToken(response.data.access_token)
        await authStore.fetchUser()
        await router.push(bootstrapMode.value && authStore.isAdmin ? '/admin/runtime' : '/chat')
    } catch (err: any) {
        error.value = err?.response?.data?.detail || (bootstrapMode.value ? '初始化失败' : '登录失败')
    } finally {
        loading.value = false
    }
}
</script>

<template>
  <div class="login-page">
    <div class="login-ambient" aria-hidden="true">
      <i class="ambient-ribbon ribbon-a" />
      <i class="ambient-ribbon ribbon-b" />
      <i class="ambient-dot dot-a" />
      <i class="ambient-dot dot-b" />
      <i class="ambient-dot dot-c" />
    </div>

    <div class="login-layout">
      <section class="login-brand">
        <div class="brand-head">
          <IkarosMark :size="46" />
          <div class="brand-copy">
            <strong>IKAROS</strong>
            <span>Agent Operations</span>
          </div>
        </div>
        <ul class="brand-features">
          <li>
            <span class="feature-icon is-pink"><Waypoints /></span>
            多渠道协作
          </li>
          <li>
            <span class="feature-icon is-teal"><CalendarClock /></span>
            自动任务
          </li>
          <li>
            <span class="feature-icon is-green"><HeartPulse /></span>
            运行可观测性
          </li>
        </ul>
      </section>

      <LiquidGlass :radius="20" :optics="panelOptics" class="login-card">
        <div class="login-card-shell">
          <div v-if="checking" class="login-loading">
            <Loader2 class="is-spinning" />
          </div>

          <template v-else>
            <header class="login-card-head">
              <p class="login-kicker">{{ bootstrapMode ? 'Bootstrap' : 'Sign In' }}</p>
              <h1>{{ bootstrapMode ? '初始化首个管理员' : '登录 Ikaros' }}</h1>
              <p class="login-sub">
                {{ bootstrapMode
                  ? '当前系统还没有管理员，完成初始化后将自动进入登录流。'
                  : '欢迎回来，请验证您的凭据。' }}
              </p>
            </header>

            <div v-if="error" class="login-error">
              {{ error }}
            </div>

            <form class="login-form" @submit.prevent="handleSubmit">
              <label v-if="bootstrapMode">
                <span>显示名称</span>
                <input
                  v-model="displayName"
                  type="text"
                  placeholder="例如：系统管理员"
                >
              </label>

              <label>
                <span>邮箱地址</span>
                <input
                  v-model="email"
                  type="email"
                  placeholder="admin@example.com"
                  required
                >
              </label>

              <label>
                <span>密码</span>
                <input
                  v-model="password"
                  type="password"
                  minlength="8"
                  placeholder="至少 8 位"
                  required
                >
              </label>

              <p v-if="bootstrapMode" class="login-init-hint">
                <Info />
                尚未创建管理员时，将在此完成首次初始化
              </p>

              <button
                type="submit"
                :disabled="loading"
                class="login-submit"
              >
                <Loader2 v-if="loading" class="is-spinning" />
                <span>{{ bootstrapMode ? '初始化并登录' : '登录' }}</span>
                <ArrowRight v-if="!loading" />
              </button>
            </form>
          </template>
        </div>
      </LiquidGlass>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  --ikaros-pink: #e85d8e;
  --ikaros-pink-dark: #c64d79;
  --ikaros-collar: #17131a;
  --ikaros-wing: #fff9fc;
  --ikaros-eye: #2a8c8a;
  --ikaros-rind: #2f7d4a;
  --ikaros-ink: #17131a;
  --ikaros-copy: #665b64;
  --ikaros-muted: #8b7f88;
  --ikaros-line: rgba(23, 19, 26, 0.12);
  --ikaros-glass-behind: #f0edf2;
  --ikaros-glass-wallpaper-image:
    radial-gradient(circle at 15% 50%, rgba(232, 93, 142, 0.06) 0%, transparent 50%),
    radial-gradient(circle at 85% 30%, rgba(42, 140, 138, 0.05) 0%, transparent 50%),
    linear-gradient(135deg, #fff9fc 0%, #f0edf2 100%);
  --ikaros-glass-wallpaper-position: center;
  --ikaros-glass-wallpaper-repeat: no-repeat;
  --ikaros-glass-wallpaper-size: cover;
  position: relative;
  display: flex;
  width: 100%;
  min-height: 100vh;
  align-items: center;
  justify-content: center;
  overflow-x: hidden;
  overflow-y: auto;
  background-color: var(--ikaros-glass-behind);
  background-image: var(--ikaros-glass-wallpaper-image);
  background-position: var(--ikaros-glass-wallpaper-position);
  background-repeat: var(--ikaros-glass-wallpaper-repeat);
  background-size: var(--ikaros-glass-wallpaper-size);
  background-attachment: fixed;
  color: var(--ikaros-ink);
  padding: 24px;
  -webkit-overflow-scrolling: touch;
}

:global(.dark) .login-page {
  --ikaros-ink: #f8f2f6;
  --ikaros-copy: #d8ced5;
  --ikaros-muted: #b8abb4;
  --ikaros-line: rgba(255, 255, 255, 0.12);
  --ikaros-glass-behind: #17131a;
  --ikaros-glass-wallpaper-image:
    radial-gradient(circle at 15% 50%, rgba(232, 93, 142, 0.09) 0%, transparent 50%),
    radial-gradient(circle at 85% 30%, rgba(42, 140, 138, 0.06) 0%, transparent 50%),
    linear-gradient(135deg, #17131a 0%, #221a21 100%);
}

.login-ambient {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
}

.ambient-ribbon {
  position: absolute;
  left: -50vw;
  width: 200vw;
  height: 100vh;
  background: linear-gradient(90deg, transparent, rgba(232, 93, 142, 0.08), transparent);
  transform: rotate(var(--ribbon-rotate, -15deg));
  animation: ribbon-drift 34s ease-in-out infinite alternate;
}

.ribbon-a {
  top: -20%;
}

.ribbon-b {
  top: 40%;
  opacity: 0.55;
  animation-duration: 46s;
  --ribbon-rotate: 15deg;
}

.ambient-dot {
  position: absolute;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--ikaros-eye);
  box-shadow: 0 0 10px rgba(42, 140, 138, 0.75);
  opacity: 0.4;
  animation: dot-float 8s ease-in-out infinite;
}

.dot-a { top: 20%; left: 15%; }
.dot-b { top: 60%; left: 80%; animation-delay: -2s; }
.dot-c { top: 85%; left: 35%; animation-delay: -5s; }

.login-layout {
  position: relative;
  z-index: 1;
  display: grid;
  width: min(1120px, 100%);
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-items: center;
  gap: 72px;
}

@keyframes ribbon-drift {
  from { transform: rotate(var(--ribbon-rotate, -15deg)) translateX(-16%); }
  to { transform: rotate(var(--ribbon-rotate, -15deg)) translateX(16%); }
}

@keyframes dot-float {
  0%, 100% { transform: translateY(0); opacity: 0.28; }
  50% { transform: translateY(-16px); opacity: 0.5; }
}

.login-brand {
  display: grid;
  gap: 46px;
}

.brand-head {
  display: flex;
  align-items: center;
  gap: 16px;
}

.brand-copy {
  display: grid;
  gap: 5px;
}

.brand-copy strong {
  color: var(--ikaros-ink);
  font-size: 36px;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1;
}

.brand-copy span {
  color: var(--ikaros-copy);
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.1em;
}

.brand-features {
  display: grid;
  gap: 20px;
  margin: 0;
  border-top: 1px solid var(--ikaros-line);
  padding: 28px 0 0;
  list-style: none;
}

.brand-features li {
  display: flex;
  align-items: center;
  gap: 14px;
  color: var(--ikaros-ink);
  font-size: 15px;
  font-weight: 650;
}

.feature-icon {
  display: grid;
  width: 34px;
  height: 34px;
  flex: none;
  place-items: center;
  border-radius: 50%;
}

.feature-icon svg {
  width: 16px;
  height: 16px;
}

.feature-icon.is-pink { background: rgba(232, 93, 142, 0.1); color: var(--ikaros-pink); }
.feature-icon.is-teal { background: rgba(42, 140, 138, 0.1); color: var(--ikaros-eye); }
.feature-icon.is-green { background: rgba(47, 125, 74, 0.1); color: var(--ikaros-rind); }

.login-card {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.74);
  width: min(430px, 100%);
  justify-self: center;
  animation: card-float 7s ease-in-out infinite;
}

:global(.dark) .login-card {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.82);
}

.login-card-shell {
  padding: 30px;
}

.login-loading {
  display: flex;
  min-height: 280px;
  align-items: center;
  justify-content: center;
  color: var(--ikaros-pink);
}

.login-loading svg {
  width: 26px;
  height: 26px;
}

.login-card-head {
  display: grid;
  gap: 8px;
}

.login-kicker {
  margin: 0;
  color: var(--ikaros-pink);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.login-card-head h1 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.025em;
}

.login-sub {
  margin: 0;
  color: var(--ikaros-muted);
  font-size: 13px;
  line-height: 1.6;
}

.login-error {
  margin-top: 18px;
  border: 1px solid rgba(198, 55, 65, 0.22);
  border-radius: 12px;
  background: rgba(198, 55, 65, 0.07);
  padding: 10px 13px;
  color: #c63741;
  font-size: 12px;
  font-weight: 650;
  line-height: 1.55;
}

@keyframes card-float {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-8px); }
}

.login-form {
  display: grid;
  gap: 15px;
  margin-top: 22px;
}

.login-form label {
  display: grid;
  gap: 7px;
  color: var(--ikaros-ink);
  font-size: 12px;
  font-weight: 750;
}

.login-form input {
  width: 100%;
  min-height: 44px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.55);
  padding: 10px 13px;
  color: var(--ikaros-ink);
  font-family: inherit;
  font-size: 14px;
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease;
}

:global(.dark) .login-form input { background: rgba(255, 255, 255, 0.06); }

.login-form input:focus {
  border-color: rgba(232, 93, 142, 0.5);
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.12);
}

.login-init-hint {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  margin: 0;
  border-radius: 10px;
  background: rgba(42, 140, 138, 0.08);
  padding: 9px 11px;
  color: var(--ikaros-eye);
  font-size: 11.5px;
  line-height: 1.55;
}

.login-init-hint svg {
  width: 14px;
  height: 14px;
  flex: none;
  margin-top: 1px;
}

.login-submit {
  display: inline-flex;
  width: 100%;
  min-height: 46px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  margin-top: 4px;
  border: none;
  border-radius: 12px;
  background: var(--ikaros-collar);
  box-shadow:
    0 12px 26px rgba(23, 19, 26, 0.22),
    inset 0 1px 0 rgba(255, 255, 255, 0.16);
  color: #fff9fc;
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  transition: transform 160ms ease, box-shadow 160ms ease;
  -webkit-tap-highlight-color: transparent;
}

.login-submit:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow:
    0 16px 30px rgba(23, 19, 26, 0.26),
    inset 0 1px 0 rgba(255, 255, 255, 0.16);
}

.login-submit:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.login-submit svg {
  width: 15px;
  height: 15px;
}

.is-spinning { animation: login-spin 850ms linear infinite; }

@keyframes login-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 1023px) {
  .login-layout {
    grid-template-columns: 1fr;
    gap: 0;
  }

  .login-brand {
    display: none;
  }
}

@media (max-width: 480px) {
  .login-page {
    padding: 16px;
  }

  .login-card-shell {
    padding: 24px 20px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .ambient-ribbon,
  .ambient-dot,
  .login-card {
    animation: none !important;
  }

  .is-spinning { animation: none; }
}
</style>
