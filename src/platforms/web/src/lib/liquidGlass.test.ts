import { describe, expect, it } from 'vitest'

import {
    buildLiquidGlassCopyGeometry,
    matrixForAxisScale,
    mergeLiquidGlassOptics,
} from './liquidGlass'

describe('liquid glass copy-refraction helpers', () => {
    it('merges optics without mutating defaults', () => {
        const optics = mergeLiquidGlassOptics({ frost: 24, strength: 0.08 })

        expect(optics.frost).toBe(24)
        expect(optics.strength).toBe(0.08)
        expect(optics.dispersion).toBeGreaterThan(0)
    })

    it('pins the filter region at the source-copy origin', () => {
        const geometry = buildLiquidGlassCopyGeometry({
            width: 320,
            height: 180,
            strengthX: 0.11,
            strengthY: 0.08,
            dispersion: 0.58,
            depth: 0.9,
        })

        expect(geometry.filterX).toBe(0)
        expect(geometry.filterY).toBe(0)
        expect(geometry.filterWidth).toBe(geometry.copyWidth)
        expect(geometry.filterHeight).toBe(geometry.copyHeight)
    })

    it('places the lens map exactly one bleed inside the source copy', () => {
        const geometry = buildLiquidGlassCopyGeometry({
            width: 240,
            height: 96,
            strengthX: 0.08,
            strengthY: 0.08,
            dispersion: 0.4,
            depth: 0.7,
        })

        expect(geometry.bleed).toBeGreaterThan(0)
        expect(geometry.mapX).toBe(geometry.bleed)
        expect(geometry.mapY).toBe(geometry.bleed)
        expect(geometry.copyWidth).toBe(240 + geometry.bleed * 2)
        expect(geometry.copyHeight).toBe(96 + geometry.bleed * 2)
    })

    it('scales displacement channels around the neutral midpoint', () => {
        expect(matrixForAxisScale(0.5, 1)).toContain('0.25')
    })
})
