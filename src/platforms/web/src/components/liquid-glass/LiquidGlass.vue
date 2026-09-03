<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, useId, watch } from 'vue'

import {
    buildLiquidGlassCopyGeometry,
    createLensMapGenerator,
    DISPERSION_SPREAD,
    matrixForAxisScale,
    mergeLiquidGlassOptics,
    type LensMapGenerator,
    type LiquidGlassOptics,
} from '@/lib/liquidGlass'

const props = withDefaults(defineProps<{
    as?: string
    radius?: number
    optics?: Partial<LiquidGlassOptics>
    interactive?: boolean
}>(), {
    as: 'div',
    radius: 20,
    optics: () => ({}),
    interactive: false,
})

const root = ref<HTMLElement | null>(null)
const box = reactive({ width: 0, height: 0, left: 0, top: 0 })
const viewport = reactive({ width: 0, height: 0 })
const mapUrl = ref('')
const filterVersion = ref(0)
const uid = useId().replace(/:/g, '')
let resizeObserver: ResizeObserver | null = null
let generator: LensMapGenerator | null = null
let generatorSize = 0
let measureFrame = 0

const optics = computed(() => mergeLiquidGlassOptics(props.optics))
const ready = computed(() => box.width > 1 && box.height > 1)
const filterId = computed(() => `ikaros-liquid-glass-${uid}-${filterVersion.value}`)
const strengthX = computed(() => optics.value.scaleX ?? optics.value.strength)
const strengthY = computed(() => optics.value.scaleY ?? optics.value.strength)
const maximumStrength = computed(() => Math.max(strengthX.value, strengthY.value))
const geometry = computed(() => buildLiquidGlassCopyGeometry({
    width: box.width,
    height: box.height,
    strengthX: strengthX.value,
    strengthY: strengthY.value,
    dispersion: optics.value.dispersion,
    depth: optics.value.depth,
}))
const displacementScale = computed(() => geometry.value.displacementScale)
const mapMatrix = computed(() => {
    if (maximumStrength.value <= 0) return null
    const x = strengthX.value / maximumStrength.value
    const y = strengthY.value / maximumStrength.value
    return x === 1 && y === 1 ? null : matrixForAxisScale(x, y)
})
const mapInput = computed(() => mapMatrix.value ? 'scaledMap' : 'map')
const sourceInput = computed(() => {
    if (optics.value.saturate !== 1) return 'glassSource'
    return optics.value.frost > 0 ? 'frostedSource' : 'SourceGraphic'
})
const hasSpecular = computed(() => optics.value.glow > 0 || optics.value.sheen > 0)
const edgeGain = computed(() => Math.max(0, Math.min(1.5, optics.value.specular)))
const edgeShadow = computed(() => [
    `inset 0 1px 0 rgba(255,255,255,${(0.62 * edgeGain.value).toFixed(3)})`,
    `inset 0 0 0 1px rgba(255,255,255,${(0.18 * edgeGain.value).toFixed(3)})`,
].join(', '))
const rootStyle = computed(() => ({
    borderRadius: `${props.radius}px`,
}))
const refractionStyle = computed(() => ({
    inset: `${-geometry.value.bleed}px`,
    filter: ready.value && mapUrl.value ? `url(#${filterId.value})` : 'none',
}))
const wallpaperStyle = computed(() => ({
    left: `${geometry.value.bleed - box.left}px`,
    top: `${geometry.value.bleed - box.top}px`,
    width: `${viewport.width}px`,
    height: `${viewport.height}px`,
}))
const brightnessStyle = computed(() => ({
    background: optics.value.brightness > 0 ? '#fff' : '#000',
    opacity: Math.min(1, Math.abs(optics.value.brightness)),
}))

const shapeKey = computed(() => JSON.stringify([
    box.width,
    box.height,
    props.radius,
    optics.value.mapSize,
    optics.value.clipToShape,
    optics.value.softEdge,
    optics.value.depth,
    optics.value.curvature,
    optics.value.splay,
    optics.value.bend,
    optics.value.bendWidth,
    optics.value.sheen,
    optics.value.sheenWidth,
    optics.value.sheenFalloff,
    optics.value.sheenAngle,
    optics.value.glow,
    optics.value.glowSpread,
    optics.value.glowFalloff,
]))

const measure = () => {
    if (!root.value) return
    const rectangle = root.value.getBoundingClientRect()
    box.width = Math.max(0, Math.round(rectangle.width))
    box.height = Math.max(0, Math.round(rectangle.height))
    box.left = Math.round(rectangle.left)
    box.top = Math.round(rectangle.top)
    viewport.width = window.innerWidth
    viewport.height = window.innerHeight
}

const scheduleMeasure = () => {
    if (measureFrame) return
    measureFrame = window.requestAnimationFrame(() => {
        measureFrame = 0
        measure()
    })
}

