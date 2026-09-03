<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
    ArrowDown,
    ArrowDownLeft,
    ArrowDownRight,
    ArrowLeft,
    ArrowRight,
    ArrowUp,
    ArrowUpLeft,
    ArrowUpRight,
    Cctv,
    CircleStop,
    Gamepad2,
    Loader2,
    Pencil,
    PictureInPicture2,
    Play,
    Plus,
    RefreshCw,
    Signal,
    Trash2,
    Video,
    ZoomIn,
    ZoomOut,
} from 'lucide-vue-next'

import {
    createCamera,
    createStreamToken,
    deleteCamera,
    listCameras,
    sendPtz,
    testCamera,
    updateCamera,
    type CameraItem,
    type CameraPayload,
    type PtzAction,
    type StreamToken,
} from '@/api/cameras'
import LiquidGlass from '@/components/liquid-glass/LiquidGlass.vue'

type PlayerMode = 'webrtc' | 'hls'

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

interface MediaMTXWebRTCReaderConfig {
    url: string
    onError?: (error: string) => void
    onTrack?: (event: RTCTrackEvent) => void
}

interface MediaMTXWebRTCReaderInstance {
    close: () => void
}

declare global {
    interface Window {
        MediaMTXWebRTCReader?: new (
            config: MediaMTXWebRTCReaderConfig
        ) => MediaMTXWebRTCReaderInstance
    }

    interface HTMLVideoElement {
        webkitPresentationMode?: 'inline' | 'picture-in-picture' | 'fullscreen'
        webkitSetPresentationMode?: (
            mode: 'inline' | 'picture-in-picture' | 'fullscreen'
        ) => void
        webkitSupportsPresentationMode?: (mode: string) => boolean
    }
}

interface CameraForm {
    name: string
    rtsp_url: string
    enabled: boolean
    mediamtx_path: string
    onvif_enabled: boolean
    onvif_host: string
    onvif_port: number
    onvif_username: string
    onvif_password: string
}

const cameras = ref<CameraItem[]>([])
const loading = ref(false)
const refreshing = ref(false)
const streamLoading = ref(false)
const selectedId = ref<number | null>(null)
const stream = ref<StreamToken | null>(null)
const streamError = ref('')
const playerMode = ref<PlayerMode>('webrtc')
const liveVideoRef = ref<HTMLVideoElement | null>(null)
const previewCanvasRef = ref<HTMLCanvasElement | null>(null)
const overviewCanvasRef = ref<HTMLCanvasElement | null>(null)
const pipVideoRef = ref<HTMLVideoElement | null>(null)
const pipCanvasRef = ref<HTMLCanvasElement | null>(null)
const directStreamReady = ref(false)
const directStreamError = ref('')
const digitalZoom = ref(1)
const zoomCenter = ref({ x: 0.5, y: 0.5 })
const pipActive = ref(false)
const showDialog = ref(false)
const editingId = ref<number | null>(null)
const saving = ref(false)
const testingId = ref<number | null>(null)
const ptzAction = ref<PtzAction | ''>('')
const ptzSpeed = ref(0.12)
const ptzSpeedPercent = computed(() => Math.round(ptzSpeed.value * 100))
const PTZ_MOVE_DURATION_MS = 80
const DIGITAL_ZOOM_MIN = 1
const DIGITAL_ZOOM_MAX = 5
const DIGITAL_ZOOM_STEP = 0.25
const TIMESTAMP_CROP_WIDTH_RATIO = 0.42
const TIMESTAMP_CROP_HEIGHT_RATIO = 0.12
let ptzIdleTimer: ReturnType<typeof window.setTimeout> | null = null
let mediamtxReader: MediaMTXWebRTCReaderInstance | null = null
let directMediaStream: MediaStream | null = null
let directStreamGeneration = 0
let readerScriptPromise: Promise<void> | null = null
let previewFrameId: number | null = null
let pipFrameId: number | null = null
let pipCanvasStream: MediaStream | null = null
let pipWarmupPromise: Promise<boolean> | null = null
let zoomPan:
    | {
        pointerId: number
        startX: number
        startY: number
        centerX: number
        centerY: number
        mode: 'main' | 'overview'
    }
    | null = null

const emptyForm = (): CameraForm => ({
    name: '',
    rtsp_url: '',
    enabled: true,
    mediamtx_path: '',
    onvif_enabled: true,
    onvif_host: '',
    onvif_port: 80,
    onvif_username: '',
    onvif_password: '',
})

const formData = ref<CameraForm>(emptyForm())

const selectedCamera = computed(() =>
    cameras.value.find((camera) => camera.id === selectedId.value) || null
)

const enabledCount = computed(() => cameras.value.filter((camera) => camera.enabled).length)
const ptzCount = computed(() => cameras.value.filter((camera) => camera.onvif_enabled).length)
const canControlPtz = computed(() =>
    !!selectedCamera.value?.onvif_enabled && !!selectedCamera.value?.onvif_host
)
const canUseDirectWebRtc = computed(() =>
    playerMode.value === 'webrtc' && !!stream.value?.webrtc_whep_url
)
const liveState = computed(() => {
    if (!selectedCamera.value) return { text: '未选择', tone: 'muted' }
    if (streamLoading.value) return { text: '连接中', tone: 'muted' }
    if (streamError.value) return { text: '连接异常', tone: 'danger' }
    if (playerMode.value === 'webrtc') {
        if (directStreamReady.value) return { text: 'LIVE', tone: 'live' }
        if (directStreamError.value) return { text: '播放异常', tone: 'danger' }
        return { text: '连接中', tone: 'muted' }
    }
    return { text: 'HLS', tone: 'live' }
})
const canUseDigitalZoom = computed(() =>
    !!selectedCamera.value &&
    (
        canUseDirectWebRtc.value ||
        (playerMode.value === 'hls' && !!stream.value?.hls_page_url)
    )
)
const canOpenZoomPip = computed(() =>
    canUseDirectWebRtc.value && directStreamReady.value && isPictureInPictureSupported()
)
const canUseZoomedCanvasPip = () => canUseCanvasCaptureStream()

const prefersNativePictureInPicture = () => {
    if (typeof navigator === 'undefined') return false
    const ua = navigator.userAgent || ''
    const isIOS = /iPad|iPhone|iPod/.test(ua) ||
        (navigator.platform === 'MacIntel' && (navigator.maxTouchPoints || 0) > 1)
    const isSafari = /Safari/i.test(ua) && !/Chrome|CriOS|FxiOS|EdgiOS|Android/i.test(ua)
    return isIOS || isSafari
}
const zoomLabel = computed(() =>
    `${digitalZoom.value.toFixed(2).replace(/\.00$/, '').replace(/0$/, '')}x`
)
const zoomedMediaStyle = computed(() => {
    const zoom = Math.max(1, digitalZoom.value)
    return {
        transform: `translate(${(0.5 - zoomCenter.value.x * zoom) * 100}%, ${(0.5 - zoomCenter.value.y * zoom) * 100}%) scale(${zoom})`,
        transformOrigin: '0 0',
    }
})
const viewportRectStyle = computed(() => {
    const zoom = Math.max(1, digitalZoom.value)
    const width = 100 / zoom
    const height = 100 / zoom
    return {
        left: `${(zoomCenter.value.x - 0.5 / zoom) * 100}%`,
        top: `${(zoomCenter.value.y - 0.5 / zoom) * 100}%`,
        width: `${width}%`,
        height: `${height}%`,
    }
})

const loadData = async (isRefresh = false) => {
    if (isRefresh) {
        refreshing.value = true
    } else {
        loading.value = true
    }
    try {
        const res = await listCameras()
        cameras.value = res.data || []
        if (!selectedId.value && cameras.value.length > 0) {
            selectedId.value = cameras.value[0]?.id || null
        }
        if (selectedId.value && !cameras.value.some((camera) => camera.id === selectedId.value)) {
            selectedId.value = cameras.value[0]?.id || null
        }
    } catch (error) {
        console.error(error)
    } finally {
        loading.value = false
        refreshing.value = false
    }
}

