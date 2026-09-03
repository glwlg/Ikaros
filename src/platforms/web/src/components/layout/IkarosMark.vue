<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 34 })
</script>

<template>
  <span class="ikaros-mark" :style="{ width: `${size}px`, height: `${size}px` }" aria-hidden="true">
    <svg viewBox="0 0 36 36" role="img">
      <path
        d="M8 22.5c4.8-1.4 8.4-5.2 10.7-11.4 1.7 4.5 4.8 7.8 9.3 9.8-3.7.4-6.7-.3-9-2.1-2.1 3-5.8 4.8-11 5.4z"
        fill="currentColor"
      />
      <path
        d="M10.2 25.8c4.2-.6 7.4-2 9.5-4.3 1.8 1.5 4.2 2.4 7.1 2.7-3.2 1.9-6.1 2.7-8.8 2.3-2.3.8-4.9.6-7.8-.7z"
        fill="currentColor"
        opacity=".58"
      />
      <ellipse cx="13" cy="18" rx="1.15" ry="1.75" fill="#17131a" transform="rotate(-28 13 18)" />
      <circle cx="26.7" cy="13.2" r="1.35" fill="#2f7d4a" />
    </svg>
  </span>
</template>

<style scoped>
.ikaros-mark {
  display: grid;
  flex: none;
  place-items: center;
  border: 1px solid rgba(255, 255, 255, 0.52);
  border-radius: 11px;
  background: rgba(255, 249, 252, 0.95);
  color: #e85d8e;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.95),
    0 8px 24px rgba(0, 0, 0, 0.16);
}

.ikaros-mark svg {
  width: 76%;
  height: 76%;
}
</style>
