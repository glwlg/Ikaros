/**
 * Vue-oriented copy-refraction adaptation of @samasante/liquid-glass.
 * Original displacement-map implementation: Copyright (c) 2026 Sam Asante.
 * Licensed under MIT; see components/liquid-glass/LICENSE.samasante-liquid-glass.
 */

export interface LiquidGlassOptics {
    mapSize: number
    strength: number
    scaleX?: number
    scaleY?: number
    depth: number
    dispersion: number
    clipToShape: boolean
    softEdge: boolean
    frost: number
    saturate: number
    brightness: number
    specular: number
    sheenAngle: number
    glow: number
    glowSpread: number
    glowFalloff: number
    sheen: number
    sheenWidth: number
    sheenFalloff: number
    curvature: number
    splay: number
    bend: number
    bendWidth: number
}

export const LIQUID_GLASS_DEFAULTS: LiquidGlassOptics = {
    mapSize: 256,
    strength: 0.06,
    depth: 0.72,
    dispersion: 0.46,
    clipToShape: true,
    softEdge: true,
    frost: 4,
    saturate: 1.22,
    brightness: 0,
    specular: 1.15,
    sheenAngle: 45,
    glow: 0.22,
    glowSpread: 1,
    glowFalloff: 0.8,
    sheen: 0.78,
    sheenWidth: 3,
    sheenFalloff: 1.5,
    curvature: 0.38,
    splay: 0,
    bend: 0.62,
    bendWidth: 0.12,
}

export const DISPERSION_SPREAD = 0.22

export const mergeLiquidGlassOptics = (
    optics?: Partial<LiquidGlassOptics>,
): LiquidGlassOptics => ({ ...LIQUID_GLASS_DEFAULTS, ...(optics || {}) })

export const matrixForAxisScale = (x: number, y: number) =>
    `${x} 0 0 0 ${0.5 * (1 - x)}  0 ${y} 0 0 ${0.5 * (1 - y)}  0 0 1 0 0  0 0 0 1 0`

export interface LiquidGlassCopyGeometry {
    bleed: number
    copyWidth: number
    copyHeight: number
    displacementScale: number
    filterX: 0
    filterY: 0
    filterWidth: number
    filterHeight: number
    mapX: number
    mapY: number
}

export const buildLiquidGlassCopyGeometry = ({
    width,
    height,
    strengthX,
    strengthY,
    dispersion,
    depth,
}: {
    width: number
    height: number
    strengthX: number
    strengthY: number
    dispersion: number
    depth: number
}): LiquidGlassCopyGeometry => {
    const safeWidth = Math.max(0, width)
    const safeHeight = Math.max(0, height)
    const diagonal = Math.sqrt((safeWidth * safeWidth + safeHeight * safeHeight) / 2)
    const displacementScale = Math.max(0, strengthX, strengthY) * diagonal
    const dispersionReach = 1 + DISPERSION_SPREAD * Math.max(0, dispersion)
    const bleed = safeWidth > 0 && safeHeight > 0
        ? Math.ceil(displacementScale * dispersionReach * 0.5 + Math.max(0, depth) + 28) + 16
        : 0
    const copyWidth = safeWidth + 2 * bleed
    const copyHeight = safeHeight + 2 * bleed

    return {
        bleed,
        copyWidth,
        copyHeight,
        displacementScale,
        filterX: 0,
        filterY: 0,
        filterWidth: copyWidth,
        filterHeight: copyHeight,
        mapX: bleed,
        mapY: bleed,
    }
}

interface LensMapShape {
    lensHalfWidth: number
    lensHalfHeight: number
    borderRadius: number
    depth: number
    clipToShape: boolean
    softEdge: boolean
    sheenAngle: number
    glow: number
    glowSpread: number
    glowFalloff: number
    sheen: number
    sheenWidth: number
    sheenFalloff: number
    curvature: number
    splay: number
    bend: number
    bendWidth: number
}

export interface LensMapGenerator {
    generate(shape: LensMapShape): string
    dispose(): void
}

interface DomeConstants {
    rx: number
    ry: number
    scaleX: number
    scaleY: number
}