const loadStream = async () => {
    stream.value = null
    streamError.value = ''
    if (!selectedId.value) return
    streamLoading.value = true
    try {
        const res = await createStreamToken(selectedId.value)
        stream.value = res.data
    } catch (error: any) {
        streamError.value = error?.response?.data?.detail || '拉流失败'
    } finally {
        streamLoading.value = false
    }
}

const selectCamera = (camera: CameraItem) => {
    selectedId.value = camera.id
}

const openCreate = () => {
    editingId.value = null
    formData.value = emptyForm()
    showDialog.value = true
}

const openEdit = (camera: CameraItem) => {
    editingId.value = camera.id
    formData.value = {
        name: camera.name,
        rtsp_url: camera.rtsp_url || '',
        enabled: camera.enabled,
        mediamtx_path: camera.mediamtx_path,
        onvif_enabled: camera.onvif_enabled,
        onvif_host: camera.onvif_host || '',
        onvif_port: camera.onvif_port || 80,
        onvif_username: camera.onvif_username || '',
        onvif_password: camera.onvif_password || '',
    }
    showDialog.value = true
}

const closeDialog = () => {
    showDialog.value = false
    editingId.value = null
    formData.value = emptyForm()
}

const buildPayload = () => {
    const base: CameraPayload = {
        name: formData.value.name.trim(),
        enabled: formData.value.enabled,
        mediamtx_path: formData.value.mediamtx_path.trim() || undefined,
        onvif_enabled: formData.value.onvif_enabled,
        onvif_host: formData.value.onvif_host.trim() || undefined,
        onvif_port: Number(formData.value.onvif_port || 80),
        onvif_username: formData.value.onvif_username.trim() || undefined,
    }
    if (formData.value.rtsp_url.trim()) {
        base.rtsp_url = formData.value.rtsp_url.trim()
    }
    if (formData.value.onvif_password.trim()) {
        base.onvif_password = formData.value.onvif_password
    }
    return base
}

const handleSave = async () => {
    if (!formData.value.name.trim()) return
    if (!editingId.value && !formData.value.rtsp_url.trim()) return
    saving.value = true
    try {
        if (editingId.value) {
            await updateCamera(editingId.value, buildPayload())
        } else {
            await createCamera(buildPayload())
        }
        closeDialog()
        await loadData(true)
    } catch (error: any) {
        alert(error?.response?.data?.detail || '保存失败')
    } finally {
        saving.value = false
    }
}

const handleDelete = async (camera: CameraItem) => {
    if (!confirm(`确定删除 ${camera.name} 吗？`)) return
    try {
        await deleteCamera(camera.id)
        await loadData(true)
    } catch (error: any) {
        alert(error?.response?.data?.detail || '删除失败')
    }
}

const handleTest = async (camera: CameraItem) => {
    testingId.value = camera.id
    try {
        const res = await testCamera(camera.id)
        const mediamtx = res.data?.mediamtx
        const onvif = res.data?.onvif
        alert(`MediaMTX: ${mediamtx?.ok ? 'OK' : mediamtx?.detail || '失败'}\nONVIF: ${onvif?.ok ? 'OK' : onvif?.detail || '失败'}`)
    } catch (error: any) {
        alert(error?.response?.data?.detail || '测试失败')
    } finally {
        testingId.value = null
    }
}

const clearPtzIdleTimer = () => {
    if (ptzIdleTimer) {
        window.clearTimeout(ptzIdleTimer)
        ptzIdleTimer = null
    }
}

const startPtz = async (action: PtzAction) => {
    if (!selectedCamera.value || !canControlPtz.value) return
    clearPtzIdleTimer()
    ptzAction.value = action
    ptzIdleTimer = window.setTimeout(() => {
        if (ptzAction.value === action) {
            ptzAction.value = ''
        }
        ptzIdleTimer = null
    }, PTZ_MOVE_DURATION_MS + 160)
    try {
        await sendPtz(selectedCamera.value.id, action, ptzSpeed.value, PTZ_MOVE_DURATION_MS)
    } catch (error: any) {
        ptzAction.value = ''
        clearPtzIdleTimer()
        alert(error?.response?.data?.detail || '云台控制失败')
    }
}

const stopPtz = async (forceOrEvent: boolean | Event = false) => {
    const force = forceOrEvent === true
    clearPtzIdleTimer()
    if (!selectedCamera.value || (!ptzAction.value && !force)) return
    const cameraId = selectedCamera.value.id
    ptzAction.value = ''
    try {
        await sendPtz(cameraId, 'stop', ptzSpeed.value)
    } catch (error) {
        console.error(error)
    }
}

const isPictureInPictureSupported = () =>
    typeof document !== 'undefined' &&
    typeof HTMLVideoElement !== 'undefined' &&
    (
        (
            !!document.pictureInPictureEnabled &&
            typeof HTMLVideoElement.prototype.requestPictureInPicture === 'function'
        ) ||
        typeof HTMLVideoElement.prototype.webkitSetPresentationMode === 'function'
    )

const isPipActiveForVideo = (video: HTMLVideoElement | null | undefined) =>
    !!video && (
        document.pictureInPictureElement === video ||
        video.webkitPresentationMode === 'picture-in-picture'
    )

const canUseCanvasCaptureStream = () =>
    typeof HTMLCanvasElement !== 'undefined' &&
    typeof HTMLCanvasElement.prototype.captureStream === 'function'

const isVideoReadyForPictureInPicture = (video: HTMLVideoElement | null | undefined) =>
    !!video &&
    !video.paused &&
    !video.ended &&
    video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
    video.videoWidth > 0 &&
    video.videoHeight > 0

const clampZoom = (value: number) => {
    const stepped = Math.round(value / DIGITAL_ZOOM_STEP) * DIGITAL_ZOOM_STEP
    return Math.min(DIGITAL_ZOOM_MAX, Math.max(DIGITAL_ZOOM_MIN, stepped))
}

const setDigitalZoom = (value: number) => {
    digitalZoom.value = clampZoom(Number(value) || DIGITAL_ZOOM_MIN)
    zoomCenter.value = clampZoomCenter(zoomCenter.value.x, zoomCenter.value.y)
}

const clampZoomCenter = (x: number, y: number) => {
    const zoom = Math.max(1, digitalZoom.value)
    const halfWidth = 0.5 / zoom
    const halfHeight = 0.5 / zoom
    return {
        x: Math.min(1 - halfWidth, Math.max(halfWidth, x)),
        y: Math.min(1 - halfHeight, Math.max(halfHeight, y)),
    }
}

const setZoomCenter = (x: number, y: number) => {
    zoomCenter.value = clampZoomCenter(x, y)
}

const isBenignPlayError = (error: any) => {
    const message = String(error?.message || error || '').toLowerCase()
    return error?.name === 'AbortError' || message.includes('interrupted by a new load request')
}

const seekZoomCenterFromEvent = (event: PointerEvent, element: HTMLElement, mode: 'main' | 'overview') => {
    const rect = element.getBoundingClientRect()
    const localX = (event.clientX - rect.left) / rect.width
    const localY = (event.clientY - rect.top) / rect.height
    if (mode === 'overview') {
        setZoomCenter(localX, localY)
        return
    }
    const zoom = Math.max(1, digitalZoom.value)
    setZoomCenter(
        zoomPan ? zoomPan.centerX - (event.clientX - zoomPan.startX) / rect.width / zoom : localX,
        zoomPan ? zoomPan.centerY - (event.clientY - zoomPan.startY) / rect.height / zoom : localY
    )
}

const startZoomPan = (event: PointerEvent, mode: 'main' | 'overview') => {
    if (!canUseDigitalZoom.value || digitalZoom.value <= 1) return
    const element = event.currentTarget as HTMLElement
    element.setPointerCapture?.(event.pointerId)
    zoomPan = {
        pointerId: event.pointerId,
        startX: event.clientX,
        startY: event.clientY,
        centerX: zoomCenter.value.x,
        centerY: zoomCenter.value.y,
        mode,
    }
    seekZoomCenterFromEvent(event, element, mode)
}

const moveZoomPan = (event: PointerEvent) => {
    if (!zoomPan || zoomPan.pointerId !== event.pointerId) return
    seekZoomCenterFromEvent(event, event.currentTarget as HTMLElement, zoomPan.mode)
}

