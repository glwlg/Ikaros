<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
    AudioLines,
    Bot,
    CircleStop,
    Loader2,
    MessageSquareText,
    Mic,
    PanelLeftClose,
    PanelLeftOpen,
    Paperclip,
    Plus,
    RefreshCw,
    Search,
    SendHorizonal,
    Volume2,
    X
} from 'lucide-vue-next'

import {
    createSession,
    fetchChatFileBlob,
    generateTts,
    getSessionMessages,
    listSessions,
    postSessionEvent,
    streamSessionEvents,
    type ChatAttachment,
    type ChatMessage,
    type ChatSession,
    uploadChatFile,
} from '@/api/web-chat'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'

const sessions = ref<ChatSession[]>([])
const messages = ref<ChatMessage[]>([])
const currentSessionId = ref('')
const composer = ref('')
const sessionQuery = ref('')
const loadingSessions = ref(false)
const sending = ref(false)
const streamStatus = ref<'idle' | 'connecting' | 'connected' | 'reconnecting' | 'error'>('idle')
const statusNote = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const streamAbort = ref<AbortController | null>(null)
const lastEventId = ref(0)
const recording = ref(false)
const recorder = ref<MediaRecorder | null>(null)
const recorderStream = ref<MediaStream | null>(null)
const messagesEl = ref<HTMLElement | null>(null)
const statusTimer = ref<number | null>(null)
const waitingAssistant = ref(false)
const showSessions = ref(false)
const showCommandPicker = ref(false)

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

const filteredCommands = computed(() => {
    const query = composer.value.trim().toLowerCase()
    if (!query.startsWith('/')) return commandEntries
    const search = query.slice(1).toLowerCase()
    if (!search) return commandEntries
    return commandEntries.filter(cmd =>
        cmd.label.toLowerCase().includes(search) ||
        cmd.text.toLowerCase().includes(search)
    )
})

watch(composer, (val) => {
    showCommandPicker.value = val.trim().startsWith('/')
})

const selectCommand = (cmd: { label: string; text: string }) => {
    composer.value = cmd.text + ' '
    showCommandPicker.value = false
}

const commandEntries = [
    { label: '/start', text: '/start', desc: '初始化会话' },
    { label: '/help', text: '/help', desc: '查看可用命令' },
    { label: '/model', text: '/model', desc: '切换推理模型' },
    { label: '/usage', text: '/usage', desc: '查看配额统计' },
    { label: '/task', text: '/task recent', desc: '转为后台任务' },
    { label: '/heartbeat', text: '/heartbeat list', desc: '查看巡检清单' },
    { label: '/skills', text: '/skills', desc: '查看技能列表' },
    { label: '/wxbind', text: '/wxbind', desc: '绑定微信账号' },
]

const attachmentKind = (attachment: ChatAttachment) =>
    String(attachment.kind || '').trim().toLowerCase()

const attachmentMimeType = (attachment: ChatAttachment) =>
    String(attachment.mime_type || '').trim().toLowerCase()

const attachmentName = (attachment: ChatAttachment) =>
    String(attachment.name || '').trim().toLowerCase()

const normalizeAttachment = (attachment: Record<string, unknown>): ChatAttachment => ({
    id: String(attachment.id || attachment.file_id || ''),
    file_id: String(attachment.file_id || attachment.id || ''),
    kind: String(attachment.kind || ''),
    name: String(attachment.name || ''),
    mime_type: String(attachment.mime_type || 'application/octet-stream'),
    size: Number(attachment.size || 0),
})

const isImageAttachment = (attachment: ChatAttachment) => {
    const kind = attachmentKind(attachment)
    const mimeType = attachmentMimeType(attachment)
    const name = attachmentName(attachment)
    return (
        kind === 'image' ||
        mimeType.startsWith('image/') ||
        /\.(avif|bmp|gif|jpe?g|png|svg|webp)$/i.test(name)
    )
}

const isAudioAttachment = (attachment: ChatAttachment) => {
    const kind = attachmentKind(attachment)
    const mimeType = attachmentMimeType(attachment)
    const name = attachmentName(attachment)
    return (
        kind === 'audio' ||
        kind === 'voice' ||
        mimeType.startsWith('audio/') ||
        /\.(aac|flac|m4a|mp3|ogg|opus|wav|webm)$/i.test(name)
    )
}

const attachmentBlobUrls = ref<Record<string, string>>({})
const loadingAttachmentIds = new Set<string>()

const attachmentFileId = (attachment: ChatAttachment) =>
    String(attachment.file_id || attachment.id || '').trim()

const attachmentObjectUrl = (attachment: ChatAttachment) =>
    attachmentBlobUrls.value[attachmentFileId(attachment)] || ''

const cacheAttachmentObjectUrl = (fileId: string, url: string) => {
    const safeFileId = String(fileId || '').trim()
    if (!safeFileId || !url) return
    const current = attachmentBlobUrls.value[safeFileId]
    if (current && current !== url) {
        URL.revokeObjectURL(current)
    }
    attachmentBlobUrls.value = {
        ...attachmentBlobUrls.value,
        [safeFileId]: url,
    }
}

const ensureAttachmentUrl = async (attachment: ChatAttachment) => {
    const fileId = attachmentFileId(attachment)
    if (!fileId) return ''
    const cached = attachmentBlobUrls.value[fileId]
    if (cached) return cached
    if (loadingAttachmentIds.has(fileId)) return ''

    loadingAttachmentIds.add(fileId)
    try {
        const blob = await fetchChatFileBlob(fileId)
        const url = URL.createObjectURL(blob)
        cacheAttachmentObjectUrl(fileId, url)
        return url
    } catch (error) {
        console.error('Failed to load chat attachment', error)
        return ''
    } finally {
        loadingAttachmentIds.delete(fileId)
    }
}

