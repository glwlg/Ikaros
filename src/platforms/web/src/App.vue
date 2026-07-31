<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import MainLayout from '@/layouts/MainLayout.vue'

const route = useRoute()
const isPublicLayout = computed(() => route.meta.public === true)
const isFullscreen = computed(() =>
    route.matched.some(r => r.meta.fullscreen === true)
)
</script>

<template>
  <!-- Public pages (login etc) -->
  <div v-if="isPublicLayout" class="w-full min-h-screen">
    <RouterView />
  </div>
  <!-- Fullscreen modules (accounting etc) -->
  <div v-else-if="isFullscreen" class="accounting-fullscreen w-full">
    <RouterView />
  </div>
  <!-- Normal pages with sidebar -->
  <template v-else>
    <MainLayout />
  </template>
</template>

<style>
html, body {
  margin: 0;
  padding: 0;
  width: 100%;
}

*, *::before, *::after {
  box-sizing: border-box;
}

:root {
  --font-display: Inter, "SF Pro Display", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
  --font-body: Inter, "SF Pro Text", "PingFang SC", "Microsoft YaHei", Arial, sans-serif;
  --panel-border: #e5ebf3;
  --panel-muted: #f6f9fd;
  --panel-soft: #fbfdff;
  --text-strong: #101828;
  --text-body: #344054;
  --text-muted: #667085;
  --text-subtle: #98a2b3;
  --brand-blue: #2f7cf6;
  --brand-blue-dark: #1469f2;
  --brand-blue-soft: #e8f1ff;
  --success: #22c55e;
  --warning: #f59e0b;
  --danger: #ef4444;
  --shadow-card: 0 18px 44px rgba(16, 24, 40, 0.04);
}

:root.dark {
  --panel-border: var(--color-border-primary);
  --panel-muted: var(--color-bg-tertiary);
  --panel-soft: var(--color-bg-secondary);
  --text-strong: var(--color-text-primary);
  --text-body: var(--color-text-secondary);
  --text-muted: var(--color-text-tertiary);
  --text-subtle: var(--color-text-muted);
  --brand-blue: var(--color-primary-500);
  --brand-blue-dark: var(--color-primary-600);
  --brand-blue-soft: var(--color-primary-50);
  --shadow-card: 0 18px 44px rgba(0, 0, 0, 0.28);
}

/* Legacy console pages use Tailwind's light utilities alongside theme tokens. */
:root.dark :is(.bg-white, .bg-white\/70, .bg-white\/80, .bg-white\/90) {
  background-color: var(--color-bg-elevated) !important;
}

:root.dark :is(.bg-slate-50, .bg-slate-50\/80, .bg-slate-100, .bg-gray-50, .bg-gray-100) {
  background-color: var(--color-bg-tertiary) !important;
}

:root.dark :is(.bg-slate-200, .bg-gray-200) {
  background-color: var(--color-border-primary) !important;
}

:root.dark :is(.border-slate-100, .border-slate-200, .border-slate-300, .border-gray-100, .border-gray-200, .border-gray-300) {
  border-color: var(--color-border-primary) !important;
}

:root.dark :is(.text-slate-950, .text-slate-900, .text-slate-800, .text-gray-950, .text-gray-900, .text-gray-800) {
  color: var(--color-text-primary) !important;
}

:root.dark :is(.text-slate-700, .text-slate-600, .text-slate-500, .text-slate-400, .text-gray-700, .text-gray-600, .text-gray-500, .text-gray-400) {
  color: var(--color-text-secondary) !important;
}

:root.dark :is(
  .models-page .model-overview-card,
  .models-page .model-stat-card,
  .models-page .models-hero,
  .models-page .models-surface,
  .models-page .loading-card,
  .models-page .route-table-card,
  .models-page .provider-quick-panel,
  .models-page .provider-list-panel,
  .models-page .provider-detail-panel,
  .models-page .role-card,
  .models-page .matrix-panel,
  .models-page .provider-card,
  .models-page .action-menu,
  .models-page .secondary-btn,
  .models-page .danger-btn,
  .models-page .table-action,
  .models-page .table-menu,
  .models-page .provider-head button,
  .models-page .provider-list-head button,
  .models-page .toggle-chip-row button,
  .models-page .pool-chip-list button,
  .runtime-page .runtime-hero,
  .runtime-page .runtime-card,
  .runtime-page .loading-card,
  .runtime-page .secondary-btn,
  .runtime-page .doc-head button,
  .runtime-page .side-card-head button,
  .skills-page .skills-hero,
  .skills-page .filter-panel,
  .skills-page .skills-table-panel,
  .skills-page .secondary-action,
  .skills-page .filter-select,
  .skills-page .skills-search,
  .skills-page .refresh-btn,
  .skills-page .row-menu
) {
  background-color: var(--color-bg-elevated) !important;
}