const erf = (value: number) => Math.tanh(Math.sqrt(Math.PI) * value)

const domeGradientMean = (radius: number, halfExtent: number) => (
    halfExtent > 0
        ? (radius - Math.sqrt(radius * radius - halfExtent * halfExtent)) / halfExtent
        : 0
)

const computeDomeConstants = (
    capDepth: number,
    halfWidth: number,
    halfHeight: number,
): DomeConstants => {
    const cap = Math.max(0.01, Math.min(capDepth, Math.min(halfWidth, halfHeight) - 1))
    const rx = (halfWidth * halfWidth + cap * cap) / (2 * cap)
    const ry = (halfHeight * halfHeight + cap * cap) / (2 * cap)
    const meanX = domeGradientMean(rx, halfWidth)
    const meanY = domeGradientMean(ry, halfHeight)
    return {
        rx,
        ry,
        scaleX: meanX > 0 ? 0.5 / meanX : 1,
        scaleY: meanY > 0 ? 0.5 / meanY : 1,
    }
}

const domeGradient = (distance: number, radius: number, scale: number) => {
    const inside = Math.min(distance, radius * (1 - 1e-3))
    return (inside / Math.sqrt(radius * radius - inside * inside)) * scale
}

const encodeAxis = (signed: number) => ((0.5 + signed) * 255 + 0.5) | 0
const encodeSpecular = (specular: number) => (127 * specular + 128 + 0.5) | 0