const primeMessageAttachments = (message?: ChatMessage | null) => {
    if (!message?.attachments?.length) return
    for (const attachment of message.attachments) {
        void ensureAttachmentUrl(attachment)
    }
}

const primeMessagesAttachments = (items: ChatMessage[]) => {
    for (const message of items) {
        primeMessageAttachments(message)
    }
}

const revokeAttachmentUrls = () => {
    for (const url of Object.values(attachmentBlobUrls.value)) {
        URL.revokeObjectURL(url)
    }
    attachmentBlobUrls.value = {}
}

const openAttachment = async (attachment: ChatAttachment) => {
    const url = attachmentObjectUrl(attachment) || await ensureAttachmentUrl(attachment)
    if (!url) return
    const opened = window.open(url, '_blank', 'noopener,noreferrer')
    if (opened) return

    const link = document.createElement('a')
    link.href = url
    link.target = '_blank'
    link.rel = 'noopener noreferrer'
    if (attachment.name) {
        link.download = attachment.name
    }
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
}

const normalizedQuery = computed(() => sessionQuery.value.trim().toLowerCase())

const visibleSessions = computed(() => {
    const ordered = [...sessions.value].sort((a, b) => {
        const left = String(a.updated_at || a.last_message_at || a.created_at || '')
        const right = String(b.updated_at || b.last_message_at || b.created_at || '')
        return right.localeCompare(left)
    })

    return ordered.filter(session => {
        if (normalizedQuery.value) {
            const haystack = `${session.title || ''} ${session.preview || ''}`.toLowerCase()
            if (!haystack.includes(normalizedQuery.value)) return false
        }
        const isEmpty = !session.message_count && !String(session.preview || '').trim()
        if (!isEmpty) return true
        return session.id === currentSessionId.value
    })
})

const currentSession = computed(() =>
    sessions.value.find(item => item.id === currentSessionId.value) || null
)

const statusBadge = computed(() => {
    if (streamStatus.value === 'reconnecting') {
        return '重连中'
    }
    if (streamStatus.value === 'error') {
        return '连接异常'
    }
    if (statusNote.value) {
        return statusNote.value
    }
    if (waitingAssistant.value) {
        return '等待 Ikaros 响应'
    }
    return ''
})

const setStatus = (text: string, timeoutMs = 0) => {
    if (statusTimer.value) {
        window.clearTimeout(statusTimer.value)
        statusTimer.value = null
    }
    statusNote.value = text
    if (timeoutMs > 0) {
        statusTimer.value = window.setTimeout(() => {
            statusNote.value = ''
            statusTimer.value = null
        }, timeoutMs)
    }
}

const scrollToBottom = async () => {
    await nextTick()
    await new Promise(resolve => requestAnimationFrame(resolve))
    if (messagesEl.value) {
        messagesEl.value.scrollTop = messagesEl.value.scrollHeight
    }
}

const mergeMessage = (message: ChatMessage) => {
    const index = messages.value.findIndex(item => item.id === message.id)
    if (index >= 0) {
        const currentMessage = messages.value[index]
        if (!currentMessage) return
        messages.value[index] = {
            ...currentMessage,
            ...message,
            attachments: message.attachments || currentMessage.attachments || [],
            actions: message.actions || currentMessage.actions || [],
            meta: message.meta || currentMessage.meta || {},
        }
        primeMessageAttachments(messages.value[index])
    } else {
        messages.value.push(message)
        primeMessageAttachments(message)
    }
}

const updateSessionSummary = (message: ChatMessage) => {
    const session = sessions.value.find(item => item.id === message.session_id)
    if (!session) return
    session.preview = message.content || session.preview
    session.updated_at = message.updated_at || new Date().toISOString()
    session.last_message_at = message.updated_at || session.last_message_at
    session.message_count = Math.max(session.message_count || 0, messages.value.length)
    if (message.role === 'user' && (!session.title || session.title === '新对话') && message.content) {
        session.title = message.content.slice(0, 48)
    }
}

const attachAudioToMessage = (messageId: string, attachment: Record<string, unknown>) => {
    const target = messages.value.find(item => item.id === messageId)
    if (!target) return
    const normalizedAttachment = normalizeAttachment(attachment)
    const nextAttachments = [...(target.attachments || [])]
    const exists = nextAttachments.some(item => item.file_id === normalizedAttachment.file_id)
    if (!exists) {
        nextAttachments.push(normalizedAttachment)
        target.attachments = nextAttachments
        void ensureAttachmentUrl(normalizedAttachment)
    }
}

const ensureActiveSession = async () => {
    if (currentSessionId.value) return currentSessionId.value

    const created = await createSession({})
    sessions.value = [created, ...sessions.value.filter(item => item.id !== created.id)]
    await openSession(created.id)
    return created.id
}

const handleStreamEvent = (event: { id: number; type: string; payload: Record<string, unknown> }) => {
    lastEventId.value = Math.max(lastEventId.value, Number(event.id || 0))
    streamStatus.value = 'connected'

    if (event.type === 'task_status') {
        setStatus(String(event.payload.action || '处理中'))
        return
    }

    if (event.type === 'error') {
        waitingAssistant.value = false
        streamStatus.value = 'error'
        setStatus(String(event.payload.message || '处理失败'))
        return
    }

    if (event.type === 'done') {
        waitingAssistant.value = false
        setStatus(String(event.payload.text || '已完成'), 2400)
        return
    }

    if (event.type === 'attachment_ready' || event.type === 'audio_ready') {
        const messageId = String(event.payload.message_id || '')
        const attachment = event.payload.attachment as Record<string, unknown> | undefined
        if (messageId && attachment) {
            attachAudioToMessage(messageId, attachment)
        }
        return
    }

    const message = event.payload.message as ChatMessage | undefined
    if (!message) return

    mergeMessage(message)
    updateSessionSummary(message)
    if (message.role === 'assistant') {
        waitingAssistant.value = false
        setStatus('', 0)
    }
    scrollToBottom()
}