:root.dark :is(
  .models-page .route-table-wrap th,
  .models-page .model-table-wrap th,
  .models-page .matrix-table-wrap th,
  .models-page .action-menu button:hover,
  .models-page .capability-list span,
  .models-page .model-edit-row td,
  .models-page .compat,
  .runtime-page .channel-item,
  .runtime-page .toggle-row,
  .runtime-page .sequence-card li span,
  .skills-page .tag-list span
) {
  background-color: var(--color-bg-tertiary) !important;
}

:root.dark :is(
  .models-page .route-table-wrap td,
  .models-page .model-table-wrap td,
  .models-page .matrix-table-wrap td,
  .models-page .provider-item,
  .skills-page td
) {
  border-color: var(--color-border-secondary) !important;
}

body {
  background: var(--color-bg-primary);
  color: var(--color-text-primary);
  font-family: var(--font-body);
  letter-spacing: 0;
}

button,
input,
textarea,
select {
  font: inherit;
  letter-spacing: 0;
}

button {
  cursor: pointer;
}

button:disabled {
  cursor: not-allowed;
}

.font-display,
.font-body {
  font-family: var(--font-display);
}

.rounded-\[30px\],
.rounded-\[28px\],
.rounded-\[24px\] {
  border-radius: 14px !important;
}

.rounded-2xl {
  border-radius: 10px !important;
}

.rounded-xl {
  border-radius: 8px !important;
}

.shadow-sm,
.shadow-lg,
[class*='shadow-'] {
  box-shadow: var(--shadow-card) !important;
}

input:not([type='checkbox']):not([type='radio']):not([type='file']),
textarea,
select {
  border-color: var(--color-border-primary);
  background: var(--color-bg-elevated);
  color: var(--color-text-primary);
  -webkit-text-fill-color: var(--color-text-primary);
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.02);
}

input::placeholder,
textarea::placeholder {
  color: var(--color-text-muted);
  -webkit-text-fill-color: var(--color-text-muted);
}

input:focus,
textarea:focus,
select:focus {
  border-color: var(--color-border-focus);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--color-border-focus) 18%, transparent);
}

table {
  border-collapse: separate;
  border-spacing: 0;
}

thead {
  background: var(--panel-muted);
}

tbody {
  background: var(--color-bg-elevated);
}

.bg-slate-950 {
  background: #101828 !important;
}

.bg-blue-500,
.bg-orange-500,
.bg-purple-500,
.bg-red-500 {
  background: var(--brand-blue) !important;
  color: #ffffff !important;
}

.hover\:bg-blue-600:hover,
.hover\:bg-orange-600:hover,
.hover\:bg-purple-600:hover,
.hover\:bg-red-600:hover {
  background: var(--brand-blue-dark) !important;
}

.bg-slate-950 .text-slate-500,
.bg-slate-950 .text-slate-400 {
  color: #cbd5e1 !important;
}

.text-cyan-600,
.text-blue-600,
.text-purple-600 {
  color: var(--brand-blue) !important;
}

.bg-cyan-50,
.bg-blue-50,
.bg-indigo-100,
.bg-violet-100,
.bg-purple-50 {
  background: var(--brand-blue-soft) !important;
}

.border-cyan-200,
.border-cyan-300,
.border-blue-200 {
  border-color: #9ec5ff !important;
}

.text-emerald-700,
.text-green-600 {
  color: #16a34a !important;
}

.bg-emerald-50,
.bg-green-50 {
  background: #ecfdf3 !important;
}

.border-emerald-200 {
  border-color: #b7efc6 !important;
}

@media (max-width: 768px) {
  .p-6,
  .md\:p-8 {
    padding: 16px !important;
  }
}
</style>