const regenerateMap = () => {
    if (!ready.value) return
    const mapSize = optics.value.mapSize
    if (!generator || generatorSize !== mapSize) {
        generator?.dispose()
        generator = createLensMapGenerator(mapSize)
        generatorSize = mapSize
    }
    mapUrl.value = generator.generate({
        lensHalfWidth: box.width / 2,
        lensHalfHeight: box.height / 2,
        borderRadius: props.radius,
        depth: optics.value.depth,
        clipToShape: optics.value.clipToShape,
        softEdge: optics.value.softEdge,
        sheenAngle: optics.value.sheenAngle,
        glow: optics.value.glow,
        glowSpread: optics.value.glowSpread,
        glowFalloff: optics.value.glowFalloff,
        sheen: optics.value.sheen,
        sheenWidth: optics.value.sheenWidth,
        sheenFalloff: optics.value.sheenFalloff,
        curvature: optics.value.curvature,
        splay: optics.value.splay,
        bend: optics.value.bend,
        bendWidth: optics.value.bendWidth,
    })
    filterVersion.value += 1
}

watch(shapeKey, () => nextTick(regenerateMap))
watch(
    () => [
        optics.value.dispersion,
        optics.value.strength,
        optics.value.scaleX,
        optics.value.scaleY,
        optics.value.specular,
        optics.value.frost,
        optics.value.saturate,
    ],
    () => { if (ready.value) filterVersion.value += 1 },
)

onMounted(() => {
    measure()
    resizeObserver = new ResizeObserver(scheduleMeasure)
    if (root.value) resizeObserver.observe(root.value)
    window.addEventListener('resize', scheduleMeasure)
    window.addEventListener('scroll', scheduleMeasure, true)
    nextTick(regenerateMap)
})

onBeforeUnmount(() => {
    resizeObserver?.disconnect()
    window.removeEventListener('resize', scheduleMeasure)
    window.removeEventListener('scroll', scheduleMeasure, true)
    if (measureFrame) window.cancelAnimationFrame(measureFrame)
    generator?.dispose()
})
</script>

<template>
  <component
    :is="as"
    ref="root"
    class="liquid-glass"
    :class="{ 'liquid-glass--interactive': interactive }"
    :style="rootStyle"
    data-liquid-glass="copy"
  >
    <div
      v-if="ready && mapUrl"
      aria-hidden="true"
      class="liquid-glass__refract"
      :style="refractionStyle"
    >
      <div class="liquid-glass__wallpaper" :style="wallpaperStyle" />
    </div>
    <div aria-hidden="true" class="liquid-glass__veil" />
    <div
      v-if="optics.brightness !== 0"
      aria-hidden="true"
      class="liquid-glass__brightness"
      :style="brightnessStyle"
    />
    <div class="liquid-glass__content">
      <slot />
    </div>
    <div aria-hidden="true" class="liquid-glass__edge" :style="{ boxShadow: edgeShadow }" />

    <svg aria-hidden="true" class="liquid-glass__filter" width="0" height="0">
      <defs>
        <filter
          :id="filterId"
          filterUnits="userSpaceOnUse"
          primitiveUnits="userSpaceOnUse"
          color-interpolation-filters="sRGB"
          :x="geometry.filterX"
          :y="geometry.filterY"
          :width="geometry.filterWidth"
          :height="geometry.filterHeight"
        >
          <template v-if="ready">
            <feFlood flood-color="rgb(128,128,128)" flood-opacity="1" result="mapBackground" />
            <feImage
              :href="mapUrl"
              :x="geometry.mapX"
              :y="geometry.mapY"
              :width="box.width"
              :height="box.height"
              preserveAspectRatio="none"
              result="rawMap"
            />
            <feComposite in="rawMap" in2="mapBackground" operator="over" result="map" />
            <feColorMatrix
              v-if="mapMatrix"
              in="map"
              type="matrix"
              :values="mapMatrix"
              result="scaledMap"
            />

            <feGaussianBlur
              v-if="optics.frost > 0"
              in="SourceGraphic"
              :stdDeviation="optics.frost"
              result="frostedSource"
            />
            <feColorMatrix
              v-if="optics.saturate !== 1"
              :in="optics.frost > 0 ? 'frostedSource' : 'SourceGraphic'"
              type="saturate"
              :values="String(Math.max(0, optics.saturate))"
              result="glassSource"
            />

            <template v-if="optics.dispersion > 0">
              <feDisplacementMap
                :in="sourceInput"
                :in2="mapInput"
                :scale="displacementScale * (1 + DISPERSION_SPREAD * 0.5 * optics.dispersion)"
                xChannelSelector="R"
                yChannelSelector="G"
              />
              <feColorMatrix
                type="matrix"
                values="1 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 1 0"
                result="refractRed"
              />
              <feDisplacementMap
                :in="sourceInput"
                :in2="mapInput"
                :scale="displacementScale"
                xChannelSelector="R"
                yChannelSelector="G"
              />
              <feColorMatrix
                type="matrix"
                values="0 0 0 0 0  0 1 0 0 0  0 0 0 0 0  0 0 0 1 0"
                result="refractGreen"
              />
              <feDisplacementMap
                :in="sourceInput"
                :in2="mapInput"
                :scale="displacementScale * (1 - DISPERSION_SPREAD * 0.5 * optics.dispersion)"
                xChannelSelector="R"
                yChannelSelector="G"
              />
              <feColorMatrix
                type="matrix"
                values="0 0 0 0 0  0 0 0 0 0  0 0 1 0 0  0 0 0 1 0"
                result="refractBlue"
              />
              <feComposite
                in="refractRed"
                in2="refractGreen"
                operator="arithmetic"
                k1="0"
                k2="1"
                k3="1"
                k4="0"
                result="refractRedGreen"
              />
              <feComposite
                in="refractRedGreen"
                in2="refractBlue"
                operator="arithmetic"
                k1="0"
                k2="1"
                k3="1"
                k4="0"
                result="lensOutput"
              />
            </template>
            <feDisplacementMap
              v-else
              :in="sourceInput"
              :in2="mapInput"
              :scale="displacementScale"
              xChannelSelector="R"
              yChannelSelector="G"
              result="lensOutput"
            />

            <template v-if="hasSpecular">
              <feColorMatrix
                in="map"
                type="matrix"
                values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 1 0 -0.5019607843"
                result="sheenMask"
              />
              <feComposite
                in="sheenMask"
                in2="lensOutput"
                operator="arithmetic"
                k1="0"
                :k2="optics.specular"
                k3="1"
                k4="0"
              />
            </template>
          </template>
        </filter>
      </defs>
    </svg>
  </component>