const startStream = (sessionId: string) => {
    streamAbort.value?.abort()
    const controller = new AbortController()
    streamAbort.value = controller
    streamStatus.value = 'connecting'

    const run = async () => {
        while (!controller.signal.aborted && currentSessionId.value === sessionId) {
            try {
                await streamSessionEvents(sessionId, lastEventId.value, handleStreamEvent, controller.signal)
                streamStatus.value = 'connected'
            } catch (error) {
                if (controller.signal.aborted) break
                console.error(error)
                streamStatus.value = 'reconnecting'
                setStatus('连接中断，正在重连')
                await new Promise(resolve => window.setTimeout(resolve, 1000))
            }
        }
    }

    void run()
}

const openSession = async (sessionId: string) => {
    currentSessionId.value = sessionId
    lastEventId.value = 0
    waitingAssistant.value = false
    showSessions.value = false
    const response = await getSessionMessages(sessionId)
    messages.value = response.items || []
    primeMessagesAttachments(messages.value)
    await scrollToBottom()
    startStream(sessionId)
}

const ensureInitialSession = async () => {
    loadingSessions.value = true
    try {
        sessions.value = await listSessions()
        const firstSession = visibleSessions.value[0]
        if (!currentSessionId.value && firstSession) {
            await openSession(firstSession.id)
        } else if (!firstSession) {
            currentSessionId.value = ''
            messages.value = []
        }
    } finally {
        loadingSessions.value = false
    }
}

const createNewSession = async () => {
    const created = await createSession({})
    sessions.value = [created, ...sessions.value.filter(item => item.id !== created.id)]
    await openSession(created.id)
}

const sendEvent = async (payload: Record<string, unknown>) => {
    const sessionId = await ensureActiveSession()
    if (!sessionId) return
    const response = await postSessionEvent(sessionId, payload)
    if (response.message) {
        mergeMessage(response.message as ChatMessage)
        updateSessionSummary(response.message as ChatMessage)
        waitingAssistant.value = true
        setStatus('等待 Ikaros 响应')
        await scrollToBottom()
    }
}

const sendText = async () => {
    const text = composer.value.trim()
    if (!text) return
    sending.value = true
    try {
        await sendEvent({
            type: text.startsWith('/') ? 'command' : 'message_text',
            text,
        })
        composer.value = ''
    } finally {
        sending.value = false
    }
}

const openFilePicker = () => fileInput.value?.click()

const sendFile = async (file: File, isVoice = false) => {
    const sessionId = await ensureActiveSession()
    if (!sessionId) return
    const uploaded = await uploadChatFile(file, sessionId)
    await sendEvent({
        type: isVoice ? 'message_voice' : 'message_file',
        file_id: uploaded.id,
        file_name: uploaded.name,
        file_size: uploaded.size,
        mime_type: uploaded.mime_type,
        caption: '',
    })
}

const handleFileSelection = async (event: Event) => {
    const input = event.target as HTMLInputElement
    const files = Array.from(input.files || [])
    for (const file of files) {
        await sendFile(file, false)
    }
    input.value = ''
}

const toggleRecord = async () => {
    if (recording.value && recorder.value) {
        recorder.value.stop()
        return
    }

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const chunks: BlobPart[] = []
    recorderStream.value = stream
    const mediaRecorder = new MediaRecorder(stream)
    recorder.value = mediaRecorder
    recording.value = true
    setStatus('录音中')

    mediaRecorder.ondataavailable = event => {
        if (event.data.size > 0) {
            chunks.push(event.data)
        }
    }

    mediaRecorder.onstop = async () => {
        recording.value = false
        setStatus('上传语音中')
        const blob = new Blob(chunks, { type: mediaRecorder.mimeType || 'audio/webm' })
        const voiceFile = new File([blob], `voice-${Date.now()}.webm`, {
            type: mediaRecorder.mimeType || 'audio/webm',
        })
        recorderStream.value?.getTracks().forEach(track => track.stop())
        recorderStream.value = null
        await sendFile(voiceFile, true)
    }

    mediaRecorder.start()
}

const runMenuAction = async (callbackData: string) => {
    await sendEvent({
        type: 'menu_action',
        callback_data: callbackData,
    })
}

const playMessage = async (message: ChatMessage) => {
    const existingAudio = (message.attachments || []).find(isAudioAttachment)
    if (existingAudio) {
        const audioUrl = attachmentObjectUrl(existingAudio) || await ensureAttachmentUrl(existingAudio)
        if (!audioUrl) return
        const audio = new Audio(audioUrl)
        await audio.play()
        return
    }
    const sessionId = await ensureActiveSession()
    if (!sessionId) return
    const result = await generateTts(sessionId, message.id)
    mergeMessage(result.message)
    const audioUrl = await ensureAttachmentUrl(result.attachment)
    if (!audioUrl) return
    const audio = new Audio(audioUrl)
    await audio.play()
}

const onDrop = async (event: DragEvent) => {
    event.preventDefault()
    const files = Array.from(event.dataTransfer?.files || [])
    for (const file of files) {
        await sendFile(file, false)
    }
}

const insertCommandPrefix = () => {
    composer.value = '/'
}

const parseTime = (value: unknown) => {
    const raw = String(value || '').trim()
    if (!raw) return null
    const date = new Date(raw)
    if (Number.isNaN(date.getTime())) return null
    return date
}

