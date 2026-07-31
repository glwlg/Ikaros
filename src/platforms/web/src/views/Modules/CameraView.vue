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
    Loader2,
    Pencil,
    PictureInPicture2,
    Play,
    Plus,
    RefreshCw,
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

type PlayerMode = 'webrtc' | 'hls'

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
  <div class="camera-page flex min-h-screen flex-col gap-4 bg-slate-50 p-3 md:gap-6 md:p-8">
    <section class="camera-summary order-2 rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm md:order-1">
      <div class="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Module</div>
          <h2 class="mt-1 text-2xl font-semibold text-slate-900">实时监控</h2>
        </div>
        <div class="flex items-center gap-2">
          <button @click="loadData(true)" class="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700 transition hover:bg-slate-100">
            <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': refreshing }" />
            刷新
          </button>
          <button @click="openCreate" class="inline-flex items-center gap-2 rounded-2xl bg-blue-500 px-4 py-3 text-sm font-medium text-white shadow-lg shadow-blue-500/20 transition hover:bg-blue-600">
            <Plus class="h-4 w-4" />
            添加摄像头
          </button>
        </div>
      </div>

      <div class="mt-6 grid gap-4 md:grid-cols-3">
        <div class="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
          <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Cameras</div>
          <div class="mt-3 text-3xl font-semibold text-slate-950">{{ cameras.length }}</div>
        </div>
        <div class="rounded-[24px] border border-slate-200 bg-slate-50 p-4">
          <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Online</div>
          <div class="mt-3 text-3xl font-semibold text-slate-950">{{ enabledCount }}</div>
        </div>
        <div class="rounded-[24px] border border-slate-200 bg-slate-950 p-4 text-slate-100">
          <div class="text-xs uppercase tracking-[0.24em] text-slate-500">PTZ</div>
          <div class="mt-3 text-2xl font-semibold">{{ ptzCount }}</div>
        </div>
      </div>
    </section>

    <div class="camera-main-grid order-1 grid gap-4 md:order-2 md:gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
      <section class="camera-live-card overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-sm">
        <div class="camera-live-header flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-4">
          <div class="min-w-0">
            <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Live</div>
            <h3 class="mt-1 truncate text-xl font-semibold text-slate-950">{{ selectedCamera?.name || '未选择摄像头' }}</h3>
          </div>
          <div class="camera-live-controls flex flex-wrap items-center justify-end gap-2">
            <div class="camera-zoom-control flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2" :class="{ 'opacity-50': !canUseDigitalZoom }">
              <ZoomOut class="h-4 w-4 text-slate-400" />
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
              <ZoomIn class="h-4 w-4 text-slate-400" />
              <span class="w-9 text-right text-xs font-semibold text-slate-600">{{ zoomLabel }}</span>
            </div>
            <button
              class="inline-flex items-center gap-2 rounded-xl border px-3 py-2 text-sm transition"
              :class="pipActive ? 'border-blue-200 bg-blue-50 text-blue-600' : 'border-slate-200 bg-white text-slate-600 hover:border-blue-200 hover:text-blue-600'"
              :disabled="!canOpenZoomPip"
              @click="toggleZoomedPictureInPicture"
            >
              <PictureInPicture2 class="h-4 w-4" />
              画中画
            </button>
            <button class="rounded-xl border px-3 py-2 text-sm" :class="playerMode === 'webrtc' ? 'border-blue-200 bg-blue-50 text-blue-600' : 'border-slate-200 bg-white text-slate-600'" @click="playerMode = 'webrtc'">WebRTC</button>
            <button class="rounded-xl border px-3 py-2 text-sm" :class="playerMode === 'hls' ? 'border-blue-200 bg-blue-50 text-blue-600' : 'border-slate-200 bg-white text-slate-600'" @click="playerMode = 'hls'">HLS</button>
            <button class="rounded-xl border border-slate-200 bg-white p-2 text-slate-500 transition hover:border-blue-200 hover:text-blue-600" @click="loadStream" :disabled="streamLoading || !selectedCamera">
              <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': streamLoading }" />
            </button>
          </div>
        </div>

        <div class="camera-player relative bg-slate-950">
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
      </section>

      <aside class="camera-side space-y-4 md:space-y-6">
        <section class="camera-device-panel rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Devices</div>
              <h3 class="mt-1 text-lg font-semibold text-slate-950">摄像头列表</h3>
            </div>
            <span class="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-sm text-slate-600">{{ cameras.length }} 路</span>
          </div>

          <div class="mt-4">
            <div v-if="loading" class="flex justify-center py-10">
              <Loader2 class="h-7 w-7 animate-spin text-blue-500" />
            </div>
            <div v-else-if="cameras.length === 0" class="flex flex-col items-center justify-center py-12 text-slate-400">
              <Cctv class="mb-3 h-12 w-12 text-slate-300" />
              <p>暂无摄像头</p>
            </div>
            <div v-else class="space-y-3">
              <button
                v-for="camera in cameras"
                :key="camera.id"
                type="button"
                class="w-full rounded-[24px] border p-4 text-left transition"
                :class="selectedId === camera.id ? 'border-blue-200 bg-blue-50' : 'border-slate-200 bg-slate-50 hover:bg-slate-100'"
                @click="selectCamera(camera)"
              >
                <div class="flex items-start justify-between gap-3">
                  <div class="min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="h-2 w-2 rounded-full" :class="camera.enabled ? 'bg-emerald-500' : 'bg-slate-300'" />
                      <h4 class="truncate font-semibold text-slate-950">{{ camera.name }}</h4>
                    </div>
                    <p class="mt-2 truncate font-mono text-xs text-slate-500">{{ camera.mediamtx_path }}</p>
                    <p class="mt-1 text-xs text-slate-400">{{ camera.onvif_enabled ? 'ONVIF' : 'RTSP' }}</p>
                  </div>
                  <div class="flex shrink-0 items-center gap-1">
                    <button type="button" class="rounded-xl border border-slate-200 bg-white p-2 text-slate-500 hover:text-blue-600" @click.stop="handleTest(camera)">
                      <Loader2 v-if="testingId === camera.id" class="h-4 w-4 animate-spin" />
                      <Play v-else class="h-4 w-4" />
                    </button>
                    <button type="button" class="rounded-xl border border-slate-200 bg-white p-2 text-slate-500 hover:text-blue-600" @click.stop="openEdit(camera)">
                      <Pencil class="h-4 w-4" />
                    </button>
                    <button type="button" class="rounded-xl border border-slate-200 bg-white p-2 text-slate-500 hover:text-rose-600" @click.stop="handleDelete(camera)">
                      <Trash2 class="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </button>
            </div>
          </div>
        </section>

        <section class="camera-ptz-panel rounded-[28px] border border-slate-200 bg-white p-5 shadow-sm" :class="{ 'opacity-60': !canControlPtz }">
          <div class="flex items-center justify-between gap-3">
            <div>
              <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Control</div>
              <h3 class="mt-1 text-lg font-semibold text-slate-950">云台控制</h3>
            </div>
            <span class="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-sm font-medium text-slate-600">{{ ptzSpeedPercent }}%</span>
          </div>

          <label class="mt-4 flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
            <span class="shrink-0 text-sm font-medium text-slate-600">速度</span>
            <input
              v-model.number="ptzSpeed"
              class="camera-speed-slider min-w-0 flex-1"
              type="range"
              min="0.05"
              max="1"
              step="0.05"
              aria-label="云台速度"
            >
          </label>

          <div class="mt-3 grid grid-cols-3 gap-2">
            <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('up_left')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowUpLeft class="h-5 w-5" /></button>
            <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('up')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowUp class="h-5 w-5" /></button>
            <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('up_right')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowUpRight class="h-5 w-5" /></button>
            <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('left')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowLeft class="h-5 w-5" /></button>
            <button class="ptz-btn bg-slate-950 text-white" :disabled="!canControlPtz" @click="stopPtz(true)"><CircleStop class="h-5 w-5" /></button>
            <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('right')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowRight class="h-5 w-5" /></button>
            <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('down_left')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowDownLeft class="h-5 w-5" /></button>
            <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('down')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowDown class="h-5 w-5" /></button>
            <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('down_right')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz"><ArrowDownRight class="h-5 w-5" /></button>
          </div>

          <div class="mt-3 grid grid-cols-2 gap-2">
            <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('zoom_in')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz">
              <ZoomIn class="h-5 w-5" />
            </button>
            <button class="ptz-btn" :disabled="!canControlPtz" @pointerdown.prevent="startPtz('zoom_out')" @pointerup.prevent="stopPtz" @pointerleave.prevent="stopPtz" @pointercancel.prevent="stopPtz" @lostpointercapture.prevent="stopPtz">
              <ZoomOut class="h-5 w-5" />
            </button>
          </div>
        </section>
      </aside>
    </div>

    <div v-if="showDialog" class="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4">
      <div class="max-h-[92vh] w-full max-w-2xl overflow-y-auto rounded-[28px] border border-slate-200 bg-white shadow-[0_24px_60px_rgba(15,23,42,0.2)]">
        <div class="border-b border-slate-200 px-6 py-5">
          <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Form</div>
          <h2 class="mt-1 text-xl font-semibold text-slate-950">{{ editingId ? '编辑摄像头' : '添加摄像头' }}</h2>
        </div>
        <div class="grid gap-4 p-6 md:grid-cols-2">
          <label class="block">
            <span class="mb-1 block text-sm text-slate-500">名称</span>
            <input v-model="formData.name" class="w-full rounded-2xl border border-slate-200 px-4 py-3" type="text" placeholder="客厅摄像头">
          </label>
          <label class="block">
            <span class="mb-1 block text-sm text-slate-500">MediaMTX 路径</span>
            <input v-model="formData.mediamtx_path" class="w-full rounded-2xl border border-slate-200 px-4 py-3" type="text" placeholder="自动生成">
          </label>
          <label class="block md:col-span-2">
            <span class="mb-1 block text-sm text-slate-500">RTSP 地址</span>
            <input v-model="formData.rtsp_url" class="w-full rounded-2xl border border-slate-200 px-4 py-3" type="text" placeholder="rtsp://user:pass@host:554/stream1">
          </label>
          <label class="inline-flex items-center gap-3 rounded-2xl border border-slate-200 px-4 py-3">
            <input v-model="formData.enabled" type="checkbox" class="h-4 w-4">
            <span class="text-sm text-slate-600">启用摄像头</span>
          </label>
          <label class="inline-flex items-center gap-3 rounded-2xl border border-slate-200 px-4 py-3">
            <input v-model="formData.onvif_enabled" type="checkbox" class="h-4 w-4">
            <span class="text-sm text-slate-600">启用 ONVIF PTZ</span>
          </label>
          <label class="block">
            <span class="mb-1 block text-sm text-slate-500">ONVIF Host</span>
            <input v-model="formData.onvif_host" class="w-full rounded-2xl border border-slate-200 px-4 py-3" type="text" placeholder="192.168.1.179">
          </label>
          <label class="block">
            <span class="mb-1 block text-sm text-slate-500">ONVIF Port</span>
            <input v-model.number="formData.onvif_port" class="w-full rounded-2xl border border-slate-200 px-4 py-3" type="number" min="1" max="65535">
          </label>
          <label class="block">
            <span class="mb-1 block text-sm text-slate-500">ONVIF 用户名</span>
            <input v-model="formData.onvif_username" class="w-full rounded-2xl border border-slate-200 px-4 py-3" type="text" placeholder="admin">
          </label>
          <label class="block">
            <span class="mb-1 block text-sm text-slate-500">ONVIF 密码</span>
            <input v-model="formData.onvif_password" class="w-full rounded-2xl border border-slate-200 px-4 py-3" type="text">
          </label>
        </div>
        <div class="flex gap-3 border-t border-slate-200 p-6">
          <button @click="closeDialog" class="flex-1 rounded-2xl border border-slate-200 bg-white py-3 font-medium text-slate-600">取消</button>
          <button @click="handleSave" class="flex-1 rounded-2xl bg-blue-500 py-3 font-medium text-white shadow-lg shadow-blue-500/25" :disabled="saving">
            {{ saving ? '保存中' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.camera-player {
  aspect-ratio: 16 / 9;
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
  background: #020617;
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

.camera-live-video {
  transform-origin: center;
  object-fit: contain;
  background: #020617;
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
  border: 1px solid rgba(74, 222, 128, 0.9);
  background: rgba(2, 6, 23, 0.78);
  box-shadow: 0 12px 28px rgba(2, 6, 23, 0.35);
}

.camera-overview canvas {
  display: block;
  object-fit: cover;
}

.camera-overview--placeholder {
  background:
    linear-gradient(135deg, rgba(148, 163, 184, 0.25), rgba(15, 23, 42, 0.86)),
    rgba(2, 6, 23, 0.82);
}

.camera-overview-rect {
  position: absolute;
  border: 2px solid #22c55e;
  box-shadow: 0 0 0 999px rgba(2, 6, 23, 0.32);
}

.camera-zoom-slider {
  width: clamp(96px, 12vw, 150px);
  accent-color: #2f7cf6;
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

.camera-live-controls button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.camera-speed-slider {
  accent-color: #2f7cf6;
}

@media (min-width: 769px) {
  .camera-page {
    height: 100vh;
    height: 100dvh;
    min-height: 0;
    gap: 12px;
    overflow: hidden;
    padding: 16px !important;
  }

  .camera-summary {
    flex: 0 0 auto;
    padding: 14px 20px !important;
  }

  .camera-summary h2 {
    margin-top: 2px !important;
    font-size: 1.25rem;
    line-height: 1.3;
  }

  .camera-summary > div:first-child {
    align-items: center;
  }

  .camera-summary > div:first-child + div {
    margin-top: 12px !important;
    gap: 10px;
  }

  .camera-summary > div:first-child + div > div {
    padding: 10px 14px !important;
  }

  .camera-summary > div:first-child + div > div > div:last-child {
    margin-top: 6px !important;
    font-size: 1.45rem;
    line-height: 1.1;
  }

  .camera-main-grid {
    flex: 1 1 auto;
    min-height: 0;
    gap: 14px !important;
    grid-template-columns: minmax(0, 1fr) 352px;
  }

  .camera-live-card {
    display: flex;
    min-height: 0;
    flex-direction: column;
  }

  .camera-live-header {
    flex: 0 0 auto;
    padding: 10px 14px !important;
  }

  .camera-live-controls {
    gap: 8px;
  }

  .camera-live-header h3 {
    margin-top: 2px !important;
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

  .camera-side > section {
    padding: 14px !important;
  }

  .ptz-btn {
    min-height: 38px !important;
  }
}

.ptz-btn {
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  border: 1px solid #e5ebf3;
  background: #ffffff;
  color: #475569;
  transition: all 0.16s ease;
}

.ptz-btn:disabled {
  opacity: 0.45;
}

.ptz-btn:not(:disabled):hover {
  border-color: #9ec5ff;
  color: #2f7cf6;
}

@media (max-width: 768px) {
  .camera-page {
    height: 100vh;
    height: 100dvh;
    min-height: 0;
    gap: 12px;
    overflow-y: auto;
    overscroll-behavior-y: contain;
    -webkit-overflow-scrolling: touch;
    padding: 0 0 max(20px, env(safe-area-inset-bottom)) !important;
    background: #f7f9fc;
  }

  .camera-live-card {
    border-radius: 0 !important;
    border-left: 0;
    border-right: 0;
    border-top: 0;
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

  .camera-live-header h3 {
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
    margin-left: 12px;
    margin-right: 12px;
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
</style>