const stopZoomPan = (event: PointerEvent) => {
    if (!zoomPan || zoomPan.pointerId !== event.pointerId) return
    const element = event.currentTarget as HTMLElement
    element.releasePointerCapture?.(event.pointerId)
    zoomPan = null
}

const videoSourceRect = (width: number, height: number) => {
    const zoom = Math.max(1, digitalZoom.value)
    const sourceWidth = width / zoom
    const sourceHeight = height / zoom
    const center = clampZoomCenter(zoomCenter.value.x, zoomCenter.value.y)
    return {
        x: center.x * width - sourceWidth / 2,
        y: center.y * height - sourceHeight / 2,
        width: sourceWidth,
        height: sourceHeight,
    }
}

const ensureCanvasSize = (canvas: HTMLCanvasElement, width: number, height: number) => {
    if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width
        canvas.height = height
    }
}

const drawTimestampInset = (
    context: CanvasRenderingContext2D,
    source: HTMLVideoElement,
    width: number,
    height: number
) => {
    const sourceWidth = Math.round(width * TIMESTAMP_CROP_WIDTH_RATIO)
    const sourceHeight = Math.round(height * TIMESTAMP_CROP_HEIGHT_RATIO)
    const targetWidth = Math.round(sourceWidth * 1.15)
    const targetHeight = Math.round(sourceHeight * 1.15)
    context.save()
    context.fillStyle = 'rgba(0, 0, 0, 0.45)'
    context.fillRect(0, 0, targetWidth + 16, targetHeight + 12)
    context.drawImage(
        source,
        0,
        0,
        sourceWidth,
        sourceHeight,
        8,
        6,
        targetWidth,
        targetHeight
    )
    context.restore()
}