const formatTime = (value: unknown) => {
    const date = parseTime(value)
    if (!date) return ''
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

const formatSessionTime = (value: unknown) => {
    const date = parseTime(value)
    if (!date) return ''
    const now = new Date()
    const sameDay = date.toDateString() === now.toDateString()
    if (sameDay) return formatTime(date)
    const yesterday = new Date(now)
    yesterday.setDate(now.getDate() - 1)
    if (date.toDateString() === yesterday.toDateString()) return '昨天'
    return `${date.getMonth() + 1}月${date.getDate()}日`
}

const formatDateTime = (value: unknown) => {
    const date = parseTime(value)
    if (!date) return '-'
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
    })
}

onMounted(async () => {
    await ensureInitialSession()
})

onBeforeUnmount(() => {
    if (statusTimer.value) {
        window.clearTimeout(statusTimer.value)
    }
    streamAbort.value?.abort()
    recorderStream.value?.getTracks().forEach(track => track.stop())
    revokeAttachmentUrls()
})
</script>

<template>
  <div class="chat-page">
    <header class="chat-header">
      <div>
        <p class="ikaros-page-kicker">Chat Workbench</p>
        <h1 class="chat-title">对话工作台</h1>
      </div>
      <p class="chat-subtitle">与 Ikaros 对话，支持文本、命令、语音和文件。</p>
    </header>

    <div class="chat-workbench">
      <div
        v-if="showSessions"
        class="sessions-scrim"
        @click="showSessions = false"
      />

      <LiquidGlass
        as="aside"
        :radius="22"
        :optics="panelOptics"
        class="chat-panel sessions-panel"
        :class="{ 'is-open': showSessions }"
      >
        <div class="panel-fill sessions-inner">
          <div class="sessions-top">
            <label class="session-search">
              <Search />
              <input v-model="sessionQuery" type="search" placeholder="搜索会话…">
            </label>
            <button type="button" class="icon-button" title="刷新会话列表" @click="ensureInitialSession">
              <RefreshCw />
            </button>
          </div>

          <button type="button" class="new-session-button" @click="createNewSession">
            <Plus />
            新建会话
          </button>

          <div class="sessions-list">
            <div v-if="loadingSessions" class="sessions-loading">
              <Loader2 class="is-spinning" />
              正在加载会话
            </div>

            <button
              v-for="session in visibleSessions"
              :key="session.id"
              type="button"
              class="session-item"
              :class="{ 'is-active': session.id === currentSessionId }"
              @click="openSession(session.id)"
            >
              <div class="session-item-head">
                <strong>{{ session.title || '新对话' }}</strong>
                <time>{{ formatSessionTime(session.updated_at || session.last_message_at || session.created_at) }}</time>
              </div>
              <p>{{ session.preview || '等待第一条消息' }}</p>
              <div class="session-item-foot">
                <span
                  v-if="session.id === currentSessionId && streamStatus === 'connected'"
                  class="live-flag"
                >
                  <span class="live-dot" />
                  Live
                </span>
                <span v-else />
                <span class="session-count">
                  <MessageSquareText />
                  {{ session.message_count || 0 }}
                </span>
              </div>
            </button>

            <div v-if="!loadingSessions && !visibleSessions.length" class="sessions-empty">
              {{ normalizedQuery ? '没有匹配的会话。' : '还没有会话，点击上方“新建会话”开始。' }}
            </div>
          </div>
        </div>
      </LiquidGlass>

      <LiquidGlass
        as="section"
        :radius="22"
        :optics="panelOptics"
        class="chat-panel canvas-panel"
        @drop="onDrop"
        @dragover.prevent
      >
        <div class="panel-fill canvas-inner">
          <header class="canvas-header">
            <div class="canvas-heading">
              <button
                type="button"
                class="icon-button sessions-toggle"
                title="会话列表"
                @click="showSessions = !showSessions"
              >
                <PanelLeftOpen v-if="!showSessions" />
                <PanelLeftClose v-else />
              </button>
              <div class="canvas-title">
                <h2>
                  <span>{{ currentSession?.title || '准备开始新的对话' }}</span>
                  <span v-if="streamStatus === 'connected'" class="active-badge">
                    <span class="live-dot" />
                    Active
                  </span>
                </h2>
                <p>{{ currentSession ? '当前会话已就绪' : '新建会话后即可开始对话' }}</p>
              </div>
            </div>
            <div class="canvas-header-actions">
              <span v-if="statusBadge" class="stream-chip" :class="{ 'is-error': streamStatus === 'error' }">
                <span class="stream-dot" />
                {{ statusBadge }}
              </span>
              <span class="command-hint">
                <MessageSquareText />
                输入 / 使用命令
              </span>
            </div>
          </header>

          <div ref="messagesEl" class="messages-area">
            <div v-if="!messages.length" class="messages-empty">
              <div class="empty-card">
                <span class="empty-icon"><AudioLines /></span>
                <h3>开始新的对话</h3>
                <p>支持文本、命令、语音和文件。输入 / 使用命令，或点击“新建会话”开始。</p>
              </div>
            </div>

            <div v-else class="messages-list">
              <div
                v-for="message in messages"
                :key="message.id"
                class="message-row"
                :class="message.role === 'user' ? 'is-user' : 'is-assistant'"
              >
                <span v-if="message.role !== 'user'" class="ai-avatar"><Bot /></span>
                <div class="message-stack">
                  <div class="message-meta">
                    <span>{{ message.role === 'user' ? '你' : 'Ikaros' }}</span>
                    <time>{{ formatTime(message.created_at) }}</time>
                  </div>

                  <div class="message-bubble">
                    <div v-if="message.content" class="message-text">{{ message.content }}</div>

                    <div v-if="message.attachments?.length" class="attachment-list">
                      <div
                        v-for="attachment in message.attachments"
                        :key="`${message.id}-${attachment.file_id}`"
                        class="attachment-card"
                      >
                        <button
                          v-if="isImageAttachment(attachment) && attachmentObjectUrl(attachment)"
                          type="button"
                          class="attachment-image"
                          @click="openAttachment(attachment)"
                        >
                          <img
                            :src="attachmentObjectUrl(attachment)"
                            :alt="attachment.name || '图片附件'"
                            loading="lazy"
                          >
                        </button>

                        <div
                          v-else-if="isImageAttachment(attachment)"
                          class="attachment-loading"
                        >
                          正在加载图片…
                        </div>

                        <div class="attachment-body">
                          <audio
                            v-if="isAudioAttachment(attachment) && attachmentObjectUrl(attachment)"
                            :src="attachmentObjectUrl(attachment)"
                            controls
                            preload="metadata"
                            class="attachment-audio"
                          />

                          <div
                            v-else-if="isAudioAttachment(attachment)"
                            class="attachment-loading is-compact"
                          >
                            正在加载音频…
                          </div>

                          <div class="attachment-row">
                            <div class="attachment-file">
                              <strong>{{ attachment.name }}</strong>
                              <span>{{ attachment.mime_type }}</span>
                            </div>
                            <button
                              type="button"
                              class="attachment-open"
                              @click="openAttachment(attachment)"
                            >
                              打开
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>

                    <div v-if="message.actions?.length" class="action-list">
                      <div
                        v-for="(row, rowIndex) in message.actions"
                        :key="`${message.id}-row-${rowIndex}`"
                        class="action-row"
                      >
                        <button
                          v-for="action in row"
                          :key="action.callback_data"
                          type="button"
                          class="action-pill"
                          @click="runMenuAction(action.callback_data)"
                        >
                          {{ action.text }}
                        </button>
                      </div>
                    </div>

                    <div v-if="message.role === 'assistant' && message.content" class="message-tools">
                      <button type="button" class="tts-button" @click="playMessage(message)">
                        <Volume2 />
                        朗读
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <footer class="canvas-footer">
            <div v-if="showCommandPicker && filteredCommands.length" class="command-picker">
              <div class="command-picker-head">
                <span>可用命令</span>
                <button type="button" title="关闭" @click="showCommandPicker = false">
                  <X />
                </button>
              </div>
              <div class="command-picker-grid">
                <button
                  v-for="cmd in filteredCommands"
                  :key="cmd.text"
                  type="button"
                  class="command-option"
                  @click="selectCommand(cmd)"
                >
                  <span>{{ cmd.label }}</span>
                  <small>{{ cmd.desc }}</small>
                </button>
              </div>
            </div>

            <div class="composer">
              <textarea
                v-model="composer"
                rows="3"
                placeholder="输入指令，或输入 '/' 唤出命令菜单…"
                @keydown.enter.exact.prevent="sendText"
              />
              <div class="composer-toolbar">
                <div class="composer-tools">
                  <button type="button" class="tool-button" title="发送文件" @click="openFilePicker">
                    <Paperclip />
                  </button>
                  <button
                    type="button"
                    class="tool-button"
                    :class="{ 'is-recording': recording }"
                    :title="recording ? '停止录音' : '语音输入'"
                    @click="toggleRecord"
                  >
                    <component :is="recording ? CircleStop : Mic" />
                  </button>
                  <button type="button" class="command-chip" @click="insertCommandPrefix">
                    / 命令
                  </button>
                  <input ref="fileInput" type="file" class="file-input" multiple @change="handleFileSelection">
                </div>

                <button
                  type="button"
                  class="send-button"
                  :disabled="sending || !composer.trim()"
                  @click="sendText"
                >
                  <Loader2 v-if="sending" class="is-spinning" />
                  <SendHorizonal v-else />
                  发送
                </button>
              </div>
            </div>
            <p class="composer-note">IKAROS AI 可能会产生不准确的信息，请核实关键数据。</p>
          </footer>
        </div>
      </LiquidGlass>

      <LiquidGlass
        as="aside"
        :radius="22"
        :optics="panelOptics"
        class="chat-panel info-panel"
      >
        <div class="panel-fill info-inner">
          <section class="info-section">
            <h3>会话元数据</h3>
            <dl class="meta-list">
              <div>
                <dt>会话标题</dt>
                <dd>{{ currentSession?.title || '未命名会话' }}</dd>
              </div>
              <div>
                <dt>创建时间</dt>
                <dd>{{ formatDateTime(currentSession?.created_at) }}</dd>
              </div>
              <div>
                <dt>最后更新</dt>
                <dd>{{ formatDateTime(currentSession?.updated_at || currentSession?.last_message_at) }}</dd>
              </div>
              <div>
                <dt>消息数</dt>
                <dd>{{ messages.length }}</dd>
              </div>
              <div>
                <dt>会话 ID</dt>
                <dd class="is-mono">{{ currentSession?.id || '-' }}</dd>
              </div>
            </dl>
          </section>

          <section class="info-section">
            <h3>快捷指令</h3>
            <div class="command-list">
              <button
                v-for="cmd in commandEntries.slice(0, 5)"
                :key="cmd.text"
                type="button"
                class="command-item"
                @click="selectCommand(cmd)"
              >
                <span>{{ cmd.label }}</span>
                <small>{{ cmd.desc }}</small>
              </button>
            </div>
          </section>
        </div>
      </LiquidGlass>
    </div>
  </div>