</template>

<style scoped>
.liquid-glass {
  position: relative;
  display: block;
  overflow: hidden;
  border: 0.5px solid var(--ikaros-glass-hairline, rgba(23, 19, 26, 0.13));
  background: var(--ikaros-glass-behind, #f1eef2);
  box-shadow:
    0 18px 52px rgba(23, 19, 26, 0.11),
    inset 0 0 28px rgba(255, 255, 255, 0.3);
  color: var(--ikaros-ink, #17131a);
  transition:
    box-shadow 420ms cubic-bezier(0.16, 1, 0.3, 1),
    border-color 220ms ease;
}

.liquid-glass--interactive:hover {
  border-color: rgba(232, 93, 142, 0.32);
  box-shadow:
    0 22px 58px rgba(23, 19, 26, 0.13),
    inset 0 0 26px rgba(255, 255, 255, 0.36);
}

.liquid-glass__refract {
  position: absolute;
  z-index: 0;
  overflow: hidden;
  contain: paint;
  background: var(--ikaros-glass-behind, #f1eef2);
  pointer-events: none;
  will-change: filter;
}

.liquid-glass__wallpaper {
  position: absolute;
  background-color: var(--ikaros-glass-behind, #f1eef2);
  background-image: var(
    --ikaros-glass-wallpaper-image,
    radial-gradient(circle at 12% 18%, rgba(255, 255, 255, 0.96), transparent 38%),
    radial-gradient(circle at 76% 82%, rgba(232, 93, 142, 0.14), transparent 46%),
    linear-gradient(135deg, #fff9fc 0%, #eceef2 48%, #f9edf3 100%)
  );
  background-position: var(--ikaros-glass-wallpaper-position, center);
  background-repeat: var(--ikaros-glass-wallpaper-repeat, no-repeat);
  background-size: var(--ikaros-glass-wallpaper-size, cover);
}

.liquid-glass__veil,
.liquid-glass__brightness,
.liquid-glass__edge {
  position: absolute;
  z-index: 1;
  inset: 0;
  border-radius: inherit;
  pointer-events: none;
}

.liquid-glass__veil {
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.18), rgba(255, 255, 255, 0.045)),
    color-mix(
      in srgb,
      var(--ikaros-glass-fill, rgba(255, 249, 252, 0.8)) 64%,
      transparent
    );
}

.liquid-glass__content {
  position: relative;
  z-index: 2;
  min-height: inherit;
}

.liquid-glass__edge {
  z-index: 3;
}

.liquid-glass__edge::before {
  position: absolute;
  inset: 1px;
  border-radius: inherit;
  background: linear-gradient(
    112deg,
    transparent 18%,
    rgba(255, 255, 255, 0.18) 39%,
    rgba(255, 255, 255, 0.42) 48%,
    transparent 61%
  );
  content: '';
  opacity: 0.62;
}

.liquid-glass__filter {
  position: absolute;
  width: 0;
  height: 0;
}

@media (prefers-reduced-motion: reduce) {
  .liquid-glass {
    transition: border-color 120ms ease;
  }
}
</style>