const drawZoomedFrame = (target: HTMLCanvasElement | null, includeTimestamp = true) => {
    const source = liveVideoRef.value
    const context = target?.getContext('2d')
    if (!source || !target || !context) return false

    const width = source.videoWidth || 1280
    const height = source.videoHeight || 720
    ensureCanvasSize(target, width, height)

    if (source.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return false

    const rect = videoSourceRect(width, height)
    context.drawImage(
        source,
        rect.x,
        rect.y,
        rect.width,
        rect.height,
        0,
        0,
        width,
        height
    )
    if (includeTimestamp && digitalZoom.value > 1) {
        drawTimestampInset(context, source, width, height)
    }
    return true
}

const drawOverviewFrame = () => {
    const source = liveVideoRef.value
    const canvas = overviewCanvasRef.value
    const context = canvas?.getContext('2d')
    if (!source || !canvas || !context || source.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return
    ensureCanvasSize(canvas, 320, 180)
    context.drawImage(source, 0, 0, canvas.width, canvas.height)
}

const startPreviewRenderer = () => {
    if (previewFrameId !== null) return
    const render = () => {
        if (directStreamReady.value) {
            drawZoomedFrame(previewCanvasRef.value)
            drawOverviewFrame()
            if (canOpenZoomPip.value && !pipCanvasStream && !prefersNativePictureInPicture()) {
                void ensurePipWarmup()
            }
        }
        previewFrameId = window.requestAnimationFrame(render)
    }
    previewFrameId = window.requestAnimationFrame(render)
}

const stopPreviewRenderer = () => {
    if (previewFrameId !== null) {
        window.cancelAnimationFrame(previewFrameId)
        previewFrameId = null
    }
}

const withToken = (url: string, token: string) => {
    if (!url || !token || url.includes('token=')) return url
    return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`
}

const readerScriptUrlFor = (whepUrl: string) => {
    const url = new URL(whepUrl, window.location.href)
    const parts = url.pathname.split('/').filter(Boolean)
    parts.splice(Math.max(0, parts.length - 2), 2, 'reader.js')
    url.pathname = `/${parts.join('/')}`
    url.search = ''
    url.hash = ''
    return url.toString()
}

const loadMediaMTXReader = (scriptUrl: string) => {
    if (window.MediaMTXWebRTCReader) return Promise.resolve()
    if (readerScriptPromise) return readerScriptPromise
    readerScriptPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script')
        script.src = scriptUrl
        script.async = true
        script.onload = () => resolve()
        script.onerror = () => {
            readerScriptPromise = null
            reject(new Error('WebRTC reader load failed'))
        }
        document.head.appendChild(script)
    })
    return readerScriptPromise
}

const stopDirectWebRtc = () => {
    directStreamGeneration += 1
    directStreamReady.value = false
    directStreamError.value = ''
    stopPipCanvasStream()
    stopPreviewRenderer()
    if (mediamtxReader) {
        mediamtxReader.close()
        mediamtxReader = null
    }
    if (liveVideoRef.value) {
        liveVideoRef.value.pause()
        liveVideoRef.value.srcObject = null
    }
    if (directMediaStream) {
        directMediaStream.getTracks().forEach((track) => track.stop())
        directMediaStream = null
    }
}

const startDirectWebRtc = async () => {
    stopDirectWebRtc()
    directStreamError.value = ''
    const currentStream = stream.value
    const liveVideo = liveVideoRef.value
    if (!currentStream?.webrtc_whep_url || !liveVideo) return

    const generation = directStreamGeneration
    const whepUrl = new URL(
        withToken(currentStream.webrtc_whep_url, currentStream.token),
        window.location.href
    ).toString()
    try {
        await loadMediaMTXReader(readerScriptUrlFor(whepUrl))
        if (generation !== directStreamGeneration) return
        const Reader = window.MediaMTXWebRTCReader
        if (!Reader) throw new Error('WebRTC reader unavailable')
        mediamtxReader = new Reader({
            url: whepUrl,
            onError: (error) => {
                if (generation === directStreamGeneration) {
                    if (directStreamReady.value) {
                        console.warn(error || 'WebRTC 播放失败')
                    } else {
                        directStreamError.value = error || 'WebRTC 播放失败'
                    }
                }
            },
            onTrack: (event) => {
                if (generation !== directStreamGeneration || !liveVideoRef.value) return
                const mediaStream = event.streams[0]
                if (!mediaStream) return
                directMediaStream = mediaStream
                liveVideoRef.value.srcObject = mediaStream
                liveVideoRef.value.play().catch((error) => {
                    if (generation !== directStreamGeneration || isBenignPlayError(error)) return
                    directStreamError.value = error?.message || 'WebRTC 播放失败'
                })
                directStreamReady.value = true
                directStreamError.value = ''
                startPreviewRenderer()
                if (!prefersNativePictureInPicture()) {
                    void ensurePipWarmup()
                }
            },
        })
    } catch (error: any) {
        if (generation === directStreamGeneration) {
            directStreamError.value = error?.message || 'WebRTC 播放失败'
        }
    }
}

const stopPipCanvasStream = () => {
    if (pipFrameId !== null) {
        window.cancelAnimationFrame(pipFrameId)
        pipFrameId = null
    }
    if (pipCanvasStream) {
        pipCanvasStream.getTracks().forEach((track) => track.stop())
        pipCanvasStream = null
    }
    pipWarmupPromise = null
    if (pipVideoRef.value) {
        pipVideoRef.value.pause()
        pipVideoRef.value.srcObject = null
    }
}

const drawZoomedPipFrame = () => {
    drawZoomedFrame(pipCanvasRef.value)
    pipFrameId = window.requestAnimationFrame(drawZoomedPipFrame)
}

const startPipRenderer = () => {
    if (pipFrameId === null) {
        drawZoomedPipFrame()
    }
}

const syncPipVideoMetrics = (
    video: HTMLVideoElement,
    width: number,
    height: number
) => {
    // iOS often refuses PiP when the element is 1x1 / zero-sized.
    video.width = width
    video.height = height
    video.style.width = `${Math.max(2, Math.round(width / 4))}px`
    video.style.height = `${Math.max(2, Math.round(height / 4))}px`
}

const ensurePipWarmup = async () => {
    if (pipWarmupPromise) return pipWarmupPromise

    pipWarmupPromise = (async () => {
        const pipVideo = pipVideoRef.value
        const canvas = pipCanvasRef.value
        const source = liveVideoRef.value
        if (
            !pipVideo ||
            !canvas ||
            !source ||
            !canOpenZoomPip.value ||
            !canUseZoomedCanvasPip() ||
            source.readyState < HTMLMediaElement.HAVE_CURRENT_DATA ||
            source.videoWidth <= 0 ||
            source.videoHeight <= 0
        ) {
            return false
        }

        const width = source.videoWidth || 1280
        const height = source.videoHeight || 720
        ensureCanvasSize(canvas, width, height)
        drawZoomedFrame(canvas)
        syncPipVideoMetrics(pipVideo, width, height)

        const streamEnded = !!pipCanvasStream?.getTracks().some((track) => track.readyState === 'ended')
        if (!pipCanvasStream || streamEnded || pipVideo.srcObject !== pipCanvasStream) {
            if (pipCanvasStream) {
                pipCanvasStream.getTracks().forEach((track) => track.stop())
                pipCanvasStream = null
            }
            pipCanvasStream = canvas.captureStream(24)
            pipVideo.srcObject = pipCanvasStream
        }

        startPipRenderer()

        if (pipVideo.paused || pipVideo.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) {
            try {
                await pipVideo.play()
            } catch (error) {
                if (!isBenignPlayError(error)) {
                    console.warn(error)
                }
            }
        }

        return isVideoReadyForPictureInPicture(pipVideo)
    })()

    try {
        return await pipWarmupPromise
    } finally {
        pipWarmupPromise = null
    }
}

const enterPictureInPicture = (video: HTMLVideoElement) => {
    try {
        video.disablePictureInPicture = false
    } catch {
        // ignore read-only failures
    }

    if (
        typeof video.requestPictureInPicture === 'function' &&
        document.pictureInPictureEnabled
    ) {
        return video.requestPictureInPicture()
    }
    if (
        typeof video.webkitSetPresentationMode === 'function' &&
        (
            typeof video.webkitSupportsPresentationMode !== 'function' ||
            video.webkitSupportsPresentationMode('picture-in-picture')
        )
    ) {
        video.webkitSetPresentationMode('picture-in-picture')
        return Promise.resolve(video)
    }
    return Promise.reject(new Error('当前浏览器不支持画中画'))
}

const exitPictureInPicture = async (video?: HTMLVideoElement | null) => {
    if (document.pictureInPictureElement) {
        await document.exitPictureInPicture()
        return
    }
    const candidates = [video, pipVideoRef.value, liveVideoRef.value].filter(
        (item): item is HTMLVideoElement => !!item
    )
    for (const candidate of candidates) {
        if (
            typeof candidate.webkitSetPresentationMode === 'function' &&
            candidate.webkitPresentationMode === 'picture-in-picture'
        ) {
            candidate.webkitSetPresentationMode('inline')
            return
        }
    }
}

const describePipError = (error: any) => {
    const message = String(error?.message || error || '')
    if (
        error?.name === 'NotAllowedError' ||
        /user activation|not allowed|not permitted/i.test(message)
    ) {
        return 'iOS/Safari 要求在点击瞬间直接打开画中画。请等画面出来后再点一次。'
    }
    if (/not ready to enter the Picture-in-Picture mode/i.test(message)) {
        return '画中画视频还没准备好。已优先尝试原生直播画面；请等画面稳定后再点一次。'
    }
    return message || '画中画打开失败'
}

const resolvePipTarget = () => {
    const liveVideo = liveVideoRef.value
    const pipVideo = pipVideoRef.value
    const canvas = pipCanvasRef.value
    const source = liveVideo
    const nativeReady = isVideoReadyForPictureInPicture(liveVideo)
    const zoomedReady = !!(
        pipVideo &&
        canvas &&
        source &&
        canUseZoomedCanvasPip() &&
        pipCanvasStream &&
        pipVideo.srcObject === pipCanvasStream &&
        isVideoReadyForPictureInPicture(pipVideo)
    )

    // iOS/Safari often never make canvas.captureStream() PiP-ready, so prefer
    // the real live WebRTC video there. Desktop can keep zoomed canvas PiP.
    if (prefersNativePictureInPicture()) {
        if (nativeReady) {
            return { video: liveVideo as HTMLVideoElement, mode: 'native' as const }
        }
        if (zoomedReady) {
            return { video: pipVideo as HTMLVideoElement, mode: 'zoomed' as const }
        }
        return null
    }

    if (zoomedReady) {
        return { video: pipVideo as HTMLVideoElement, mode: 'zoomed' as const }
    }
    if (nativeReady) {
        return { video: liveVideo as HTMLVideoElement, mode: 'native' as const }
    }
    return null
}

const toggleZoomedPictureInPicture = () => {
    const liveVideo = liveVideoRef.value
    const pipVideo = pipVideoRef.value
    if (!canOpenZoomPip.value || !liveVideo) return

    try {
        if (isPipActiveForVideo(pipVideo) || isPipActiveForVideo(liveVideo)) {
            void exitPictureInPicture(
                isPipActiveForVideo(pipVideo) ? pipVideo : liveVideo
            ).catch((error) => {
                alert(describePipError(error))
            })
            return
        }

        // Keep the click handler free of awaits so iOS still treats this as user activation.
        const target = resolvePipTarget()
        if (!target) {
            void ensurePipWarmup()
            throw new Error('画面还没准备好进入画中画，请等直播画面稳定后再试')
        }

        if (target.mode === 'zoomed') {
            startPipRenderer()
        } else {
            // Keep warming canvas PiP in the background for browsers that can use it later.
            void ensurePipWarmup()
        }

        void Promise.resolve(enterPictureInPicture(target.video)).catch((error) => {
            // If zoomed canvas path failed readiness-style, immediately retry native live video
            // while we still have a user gesture on some browsers.
            if (
                target.mode === 'zoomed' &&
                isVideoReadyForPictureInPicture(liveVideo)
            ) {
                void Promise.resolve(enterPictureInPicture(liveVideo)).catch((nativeError) => {
                    alert(describePipError(nativeError))
                    void ensurePipWarmup()
                })
                return
            }
            alert(describePipError(error))
            void ensurePipWarmup()
        })
    } catch (error: any) {
        alert(describePipError(error))
        void ensurePipWarmup()
    }
}

const handlePipEnter = () => {
    pipActive.value = true
    if (isPipActiveForVideo(pipVideoRef.value)) {
        startPipRenderer()
    }
}

const handlePipLeave = () => {
    pipActive.value = false
    // Keep the canvas stream warm for browsers that can use zoomed PiP.
    void ensurePipWarmup()
}

watch(
    [playerMode, () => stream.value?.webrtc_whep_url, () => stream.value?.token],
    () => {
        if (canUseDirectWebRtc.value) {
            startDirectWebRtc()
        } else {
            stopDirectWebRtc()
        }
    },
    { flush: 'post' }
)

watch(selectedId, () => {
    loadStream()
})

onMounted(() => {
    loadData()
})

onBeforeUnmount(() => {
    clearPtzIdleTimer()
    stopDirectWebRtc()
    stopPipCanvasStream()
})
</script>

<template>
  <div class="camera-page flex flex-col gap-4 p-3 md:gap-6 md:p-8">
    <LiquidGlass as="section" :radius="24" :optics="panelOptics" class="camera-summary order-2 md:order-1">
      <div class="camera-summary-inner">
        <div class="camera-summary-head">
          <div class="camera-summary-title">
            <p class="ikaros-page-kicker">Realtime</p>
            <h1>实时监控</h1>
          </div>
          <div class="camera-summary-actions">
            <button type="button" class="camera-ghost-btn" @click="loadData(true)">
              <RefreshCw :class="{ 'is-spinning': refreshing }" />
              刷新
            </button>
            <button type="button" class="ikaros-primary-action camera-add-btn" @click="openCreate">
              <Plus />
              添加摄像头
            </button>
          </div>
        </div>
        <div class="camera-summary-stats">
          <div class="camera-stat">
            <span class="camera-stat-icon"><Cctv /></span>
            <div class="camera-stat-copy">
              <span>摄像头总数</span>
              <strong>{{ cameras.length }}</strong>
            </div>
          </div>
          <div class="camera-stat">
            <span class="camera-stat-icon is-online"><Signal /></span>
            <div class="camera-stat-copy">
              <span>在线设备</span>
              <strong>{{ enabledCount }}</strong>
            </div>
          </div>
          <div class="camera-stat">
            <span class="camera-stat-icon"><Gamepad2 /></span>
            <div class="camera-stat-copy">
              <span>PTZ 支持</span>
              <strong>{{ ptzCount }}</strong>
            </div>
          </div>
        </div>
      </div>
    </LiquidGlass>

    <div class="camera-main-grid order-1 grid gap-4 md:order-2 md:gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <LiquidGlass as="section" :radius="24" :optics="panelOptics" class="camera-live-card">
        <div class="camera-live-header">
          <div class="camera-live-title">
            <span class="camera-live-dot" :class="`is-${liveState.tone}`" />
            <h3>{{ selectedCamera?.name || '未选择摄像头' }}</h3>
            <span class="camera-live-chip" :class="`is-${liveState.tone}`">{{ liveState.text }}</span>
          </div>
          <div class="camera-live-controls">
            <div class="camera-zoom-control" :class="{ 'is-disabled': !canUseDigitalZoom }">
              <ZoomOut />
              <input
                :value="digitalZoom"
                class="camera-zoom-slider"
                type="range"
                :min="DIGITAL_ZOOM_MIN"
                :max="DIGITAL_ZOOM_MAX"
                :step="DIGITAL_ZOOM_STEP"
                aria-label="数字变焦"
                :disabled="!canUseDigitalZoom"
                @input="setDigitalZoom(($event.target as HTMLInputElement).valueAsNumber)"
              >
              <ZoomIn />
              <span class="camera-zoom-value">{{ zoomLabel }}</span>
            </div>
            <button
              type="button"
              class="camera-pip-btn"
              :class="{ 'is-active': pipActive }"
              :disabled="!canOpenZoomPip"
              @click="toggleZoomedPictureInPicture"
            >
              <PictureInPicture2 />
              画中画
            </button>
            <div class="camera-mode-switch">
              <button
                type="button"
                :class="{ 'is-active': playerMode === 'webrtc' }"
                @click="playerMode = 'webrtc'"
              >
                WebRTC
              </button>
              <button
                type="button"
                :class="{ 'is-active': playerMode === 'hls' }"
                @click="playerMode = 'hls'"
              >
                HLS
              </button>
            </div>
            <button
              type="button"
              class="camera-icon-btn"
              title="重新拉流"
              :disabled="streamLoading || !selectedCamera"
              @click="loadStream"
            >
              <RefreshCw :class="{ 'is-spinning': streamLoading }" />
            </button>
          </div>
        </div>

        <div class="camera-player relative">
          <div v-if="streamLoading" class="absolute inset-0 flex items-center justify-center text-slate-100">
            <Loader2 class="h-8 w-8 animate-spin" />
          </div>
          <div v-else-if="streamError" class="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-slate-200">
            <Video class="h-12 w-12 text-slate-500" />
            <p>{{ streamError }}</p>
          </div>
          <div v-else-if="!selectedCamera" class="absolute inset-0 flex flex-col items-center justify-center gap-3 text-slate-400">
            <Cctv class="h-16 w-16 text-slate-600" />
            <p>暂无摄像头</p>
          </div>
          <div
            v-else-if="playerMode === 'webrtc' && stream?.webrtc_whep_url"
            class="camera-zoom-stage relative h-full w-full overflow-hidden"
            @pointerdown.prevent="startZoomPan($event, 'main')"
            @pointermove.prevent="moveZoomPan"
            @pointerup.prevent="stopZoomPan"
            @pointercancel.prevent="stopZoomPan"
          >
            <canvas ref="previewCanvasRef" class="camera-preview-canvas h-full w-full" />
            <video
              ref="liveVideoRef"
              class="camera-source-video"
              autoplay
              muted
              playsinline
              webkit-playsinline
              @enterpictureinpicture="handlePipEnter"
              @leavepictureinpicture="handlePipLeave"
            />
            <div v-if="!directStreamReady && !directStreamError" class="absolute inset-0 flex items-center justify-center text-slate-100">
              <Loader2 class="h-8 w-8 animate-spin" />
            </div>
            <div v-if="directStreamError && !directStreamReady" class="absolute inset-0 flex flex-col items-center justify-center gap-3 p-6 text-center text-slate-200">
              <Video class="h-12 w-12 text-slate-500" />
              <p>{{ directStreamError }}</p>
            </div>
            <div
              v-if="digitalZoom > 1 && directStreamReady"
              class="camera-overview"
              @pointerdown.stop.prevent="startZoomPan($event, 'overview')"
              @pointermove.stop.prevent="moveZoomPan"
              @pointerup.stop.prevent="stopZoomPan"
              @pointercancel.stop.prevent="stopZoomPan"
            >
              <canvas ref="overviewCanvasRef" class="h-full w-full" />
              <div class="camera-overview-rect" :style="viewportRectStyle" />
            </div>
          </div>
          <div
            v-else-if="playerMode === 'hls' && stream?.hls_page_url"
            class="camera-zoom-stage relative h-full w-full overflow-hidden"
            @pointerdown.prevent="startZoomPan($event, 'main')"
            @pointermove.prevent="moveZoomPan"
            @pointerup.prevent="stopZoomPan"
            @pointercancel.prevent="stopZoomPan"
          >
            <iframe
              :key="stream.hls_page_url"
              :src="stream.hls_page_url"
              class="camera-hls-frame h-full w-full"
              :class="{ 'camera-hls-frame--zoomed': digitalZoom > 1 }"
              :style="zoomedMediaStyle"
              allow="autoplay; fullscreen; picture-in-picture"
            />
            <div
              v-if="digitalZoom > 1"
              class="camera-overview camera-overview--placeholder"
              @pointerdown.stop.prevent="startZoomPan($event, 'overview')"
              @pointermove.stop.prevent="moveZoomPan"
              @pointerup.stop.prevent="stopZoomPan"
              @pointercancel.stop.prevent="stopZoomPan"
            >
              <div class="camera-overview-rect" :style="viewportRectStyle" />
            </div>
          </div>
          <video
            ref="pipVideoRef"
            class="camera-pip-video"
            autoplay
            muted
            playsinline
            webkit-playsinline
            @enterpictureinpicture="handlePipEnter"
            @leavepictureinpicture="handlePipLeave"
          />
          <canvas ref="pipCanvasRef" class="camera-pip-canvas" />
        </div>
      </LiquidGlass>

      <aside class="camera-side space-y-4 md:space-y-6">
        <LiquidGlass as="section" :radius="24" :optics="panelOptics" class="camera-device-panel">
          <div class="camera-panel-inner">
            <div class="camera-panel-head">
              <div class="camera-panel-title">
                <h3>设备列表</h3>
                <p>选择一路摄像头查看实时画面</p>
              </div>
              <span class="camera-count-chip">{{ cameras.length }} 路</span>
            </div>

            <div v-if="loading" class="camera-list-state">
              <Loader2 class="is-spinning" />
              正在加载摄像头
            </div>
            <div v-else-if="cameras.length === 0" class="camera-list-empty">
              <Cctv />
              <p>暂无摄像头</p>
            </div>
            <div v-else class="camera-device-list">
              <button
                v-for="camera in cameras"
                :key="camera.id"
                type="button"
                class="camera-device-item"
                :class="{ 'is-selected': selectedId === camera.id, 'is-disabled': !camera.enabled }"
                @click="selectCamera(camera)"
              >
                <div class="camera-device-row">
                  <div class="camera-device-copy">
                    <div class="camera-device-name">
                      <span class="camera-device-dot" :class="camera.enabled ? 'is-online' : 'is-offline'" />
                      <h4>{{ camera.name }}</h4>
                    </div>
                    <p class="camera-device-path">{{ camera.mediamtx_path }}</p>
                    <span class="camera-device-proto">{{ camera.onvif_enabled ? 'ONVIF' : 'RTSP' }}</span>
                  </div>
                  <div class="camera-device-actions">
                    <button type="button" title="测试连接" @click.stop="handleTest(camera)">
                      <Loader2 v-if="testingId === camera.id" class="is-spinning" />
                      <Play v-else />
                    </button>
                    <button type="button" title="编辑" @click.stop="openEdit(camera)">
                      <Pencil />
                    </button>
                    <button type="button" class="is-danger" title="删除" @click.stop="handleDelete(camera)">
                      <Trash2 />
                    </button>
                  </div>
                </div>
              </button>
            </div>
          </div>
        </LiquidGlass>

        <LiquidGlass as="section" :radius="24" :optics="panelOptics" class="camera-ptz-panel" :class="{ 'is-disabled': !canControlPtz }">
          <div class="camera-panel-inner">
            <div class="camera-panel-head">
              <div class="camera-panel-title">
                <h3>云台控制</h3>
                <p>{{ canControlPtz ? '按住方向键转动云台' : '当前摄像头未启用 ONVIF 云台' }}</p>
              </div>
              <span class="camera-count-chip">{{ ptzSpeedPercent }}%</span>
            </div>

            <label class="camera-speed-row">
              <span>速度</span>
              <input
                v-model.number="ptzSpeed"
                class="camera-speed-slider"
                type="range"
                min="0.05"
                max="1"
                step="0.05"
                aria-label="云台速度"
              >
            </label>

            <div class="camera-ptz-dpad">
              <div class="camera-ptz-grid">
                <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('up_left')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowUpLeft class="h-5 w-5" /></button>
                <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('up')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowUp class="h-5 w-5" /></button>
                <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('up_right')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowUpRight class="h-5 w-5" /></button>
                <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('left')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowLeft class="h-5 w-5" /></button>
                <button class="ptz-btn camera-ptz-stop" :disabled="!canControlPtz" @click="stopPtz(true)"><CircleStop class="h-5 w-5" /></button>
                <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('right')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowRight class="h-5 w-5" /></button>
                <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('down_left')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowDownLeft class="h-5 w-5" /></button>
                <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('down')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowDown class="h-5 w-5" /></button>
                <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('down_right')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowDownRight class="h-5 w-5" /></button>
              </div>
            </div>

            <div class="camera-ptz-zoom-row">
              <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('zoom_in')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz">
                <ZoomIn class="h-5 w-5" />
              </button>
              <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('zoom_out')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz">
                <ZoomOut class="h-5 w-5" />
              </button>
            </div>
          </div>
        </LiquidGlass>
      </aside>
    </div>

    <div v-if="showDialog" class="camera-dialog-layer">
      <div class="ikaros-surface ikaros-surface-strong camera-dialog">
        <header class="camera-dialog-head">
          <h2>{{ editingId ? '编辑摄像头' : '添加摄像头' }}</h2>
        </header>
        <div class="camera-dialog-body">
          <label class="camera-field">
            <span>名称</span>
            <input v-model="formData.name" type="text" placeholder="客厅摄像头">
          </label>
          <label class="camera-field">
            <span>MediaMTX 路径</span>
            <input v-model="formData.mediamtx_path" type="text" placeholder="自动生成">
          </label>
          <label class="camera-field is-wide">
            <span>RTSP 地址</span>
            <input v-model="formData.rtsp_url" type="text" placeholder="rtsp://user:pass@host:554/stream1">
          </label>
          <label class="camera-check">
            <input v-model="formData.enabled" type="checkbox">
            <span>启用摄像头</span>
          </label>
          <label class="camera-check">
            <input v-model="formData.onvif_enabled" type="checkbox">
            <span>启用 ONVIF PTZ</span>
          </label>
          <label class="camera-field">
            <span>ONVIF Host</span>
            <input v-model="formData.onvif_host" type="text" placeholder="192.168.1.179">
          </label>
          <label class="camera-field">
            <span>ONVIF Port</span>
            <input v-model.number="formData.onvif_port" type="number" min="1" max="65535">
          </label>
          <label class="camera-field">
            <span>ONVIF 用户名</span>
            <input v-model="formData.onvif_username" type="text" placeholder="admin">
          </label>
          <label class="camera-field">
            <span>ONVIF 密码</span>
            <input v-model="formData.onvif_password" type="text">
          </label>
        </div>
        <footer class="camera-dialog-foot">
          <button type="button" class="camera-dialog-cancel" @click="closeDialog">取消</button>
          <button type="button" class="ikaros-primary-action camera-dialog-save" :disabled="saving" @click="handleSave">
            {{ saving ? '保存中' : '保存' }}
          </button>
        </footer>
      </div>
    </div>
  </div>
</template>

<style scoped>
.camera-page {
  color: var(--ikaros-ink);
}

/* ---- Summary ---- */
.camera-summary {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .camera-summary {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.86);
}

.camera-summary-inner {
  display: grid;
  gap: 16px;
  padding: 20px 22px;
}

.camera-summary-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.camera-summary-title h1 {
  margin: 2px 0 0;
  color: var(--ikaros-ink);
  font-size: clamp(20px, 2vw, 26px);
  font-weight: 780;
  letter-spacing: -0.03em;
  line-height: 1.2;
}

.camera-summary-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}

.camera-summary-actions svg {
  width: 15px;
  height: 15px;
}

.camera-ghost-btn {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.4);
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 750;
  transition: border-color 160ms ease, color 160ms ease;
}

:global(.dark) .camera-ghost-btn {
  background: rgba(255, 255, 255, 0.06);
}

.camera-ghost-btn:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.camera-add-btn {
  border: 0;
  cursor: pointer;
}

.camera-summary-stats {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.camera-stat {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--ikaros-line);
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.35);
}

:global(.dark) .camera-stat {
  background: rgba(255, 255, 255, 0.04);
}

.camera-stat-icon {
  display: grid;
  width: 36px;
  height: 36px;
  flex: none;
  place-items: center;
  border: 1px solid rgba(232, 93, 142, 0.2);
  border-radius: 12px;
  background: rgba(232, 93, 142, 0.09);
  color: var(--ikaros-pink);
}

.camera-stat-icon.is-online {
  border-color: rgba(42, 140, 138, 0.22);
  background: rgba(42, 140, 138, 0.1);
  color: var(--ikaros-eye);
}

.camera-stat-icon svg {
  width: 17px;
  height: 17px;
}

.camera-stat-copy {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.camera-stat-copy span {
  color: var(--ikaros-muted);
  font-size: 11px;
  font-weight: 700;
}

.camera-stat-copy strong {
  color: var(--ikaros-ink);
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

/* ---- Live card ---- */
.camera-live-card {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) .camera-live-card {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.86);
}

.camera-page .camera-live-card {
  display: flex;
  flex-direction: column;
}

.camera-live-card :deep(.liquid-glass__content) {
  display: flex;
  min-height: 0;
  flex: 1 1 auto;
  flex-direction: column;
}

.camera-live-header {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--ikaros-line);
}

.camera-live-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 9px;
}

.camera-live-title h3 {
  margin: 0;
  overflow: hidden;
  color: var(--ikaros-ink);
  font-size: 15px;
  font-weight: 780;
  letter-spacing: -0.02em;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.camera-live-dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
  background: var(--ikaros-muted);
}

.camera-live-dot.is-live {
  background: var(--ikaros-eye);
  box-shadow: 0 0 8px rgba(42, 140, 138, 0.55);
  animation: camera-pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

.camera-live-dot.is-danger {
  background: #c63741;
}

.camera-live-chip {
  flex: none;
  padding: 3px 8px;
  border: 1px solid var(--ikaros-line);
  border-radius: 7px;
  background: var(--panel-muted);
  color: var(--ikaros-muted);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.04em;
}

.camera-live-chip.is-live {
  border-color: rgba(42, 140, 138, 0.24);
  background: rgba(42, 140, 138, 0.1);
  color: var(--ikaros-eye);
}

.camera-live-chip.is-danger {
  border-color: rgba(198, 55, 65, 0.22);
  background: rgba(198, 55, 65, 0.08);
  color: #c63741;
}

.camera-live-controls {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.camera-zoom-control {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 7px 11px;
  border: 1px solid var(--ikaros-line);
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.4);
}

:global(.dark) .camera-zoom-control {
  background: rgba(255, 255, 255, 0.05);
}

.camera-zoom-control.is-disabled {
  opacity: 0.5;
}

.camera-zoom-control > svg {
  width: 15px;
  height: 15px;
  flex: none;
  color: var(--ikaros-muted);
}

.camera-zoom-value {
  width: 34px;
  flex: none;
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 750;
  text-align: right;
}

.camera-zoom-slider {
  width: clamp(96px, 12vw, 150px);
  accent-color: var(--ikaros-pink);
}

.camera-pip-btn,
.camera-icon-btn,
.camera-mode-switch button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--ikaros-line);
  background: rgba(255, 255, 255, 0.4);
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 700;
  transition: border-color 160ms ease, color 160ms ease, background-color 160ms ease;
}

:global(.dark) :is(.camera-pip-btn, .camera-icon-btn, .camera-mode-switch button) {
  background: rgba(255, 255, 255, 0.05);
}

.camera-pip-btn {
  padding: 7px 12px;
  border-radius: 11px;
}

.camera-pip-btn svg {
  width: 15px;
  height: 15px;
}

.camera-pip-btn:hover,
.camera-icon-btn:hover,
.camera-mode-switch button:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.camera-pip-btn.is-active {
  border-color: rgba(42, 140, 138, 0.3);
  background: rgba(42, 140, 138, 0.1);
  color: var(--ikaros-eye);
}

.camera-live-controls button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.camera-mode-switch {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--ikaros-line);
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.4);
}

:global(.dark) .camera-mode-switch {
  background: rgba(255, 255, 255, 0.05);
}

.camera-mode-switch button {
  padding: 5px 10px;
  border: 0;
  border-radius: 9px;
  background: transparent;
}

.camera-mode-switch button.is-active {
  background: var(--ikaros-pink);
  color: #fff;
  box-shadow: 0 4px 12px rgba(232, 93, 142, 0.24);
}

.camera-icon-btn {
  width: 32px;
  height: 32px;
  justify-content: center;
  padding: 0;
  border-radius: 10px;
}

.camera-icon-btn svg {
  width: 15px;
  height: 15px;
}

.camera-player {
  position: relative;
  aspect-ratio: 16 / 9;
  background: #17131a;
}

.camera-player iframe {
  border: 0;
}

.camera-zoom-stage {
  touch-action: none;
  cursor: grab;
}

.camera-zoom-stage:active {
  cursor: grabbing;
}

.camera-preview-canvas {
  display: block;
  object-fit: contain;
  background: #17131a;
}

.camera-source-video {
  position: fixed;
  left: 0;
  top: 0;
  width: 320px;
  height: 180px;
  opacity: 0;
  pointer-events: none;
  z-index: -1;
}

.camera-hls-frame {
  transform-origin: center;
}

.camera-hls-frame--zoomed {
  pointer-events: none;
}

.camera-overview {
  position: absolute;
  right: 14px;
  bottom: 14px;
  z-index: 4;
  width: min(220px, 28vw);
  aspect-ratio: 16 / 9;
  overflow: hidden;
  border: 1px solid rgba(63, 182, 179, 0.85);
  border-radius: 10px;
  background: rgba(23, 19, 26, 0.78);
  box-shadow: 0 12px 28px rgba(23, 19, 26, 0.35);
}

.camera-overview canvas {
  display: block;
  object-fit: cover;
}

.camera-overview--placeholder {
  background:
    linear-gradient(135deg, rgba(63, 182, 179, 0.14), rgba(23, 19, 26, 0.86)),
    rgba(23, 19, 26, 0.82);
}

.camera-overview-rect {
  position: absolute;
  border: 2px solid #3fb6b3;
  box-shadow: 0 0 0 999px rgba(23, 19, 26, 0.32);
}

.camera-pip-video,
.camera-pip-canvas {
  position: fixed;
  left: 0;
  top: 0;
  width: 320px;
  height: 180px;
  opacity: 0;
  pointer-events: none;
  z-index: -1;
}

/* ---- Side panels ---- */
.camera-device-panel,
.camera-ptz-panel {
  --ikaros-glass-fill: rgba(255, 249, 252, 0.84);
}

:global(.dark) :is(.camera-device-panel, .camera-ptz-panel) {
  --ikaros-glass-fill: rgba(43, 34, 40, 0.86);
}

.camera-ptz-panel.is-disabled {
  opacity: 0.6;
}

.camera-panel-inner {
  display: grid;
  gap: 14px;
  padding: 18px;
}

.camera-panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.camera-panel-title h3 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 15px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.camera-panel-title p {
  margin: 3px 0 0;
  color: var(--ikaros-muted);
  font-size: 11px;
}

.camera-count-chip {
  flex: none;
  padding: 5px 10px;
  border: 1px solid var(--ikaros-line);
  border-radius: 999px;
  background: var(--panel-muted);
  color: var(--ikaros-copy);
  font-size: 11px;
  font-weight: 700;
}

.camera-list-state {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 2px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.camera-list-state svg {
  width: 16px;
  height: 16px;
}

.camera-list-empty {
  display: flex;
  min-height: 140px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  border: 1px dashed var(--ikaros-line);
  border-radius: 16px;
  color: var(--ikaros-muted);
  font-size: 13px;
}

.camera-list-empty svg {
  width: 26px;
  height: 26px;
}

.camera-list-empty p {
  margin: 0;
}

.camera-device-list {
  display: grid;
  gap: 9px;
}

.camera-device-item {
  position: relative;
  display: block;
  width: 100%;
  padding: 12px;
  border: 1px solid var(--ikaros-line);
  border-radius: 15px;
  background: rgba(255, 255, 255, 0.35);
  color: var(--ikaros-ink);
  font: inherit;
  text-align: left;
  transition: border-color 160ms ease, background-color 160ms ease, box-shadow 160ms ease;
}

:global(.dark) .camera-device-item {
  background: rgba(255, 255, 255, 0.04);
}

.camera-device-item:hover {
  border-color: rgba(232, 93, 142, 0.28);
}

.camera-device-item.is-selected {
  border-color: rgba(232, 93, 142, 0.42);
  background: rgba(232, 93, 142, 0.06);
  box-shadow: inset 3px 0 0 var(--ikaros-pink);
}

.camera-device-item.is-disabled .camera-device-copy {
  opacity: 0.62;
}

.camera-device-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.camera-device-copy {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.camera-device-name {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.camera-device-name h4 {
  margin: 0;
  overflow: hidden;
  color: var(--ikaros-ink);
  font-size: 13px;
  font-weight: 750;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.camera-device-dot {
  width: 8px;
  height: 8px;
  flex: none;
  border-radius: 50%;
}

.camera-device-dot.is-online {
  background: var(--ikaros-eye);
  box-shadow: 0 0 6px rgba(42, 140, 138, 0.5);
}

.camera-device-dot.is-offline {
  background: var(--ikaros-pink);
}

.camera-device-path {
  margin: 0;
  overflow: hidden;
  color: var(--ikaros-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.camera-device-proto {
  width: fit-content;
  padding: 2px 7px;
  border: 1px solid var(--ikaros-line);
  border-radius: 6px;
  background: var(--panel-muted);
  color: var(--ikaros-muted);
  font-size: 9px;
  font-weight: 800;
  letter-spacing: 0.06em;
}

.camera-device-actions {
  display: flex;
  flex: none;
  gap: 5px;
}

.camera-device-actions button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border: 1px solid var(--ikaros-line);
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.5);
  color: var(--ikaros-copy);
  transition: border-color 160ms ease, color 160ms ease, background-color 160ms ease;
}

:global(.dark) .camera-device-actions button {
  background: rgba(255, 255, 255, 0.06);
}

.camera-device-actions button:hover {
  border-color: rgba(232, 93, 142, 0.32);
  color: var(--ikaros-pink);
}

.camera-device-actions button.is-danger:hover {
  border-color: rgba(198, 55, 65, 0.3);
  background: rgba(198, 55, 65, 0.07);
  color: #c63741;
}

.camera-device-actions svg {
  width: 13px;
  height: 13px;
}

/* ---- PTZ ---- */
.camera-speed-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--ikaros-line);
  border-radius: 11px;
  background: rgba(255, 255, 255, 0.35);
}

:global(.dark) .camera-speed-row {
  background: rgba(255, 255, 255, 0.04);
}

.camera-speed-row > span {
  flex: none;
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 700;
}

.camera-speed-slider {
  min-width: 0;
  flex: 1;
  accent-color: var(--ikaros-eye);
}

.camera-ptz-dpad {
  width: min(200px, 100%);
  margin: 0 auto;
  padding: 8px;
  border: 1px solid var(--ikaros-line);
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.35);
  box-shadow: inset 0 2px 10px rgba(23, 19, 26, 0.05);
}

:global(.dark) .camera-ptz-dpad {
  background: rgba(255, 255, 255, 0.04);
}

.camera-ptz-grid {
  display: grid;
  aspect-ratio: 1;
  gap: 4px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.camera-ptz-zoom-row {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.ptz-btn {
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--ikaros-line);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.55);
  color: var(--ikaros-copy);
  transition: border-color 160ms ease, color 160ms ease, background-color 160ms ease;
  touch-action: none;
}

:global(.dark) .ptz-btn {
  background: rgba(255, 255, 255, 0.06);
}

.camera-ptz-grid .ptz-btn {
  border: 0;
  background: transparent;
  border-radius: 999px;
}

.camera-ptz-grid .ptz-btn:not(:disabled):hover {
  background: rgba(232, 93, 142, 0.1);
  color: var(--ikaros-pink);
}

.ptz-btn:disabled {
  opacity: 0.45;
}

.ptz-btn:not(:disabled):hover {
  border-color: rgba(232, 93, 142, 0.34);
  color: var(--ikaros-pink);
}

.ptz-btn:not(:disabled):active {
  background: rgba(232, 93, 142, 0.14);
  color: var(--ikaros-pink);
}

.camera-ptz-stop {
  background: rgba(232, 93, 142, 0.12) !important;
  color: var(--ikaros-pink) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

/* ---- Dialog ---- */
.camera-dialog-layer {
  position: fixed;
  z-index: 60;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 20px;
  background: rgba(23, 19, 26, 0.32);
  backdrop-filter: blur(6px);
  -webkit-backdrop-filter: blur(6px);
}

.camera-dialog {
  width: min(640px, 100%);
  max-height: 92vh;
  overflow-y: auto;
}

.camera-dialog-head {
  padding: 18px 22px;
  border-bottom: 1px solid var(--ikaros-line);
}

.camera-dialog-head h2 {
  margin: 0;
  color: var(--ikaros-ink);
  font-size: 16px;
  font-weight: 800;
  letter-spacing: -0.02em;
}

.camera-dialog-body {
  display: grid;
  gap: 14px;
  padding: 20px 22px;
}

.camera-field {
  display: grid;
  gap: 7px;
}

.camera-field span {
  color: var(--ikaros-copy);
  font-size: 12px;
  font-weight: 700;
}

.camera-field input {
  width: 100%;
  padding: 10px 13px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.55);
  color: var(--ikaros-ink);
  font-size: 13px;
  outline: none;
  transition: border-color 160ms ease, box-shadow 160ms ease, background-color 160ms ease;
}

:global(.dark) .camera-field input {
  background: rgba(255, 255, 255, 0.06);
}

.camera-field input:focus {
  border-color: rgba(232, 93, 142, 0.45);
  background: #fff;
  box-shadow: 0 0 0 3px rgba(232, 93, 142, 0.12);
}

:global(.dark) .camera-field input:focus {
  background: rgba(255, 255, 255, 0.09);
}

.camera-check {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 13px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.35);
  color: var(--ikaros-copy);
  font-size: 13px;
  cursor: pointer;
}

:global(.dark) .camera-check {
  background: rgba(255, 255, 255, 0.04);
}

.camera-check input {
  width: 15px;
  height: 15px;
  accent-color: var(--ikaros-pink);
}

.camera-dialog-foot {
  display: flex;
  gap: 10px;
  padding: 16px 22px;
  border-top: 1px solid var(--ikaros-line);
}

.camera-dialog-cancel {
  flex: 1;
  min-height: 40px;
  border: 1px solid var(--ikaros-line);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.45);
  color: var(--ikaros-copy);
  font-size: 13px;
  font-weight: 700;
}

:global(.dark) .camera-dialog-cancel {
  background: rgba(255, 255, 255, 0.06);
}

.camera-dialog-cancel:hover {
  border-color: rgba(232, 93, 142, 0.3);
  color: var(--ikaros-pink);
}

.camera-dialog-save {
  flex: 1;
  border: 0;
  cursor: pointer;
}

.camera-dialog-save:disabled {
  cursor: wait;
  opacity: 0.7;
}

.is-spinning {
  animation: camera-spin 850ms linear infinite;
}

@keyframes camera-spin {
  to {
    transform: rotate(360deg);
  }
}

@keyframes camera-pulse {
  0%, 100% {
    opacity: 1;
  }
  50% {
    opacity: 0.45;
  }
}

@media (min-width: 769px) {
  .camera-page {
    height: calc(100vh - 132px);
    height: calc(100dvh - 132px);
    min-height: 0;
    gap: 12px;
    overflow: hidden;
    padding: 16px !important;
  }

  .camera-summary {
    flex: 0 0 auto;
  }

  .camera-summary-inner {
    gap: 12px;
    padding: 14px 20px;
  }

  .camera-summary-title h1 {
    margin-top: 2px;
    font-size: 1.25rem;
    line-height: 1.3;
  }

  .camera-summary-stats {
    gap: 10px;
  }

  .camera-stat {
    padding: 10px 14px;
  }

  .camera-stat-copy strong {
    font-size: 1.45rem;
    line-height: 1.1;
  }

  .camera-main-grid {
    flex: 1 1 auto;
    min-height: 0;
    gap: 14px !important;
    grid-template-columns: minmax(0, 1fr) 352px;
  }

  .camera-page .camera-live-card {
    min-height: 0;
  }

  .camera-live-header {
    padding: 10px 14px;
  }

  .camera-live-title h3 {
    font-size: 1.05rem;
    line-height: 1.25;
  }

  .camera-player {
    min-height: 0;
    flex: 1 1 auto;
    aspect-ratio: auto;
  }

  .camera-side {
    min-height: 0;
    overflow-y: auto;
  }

  .camera-panel-inner {
    padding: 14px;
  }

  .ptz-btn {
    min-height: 38px !important;
  }

  .camera-dialog-body {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .camera-dialog-body .is-wide {
    grid-column: span 2;
  }
}

@media (max-width: 768px) {
  .camera-page {
    height: auto;
    min-height: 100%;
    gap: 12px;
    overflow: visible;
    overscroll-behavior-y: contain;
    -webkit-overflow-scrolling: touch;
    padding: 0 0 max(20px, env(safe-area-inset-bottom)) !important;
  }

  .camera-live-card {
    border-top: 0;
    border-right: 0;
    border-left: 0;
    border-radius: 0 !important;
  }

  .camera-live-header {
    padding: 10px 12px;
  }

  .camera-live-controls {
    width: 100%;
    justify-content: flex-start;
  }

  .camera-zoom-control {
    flex: 1 1 100%;
  }

  .camera-zoom-slider {
    width: auto;
    min-width: 0;
    flex: 1;
  }

  .camera-live-title h3 {
    max-width: 52vw;
    font-size: 1rem;
  }

  .camera-player {
    height: 40vh;
    height: min(40svh, 320px);
    min-height: 180px;
    aspect-ratio: auto;
  }

  .camera-overview {
    right: 10px;
    bottom: 10px;
    width: min(168px, 42vw);
  }

  .camera-summary,
  .camera-side {
    margin-right: 12px;
    margin-left: 12px;
  }

  .camera-side {
    display: flex;
    flex-direction: column;
    padding-bottom: max(24px, env(safe-area-inset-bottom));
  }

  .camera-ptz-panel {
    order: 1;
  }

  .camera-device-panel {
    order: 2;
  }
}

@media (max-width: 430px) {
  .camera-player {
    height: 36vh;
    height: min(36svh, 300px);
    min-height: 170px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .is-spinning,
  .camera-live-dot.is-live {
    animation: none;
  }
}
</style>