</template>

<style scoped>
.chat-page {
  display: grid;
  height: calc(100vh - 154px);
  min-height: 0;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 16px;
  overflow: hidden;
  color: var(--ikaros-ink);
}

.chat-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 18px;
  padding: 0 4px;
}

.chat-title {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 22px;
  font-weight: 780;
  letter-spacing: -0.03em;
  line-height: 1.2;
}

.chat-subtitle {
  margin: 0;
  color: var(--ikaros-copy);
  font-size: 12px;
}

.chat-workbench {
  display: grid;
  min-height: 0;
  gap: 16px;
  grid-template-columns: 320px minmax(0, 1fr);
}

.chat-panel {
  min-height: 0;
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .chat-panel {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.86);
}

.panel-fill {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
}

.chat-panel :global(.liquid-glass__content) {
  height: 100%;
  min-height: 0;
}

/* Sessions rail */
.sessions-inner {
  gap: 12px;
  padding: 14px;
}

.sessions-top {
  display: flex;
  flex: none;
  gap: 8px;
}

.session-search {
  display: flex;
  min-width: 0;
  height: 38px;
  flex: 1;
  align-items: center;
  gap: 9px;
  padding: 0 12px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--ikaros-muted);
}

:global(.dark) .session-search {
  background: rgba(255, 255, 255, 0.06);
}