export const createLensMapGenerator = (requestedSize: number): LensMapGenerator => {
    const size = Math.max(32, Math.round(requestedSize / 2) * 2)
    let canvas: HTMLCanvasElement | null = null
    let context: CanvasRenderingContext2D | null = null
    let image: ImageData | null = null
    let domeLut: Float32Array | null = null
    let cachedDomeDepth = -Infinity
    let cachedHalfWidth = -Infinity
    let cachedHalfHeight = -Infinity
    let dome: DomeConstants | null = null

    return {
        generate(shape) {
            if (!canvas) {
                canvas = document.createElement('canvas')
                canvas.width = size
                canvas.height = size
                context = canvas.getContext('2d')
                if (!context) throw new Error('Canvas 2D context is required for Liquid Glass')
                image = context.createImageData(size, size)
            }

            const {
                lensHalfWidth: halfWidth,
                lensHalfHeight: halfHeight,
                borderRadius,
                depth,
                clipToShape,
                softEdge,
                sheenAngle,
                glow,
                glowSpread,
                glowFalloff,
                sheen,
                sheenWidth,
                sheenFalloff,
                curvature,
                splay,
                bend,
                bendWidth,
            } = shape
            const data = image!.data
            const half = size >> 1
            const radius = Math.min(borderRadius, Math.min(halfWidth, halfHeight))
            const minHalf = Math.min(halfWidth, halfHeight)
            const depthPx = Math.min(depth * minHalf, minHalf - 1)
            const innerHalfWidth = Math.max(0, halfWidth - depthPx)
            const innerHalfHeight = Math.max(0, halfHeight - depthPx)
            const innerRadius = Math.max(
                0,
                Math.min(borderRadius, Math.min(innerHalfWidth, innerHalfHeight)),
            )
            const falloff = depthPx > 0 ? Math.SQRT1_2 / depthPx : 1e6
            const hasSpecular = glow > 0 || sheen > 0
            const angle = (sheenAngle * Math.PI) / 180
            const cosAngle = Math.cos(angle)
            const sinAngle = Math.sin(angle)
            const edgeInverse = sheenWidth > 0 ? 1 / sheenWidth : 0
            const glowReachInverse = 1 / Math.max(2, glowSpread * minHalf)
            const stepX = (2 * halfWidth) / size
            const stepY = (2 * halfHeight) / size
            const inverseWidth = 1 / halfWidth
            const inverseHeight = 1 / halfHeight
            const hasDome = curvature > 0
            const domeDepth = curvature * minHalf
            const hasSplay = splay > 0
            const hasBend = bend > 0
            const bendInverse = 1 / Math.max(2, bendWidth * minHalf)

            const cornerDistance = (x: number, y: number) => (
                x > 0 || y > 0 ? Math.sqrt(x * x + y * y) : 0
            )

            if (hasDome && (
                !dome
                || Math.abs(domeDepth - cachedDomeDepth) > 0.5
                || Math.abs(halfWidth - cachedHalfWidth) > 1
                || Math.abs(halfHeight - cachedHalfHeight) > 1
            )) {
                dome = computeDomeConstants(domeDepth, halfWidth, halfHeight)
                cachedDomeDepth = domeDepth
                cachedHalfWidth = halfWidth
                cachedHalfHeight = halfHeight
                domeLut = null
            }
            if (hasDome && !domeLut) {
                domeLut = new Float32Array(half)
                const radiusSquared = dome!.rx * dome!.rx
                const radiusMaximum = dome!.rx * (1 - 1e-3)
                for (let column = 0; column < half; column += 1) {
                    const x = -((column + 0.5) * stepX - halfWidth)
                    const clamped = x < radiusMaximum ? x : radiusMaximum
                    domeLut[column] = (
                        clamped / Math.sqrt(radiusSquared - clamped * clamped)
                    ) * dome!.scaleX
                }
            }

            const lut = hasDome ? domeLut : null
            const splayHalf = 0.5 * minHalf
            const splayInverse = splayHalf > 0 ? 1 / splayHalf : 0
            const sheenNormalization = Math.SQRT1_2

            for (let row = 0; row < half; row += 1) {
                const mirrorRow = size - 1 - row
                const y = -((row + 0.5) * stepY - halfHeight)
                const edgeY = y - halfHeight + radius
                const innerEdgeY = softEdge ? y - innerHalfHeight + innerRadius : 0
                const directionYBase = hasDome && lut
                    ? domeGradient(y, dome!.ry, dome!.scaleY)
                    : Math.min(1, y * inverseHeight)
                const normalizedY = Math.min(1, y * inverseHeight)
                const splayY = hasSplay
                    ? Math.max(0, 1 - (halfHeight - y) * splayInverse)
                    : 0
                const rowBase = row * size
                const mirrorRowBase = mirrorRow * size

                for (let column = 0; column < half; column += 1) {
                    const mirrorColumn = size - 1 - column
                    const x = -((column + 0.5) * stepX - halfWidth)
                    const edgeX = x - halfWidth + radius
                    const signedDistance = (
                        cornerDistance(Math.max(0, edgeX), Math.max(0, edgeY))
                        + (edgeX > edgeY
                            ? (edgeX > 0 ? 0 : edgeX)
                            : (edgeY > 0 ? 0 : edgeY))
                        - radius
                    )
                    const indexTopLeft = (rowBase + column) * 4
                    const indexTopRight = (rowBase + mirrorColumn) * 4
                    const indexBottomLeft = (mirrorRowBase + column) * 4
                    const indexBottomRight = (mirrorRowBase + mirrorColumn) * 4

                    if (clipToShape && signedDistance >= 0) {
                        for (const index of [
                            indexTopLeft,
                            indexTopRight,
                            indexBottomLeft,
                            indexBottomRight,
                        ]) {
                            data[index] = 128
                            data[index + 1] = 128
                            data[index + 2] = 128
                            data[index + 3] = 255
                        }
                        continue
                    }

                    let directionX = lut ? (lut[column] ?? 0) : Math.min(1, x * inverseWidth)
                    let directionY = directionYBase
                    if (hasSplay) {
                        const yAttenuation = splayY * splay
                        const xAttenuation = Math.max(
                            0,
                            1 - (halfWidth - x) * splayInverse,
                        ) * splay
                        if (yAttenuation > 0.001 || xAttenuation > 0.001) {
                            const previousX = directionX
                            const previousY = directionY
                            directionX *= 1 - yAttenuation
                            directionY *= 1 - xAttenuation
                            const previousLength = Math.hypot(previousX, previousY)
                            const nextLength = Math.hypot(directionX, directionY)
                            if (nextLength > 0.001) {
                                const restore = previousLength / nextLength
                                directionX *= restore
                                directionY *= restore
                            }
                        }
                    }

                    let edgeOpacity = 1
                    if (softEdge) {
                        const innerX = x - innerHalfWidth + innerRadius
                        const innerDistance = (
                            cornerDistance(Math.max(0, innerX), Math.max(0, innerEdgeY))
                            + (innerX > innerEdgeY
                                ? (innerX > 0 ? 0 : innerX)
                                : (innerEdgeY > 0 ? 0 : innerEdgeY))
                            - innerRadius
                        )
                        edgeOpacity = 0.5 * (1 + erf(innerDistance * falloff))
                    }

                    let displacementX = 0.5 * directionX * edgeOpacity
                    let displacementY = 0.5 * directionY * edgeOpacity
                    if (hasBend) {
                        const bendPosition = signedDistance < 0
                            ? Math.max(0, 1 + signedDistance * bendInverse)
                            : 0
                        if (bendPosition > 0) {
                            const directionLength = Math.hypot(directionX, directionY)
                            if (directionLength > 1e-4) {
                                const meniscus = 6.75
                                    * bendPosition
                                    * bendPosition
                                    * (1 - bendPosition)
                                const amount = (
                                    0.5 * bend * meniscus * edgeOpacity
                                ) / directionLength
                                displacementX += directionX * amount
                                displacementY += directionY * amount
                            }
                        }
                    }

                    let specularMain = 0
                    let specularCross = 0
                    if (hasSpecular) {
                        const normalizedX = Math.min(1, x * inverseWidth)
                        const axisMain = Math.min(
                            1,
                            Math.abs(normalizedX * cosAngle + normalizedY * sinAngle)
                                * sheenNormalization,
                        )
                        const axisCross = Math.min(
                            1,
                            Math.abs(normalizedX * cosAngle - normalizedY * sinAngle)
                                * sheenNormalization,
                        )
                        if (sheen > 0) {
                            const band = signedDistance < 0
                                ? Math.max(0, 1 + signedDistance * edgeInverse)
                                : 0
                            const base = sheen * Math.pow(band, sheenFalloff)
                            specularMain += base * (0.16 + 0.84 * Math.pow(axisMain, 1.6))
                            specularCross += base * (0.16 + 0.84 * Math.pow(axisCross, 1.6))
                        }
                        if (glow > 0) {
                            const reach = signedDistance < 0
                                ? Math.min(1, -signedDistance * glowReachInverse)
                                : 1
                            const distance = 1 - reach
                            const innerGlow = glow * Math.pow(
                                distance * distance * (3 - 2 * distance),
                                glowFalloff,
                            ) * edgeOpacity
                            specularMain += innerGlow * (0.6 + 0.4 * axisMain)
                            specularCross += innerGlow * (0.6 + 0.4 * axisCross)
                        }
                        specularMain = Math.max(-1, Math.min(1, specularMain))
                        specularCross = Math.max(-1, Math.min(1, specularCross))
                    }

                    const redPositive = encodeAxis(displacementX)
                    const redNegative = encodeAxis(-displacementX)
                    const greenPositive = encodeAxis(displacementY)
                    const greenNegative = encodeAxis(-displacementY)
                    const blueMain = encodeSpecular(specularMain)
                    const blueCross = encodeSpecular(specularCross)

                    const targets: Array<[number, number, number, number]> = [
                        [indexTopLeft, redPositive, greenPositive, blueMain],
                        [indexTopRight, redNegative, greenPositive, blueCross],
                        [indexBottomLeft, redPositive, greenNegative, blueCross],
                        [indexBottomRight, redNegative, greenNegative, blueMain],
                    ]
                    for (const [index, red, green, blue] of targets) {
                        data[index] = red
                        data[index + 1] = green
                        data[index + 2] = blue
                        data[index + 3] = 255
                    }
                }
            }

            context!.putImageData(image!, 0, 0)
            return canvas.toDataURL()
        },
        dispose() {
            if (canvas) {
                canvas.width = 0
                canvas.height = 0
            }
            canvas = null
            context = null
            image = null
            domeLut = null
            dome = null
        },
    }
}