.session-search svg {
  width: 15px;
  height: 15px;
  flex: none;
}

.session-search input {
  min-width: 0;
  width: 100%;
  border: 0;
  background: transparent;
  color: var(--ikaros-ink);
  font-size: 13px;
  outline: none;
}

.icon-button {
  display: grid;
  width: 38px;
  height: 38px;
  flex: none;
  place-items: center;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--ikaros-copy);
}

:global(.dark) .icon-button {
  background: rgba(255, 255, 255, 0.06);
}

.icon-button:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.icon-button svg {
  width: 16px;
  height: 16px;
}

.new-session-button {
  display: flex;
  height: 40px;
  flex: none;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 0;
  border-radius: 13px;
  background: var(--ikaros-collar);
  color: #fff9fc;
  box-shadow: 0 8px 20px rgba(23, 19, 26, 0.18);
  font-size: 13px;
  font-weight: 750;
}

.new-session-button:hover {
  background: #2a2230;
}

.new-session-button svg {
  width: 16px;
  height: 16px;
}

.sessions-list {
  display: flex;
  min-height: 0;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  overflow-y: auto;
  padding-right: 2px;
}

.sessions-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--ikaros-line);
  border-radius: 13px;
  color: var(--ikaros-copy);
  font-size: 12px;
}

.sessions-loading svg {
  width: 15px;
  height: 15px;
  color: var(--ikaros-pink);
}

.is-spinning {
  animation: chat-spin 850ms linear infinite;
}

.session-item {
  position: relative;
  display: grid;
  width: 100%;
  min-height: 88px;
  flex: 0 0 auto;
  box-sizing: border-box;
  gap: 6px;
  padding: 11px 12px;
  overflow: hidden;
  border: 1px solid transparent;
  border-radius: 14px;
  background: transparent;
  color: var(--ikaros-ink);
  text-align: left;
}

.session-item:hover {
  background: rgba(255, 255, 255, 0.42);
}

:global(.dark) .session-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.session-item.is-active {
  border-color: rgba(232, 93, 142, 0.22);
  background: rgba(255, 255, 255, 0.62);
}

:global(.dark) .session-item.is-active {
  background: rgba(255, 255, 255, 0.08);
}

.session-item.is-active::before {
  position: absolute;
  top: 10px;
  bottom: 10px;
  left: 0;
  width: 3px;
  border-radius: 999px;
  background: var(--ikaros-pink);
  content: '';
}

.session-item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.session-item-head strong {
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-item-head time {
  flex: none;
  color: var(--ikaros-muted);
  font-size: 10px;
}

.session-item > p {
  display: -webkit-box;
  margin: 0;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  color: var(--ikaros-copy);
  font-size: 11px;
  line-height: 1.55;
}

.session-item-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.live-flag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ikaros-eye);
  font-size: 10px;
  font-weight: 700;
}

.live-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ikaros-eye);
  box-shadow: 0 0 0 3px rgba(42, 140, 138, 0.14);
  animation: chat-pulse 2s ease-out infinite;
}

.session-count {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(23, 19, 26, 0.05);
  color: var(--ikaros-muted);
  font-size: 10px;
  font-weight: 650;
}

:global(.dark) .session-count {
  background: rgba(255, 255, 255, 0.07);
}

.session-count svg {
  width: 11px;
  height: 11px;
}

.sessions-empty {
  padding: 16px 14px;
  border: 1px dashed var(--ikaros-line);
  border-radius: 14px;
  color: var(--ikaros-muted);
  font-size: 12px;
  line-height: 1.6;
}

.sessions-scrim {
  display: none;
}

/* Conversation canvas */
.canvas-inner {
  min-height: 0;
}

.canvas-header {
  display: flex;
  flex: none;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
  padding: 13px 18px;
  border-bottom: 1px solid var(--ikaros-line);
}

.canvas-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 10px;
}

.sessions-toggle {
  display: none;
}

.canvas-title {
  min-width: 0;
}

.canvas-title h2 {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 14px;
  font-weight: 750;
}

.canvas-title h2 > span:first-child {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.canvas-title p {
  margin: 3px 0 0;
  overflow: hidden;
  color: var(--ikaros-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.active-badge {
  display: inline-flex;
  flex: none;
  align-items: center;
  gap: 5px;
  padding: 3px 9px;
  border-radius: 999px;
  background: rgba(42, 140, 138, 0.1);
  color: var(--ikaros-eye);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}

.canvas-header-actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: 8px;
}

.stream-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 11px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 650;
}

:global(.dark) .stream-chip {
  background: rgba(255, 255, 255, 0.06);
}

.stream-chip.is-error {
  border-color: rgba(198, 55, 65, 0.2);
  background: rgba(198, 55, 65, 0.08);
  color: #c63741;
}

.stream-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--ikaros-eye);
}

.stream-chip.is-error .stream-dot {
  background: #c63741;
}

.command-hint {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 11px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 650;
}

.command-hint svg {
  width: 13px;
  height: 13px;
  color: var(--ikaros-pink);
}

.messages-area {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 18px;
  scrollbar-gutter: stable;
}

.messages-area::-webkit-scrollbar,
.sessions-list::-webkit-scrollbar {
  width: 6px;
}

.messages-area::-webkit-scrollbar-thumb,
.sessions-list::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: rgba(23, 19, 26, 0.18);
}

:global(.dark) .messages-area::-webkit-scrollbar-thumb,
:global(.dark) .sessions-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.16);
}

.messages-empty {
  display: flex;
  min-height: 100%;
  align-items: center;
  justify-content: center;
}

.empty-card {
  max-width: 460px;
  padding: 30px 28px;
  border: 1px dashed var(--ikaros-line);
  border-radius: 20px;
  text-align: center;
}

.empty-icon {
  display: grid;
  width: 46px;
  height: 46px;
  margin: 0 auto;
  place-items: center;
  border-radius: 15px;
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.empty-icon svg {
  width: 21px;
  height: 21px;
}

.empty-card h3 {
  margin: 14px 0 0;
  color: var(--ikaros-ink);
  font-size: 17px;
  font-weight: 780;
  letter-spacing: -0.02em;
}

.empty-card p {
  margin: 8px 0 0;
  color: var(--ikaros-copy);
  font-size: 12px;
  line-height: 1.7;
}

.messages-list {
  display: grid;
  gap: 18px;
}

.message-row {
  display: flex;
  gap: 10px;
}

.message-row.is-user {
  justify-content: flex-end;
}

.ai-avatar {
  display: grid;
  width: 30px;
  height: 30px;
  flex: none;
  place-items: center;
  border-radius: 10px;
  background: var(--ikaros-collar);
  color: #fff9fc;
  box-shadow: 0 4px 12px rgba(23, 19, 26, 0.18);
}

.ai-avatar svg {
  width: 16px;
  height: 16px;
}

.message-stack {
  display: grid;
  max-width: min(760px, 82%);
  gap: 5px;
  justify-items: start;
}

.message-row.is-user .message-stack {
  justify-items: end;
}

.message-meta {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 0 4px;
  color: var(--ikaros-muted);
  font-size: 10px;
  font-weight: 650;
}

.message-bubble {
  display: grid;
  gap: 10px;
  padding: 12px 14px;
  border-radius: 16px 16px 16px 4px;
  font-size: 13px;
  line-height: 1.7;
}

.message-row.is-assistant .message-bubble {
  border: 1px solid var(--ikaros-line);
  background: rgba(255, 255, 255, 0.72);
  color: var(--ikaros-ink);
  box-shadow: 0 4px 14px rgba(23, 19, 26, 0.05);
}

:global(.dark) .message-row.is-assistant .message-bubble {
  background: rgba(255, 255, 255, 0.07);
}

.message-row.is-user .message-bubble {
  border-radius: 16px 16px 4px 16px;
  background: var(--ikaros-pink);
  color: #17131a;
  box-shadow: 0 8px 20px rgba(232, 93, 142, 0.22);
}

.message-text {
  white-space: pre-wrap;
  word-break: break-word;
}

.attachment-list {
  display: grid;
  gap: 8px;
}

.attachment-card {
  overflow: hidden;
  border: 1px solid var(--ikaros-line);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.55);
}

:global(.dark) .attachment-card {
  background: rgba(255, 255, 255, 0.05);
}

.attachment-image {
  display: block;
  width: 100%;
  border: 0;
  background: rgba(23, 19, 26, 0.04);
  padding: 0;
}

.attachment-image img {
  display: block;
  width: 100%;
  max-height: 420px;
  object-fit: contain;
}

.attachment-loading {
  display: flex;
  min-height: 150px;
  align-items: center;
  justify-content: center;
  color: var(--ikaros-muted);
  font-size: 12px;
}

.attachment-loading.is-compact {
  min-height: 0;
  padding: 12px;
  border: 1px dashed var(--ikaros-line);
  border-radius: 11px;
}

.attachment-body {
  display: grid;
  gap: 10px;
  padding: 10px;
}

.attachment-audio {
  width: 100%;
}

.attachment-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.attachment-file {
  min-width: 0;
}

.attachment-file strong {
  display: block;
  overflow: hidden;
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-file span {
  color: var(--ikaros-muted);
  font-size: 10px;
}

.attachment-open {
  flex: none;
  padding: 6px 12px;
  border: 1px solid var(--ikaros-line);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.6);
  color: var(--ikaros-ink);
  font-size: 11px;
  font-weight: 700;
}

:global(.dark) .attachment-open {
  background: rgba(255, 255, 255, 0.08);
}

.attachment-open:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.action-list {
  display: grid;
  gap: 8px;
}

.action-row {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.action-pill {
  padding: 6px 12px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--ikaros-ink);
  font-size: 11px;
  font-weight: 650;
}

:global(.dark) .action-pill {
  background: rgba(255, 255, 255, 0.06);
}

.action-pill:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.message-tools {
  display: flex;
  justify-content: flex-end;
}

.tts-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 11px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 650;
}

:global(.dark) .tts-button {
  background: rgba(255, 255, 255, 0.06);
}

.tts-button:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.tts-button svg {
  width: 13px;
  height: 13px;
}

.canvas-footer {
  flex: none;
  padding: 12px 14px 10px;
  border-top: 1px solid var(--ikaros-line);
}

.command-picker {
  margin-bottom: 10px;
  padding: 10px;
  border: 1px solid var(--ikaros-line);
  border-radius: 14px;
  background: rgba(255, 249, 252, 0.9);
  box-shadow: 0 12px 32px rgba(23, 19, 26, 0.1);
}

:global(.dark) .command-picker {
  background: rgba(43, 34, 40, 0.94);
}

.command-picker-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 0 2px 8px;
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
}

.command-picker-head button {
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  border: 0;
  border-radius: 7px;
  background: transparent;
  color: var(--ikaros-muted);
}

.command-picker-head button:hover {
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.command-picker-head svg {
  width: 12px;
  height: 12px;
}

.command-picker-grid {
  display: grid;
  gap: 4px;
}

.command-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 7px 10px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--ikaros-ink);
  text-align: left;
}

.command-option:hover {
  background: rgba(232, 93, 142, 0.09);
}

.command-option span {
  color: var(--ikaros-pink);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  font-weight: 700;
}

.command-option small {
  color: var(--ikaros-muted);
  font-size: 11px;
}

.composer {
  display: grid;
  gap: 8px;
  padding: 8px 10px 10px;
  border: 1px solid var(--ikaros-line);
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.62);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.7);
}

:global(.dark) .composer {
  background: rgba(255, 255, 255, 0.06);
}

.composer:focus-within {
  border-color: rgba(232, 93, 142, 0.4);
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.1);
}

.composer textarea {
  width: 100%;
  min-height: 64px;
  max-height: 180px;
  resize: none;
  border: 0;
  background: transparent;
  color: var(--ikaros-ink);
  font-size: 13px;
  line-height: 1.7;
  outline: none;
}

.composer-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding-top: 8px;
  border-top: 1px solid var(--ikaros-line);
}

.composer-tools {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tool-button {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: var(--ikaros-copy);
}

.tool-button:hover {
  background: rgba(23, 19, 26, 0.05);
  color: var(--ikaros-pink);
}

:global(.dark) .tool-button:hover {
  background: rgba(255, 255, 255, 0.08);
}

.tool-button.is-recording {
  background: rgba(198, 55, 65, 0.1);
  color: #c63741;
}

.tool-button svg {
  width: 17px;
  height: 17px;
}

.command-chip {
  padding: 5px 10px;
  border: 0;
  border-radius: 9px;
  background: rgba(23, 19, 26, 0.05);
  color: var(--ikaros-copy);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  font-weight: 650;
}

:global(.dark) .command-chip {
  background: rgba(255, 255, 255, 0.08);
}

.command-chip:hover {
  color: var(--ikaros-pink);
}

.file-input {
  display: none;
}

.send-button {
  display: inline-flex;
  height: 36px;
  align-items: center;
  gap: 7px;
  padding: 0 16px;
  border: 0;
  border-radius: 11px;
  background: var(--ikaros-collar);
  color: #fff9fc;
  box-shadow: 0 6px 16px rgba(23, 19, 26, 0.18);
  font-size: 13px;
  font-weight: 750;
}

.send-button:hover:not(:disabled) {
  background: var(--ikaros-pink);
}

.send-button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.send-button svg {
  width: 15px;
  height: 15px;
}

.composer-note {
  margin: 8px 0 0;
  color: var(--ikaros-muted);
  font-size: 10px;
  text-align: center;
}

/* Info panel */
.info-panel {
  display: none;
}

.info-inner {
  gap: 0;
  overflow-y: auto;
}

.info-section {
  padding: 18px;
  border-bottom: 1px solid var(--ikaros-line);
}

.info-section:last-child {
  border-bottom: 0;
}

.info-section h3 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 800;
  letter-spacing: -0.01em;
}

.meta-list {
  display: grid;
  gap: 14px;
  margin: 16px 0 0;
}

.meta-list div {
  min-width: 0;
}

.meta-list dt {
  color: var(--ikaros-muted);
  font-size: 11px;
}

.meta-list dd {
  margin: 4px 0 0;
  overflow: hidden;
  color: var(--ikaros-ink);
  font-size: 12px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.meta-list dd.is-mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
}

.command-list {
  display: grid;
  gap: 4px;
  margin-top: 14px;
}

.command-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  text-align: left;
}

.command-item:hover {
  background: rgba(232, 93, 142, 0.09);
}

.command-item span {
  color: var(--ikaros-pink);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  font-weight: 700;
}

.command-item small {
  overflow: hidden;
  color: var(--ikaros-muted);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@keyframes chat-spin {
  to { transform: rotate(360deg); }
}

@keyframes chat-pulse {
  0% { box-shadow: 0 0 0 0 rgba(42, 140, 138, 0.28); }
  70%, 100% { box-shadow: 0 0 0 7px rgba(42, 140, 138, 0); }
}

@media (min-width: 1280px) {
  .chat-workbench {
    grid-template-columns: 330px minmax(0, 1fr) 290px;
  }

  .info-panel {
    display: block;
  }
}

@media (max-width: 900px) {
  .chat-workbench {
    grid-template-columns: minmax(0, 1fr);
  }

  .sessions-panel {
    position: fixed;
    z-index: 60;
    top: 12px;
    bottom: 12px;
    left: 12px;
    width: min(320px, calc(100vw - 48px));
    transform: translateX(calc(-100% - 20px));
    transition: transform 240ms cubic-bezier(0.16, 1, 0.3, 1);
  }

  .sessions-panel.is-open {
    transform: translateX(0);
  }

  .sessions-scrim {
    position: fixed;
    z-index: 55;
    inset: 0;
    display: block;
    background: rgba(23, 19, 26, 0.28);
    backdrop-filter: blur(4px);
  }

  .sessions-toggle {
    display: grid;
  }

  .command-hint {
    display: none;
  }
}

@media (max-width: 640px) {
  .chat-page {
    height: calc(100dvh - 154px);
    gap: 12px;
  }

  .chat-subtitle {
    display: none;
  }

  .message-stack {
    max-width: 92%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning {
    animation: none;
  }

  .live-dot {
    animation: none;
  }

  .sessions-panel {
    transition: none;
  }
}
</style>
