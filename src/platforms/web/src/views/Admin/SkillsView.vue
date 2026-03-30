<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Loader2 } from 'lucide-vue-next'

import { getSkills, setSkillEnabled, type SkillInfo } from '@/api/skills'

const skills = ref<SkillInfo[]>([])
const loading = ref(false)
const toggling = ref<string | null>(null)

const builtinSkills = computed(() =>
    skills.value.filter(s => s.source === 'builtin').sort((a, b) => a.name.localeCompare(b.name))
)

const learnedSkills = computed(() =>
    skills.value.filter(s => s.source === 'learned').sort((a, b) => a.name.localeCompare(b.name))
)

const load = async () => {
    loading.value = true
    try {
        const response = await getSkills()
        skills.value = response.data.skills || []
    } finally {
        loading.value = false
    }
}

const toggleSkill = async (skill: SkillInfo) => {
    toggling.value = skill.name
    try {
        const response = await setSkillEnabled(skill.name, !skill.enabled)
        skill.enabled = response.data.enabled
    } finally {
        toggling.value = null
    }
}

onMounted(load)
</script>

<template>
  <div class="space-y-6 p-6 md:p-8">
    <section class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
      <div class="text-xs uppercase tracking-[0.24em] text-slate-400">Skills</div>
      <h2 class="mt-1 text-2xl font-semibold text-slate-900">技能管理</h2>
      <p class="mt-2 text-sm leading-7 text-slate-500">
        管理系统中的技能模块，启用或禁用特定技能。
      </p>
    </section>

    <div v-if="loading" class="flex items-center gap-2 rounded-[28px] border border-slate-200 bg-white px-5 py-4 text-sm text-slate-500 shadow-sm">
      <Loader2 class="h-4 w-4 animate-spin" />
      正在加载技能列表
    </div>

    <template v-else>
      <section class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
        <div class="text-sm font-semibold text-slate-900">内置技能 ({{ builtinSkills.length }})</div>
        <div class="mt-4 space-y-3">
          <label
            v-for="skill in builtinSkills"
            :key="skill.name"
            class="flex items-start justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
          >
            <div class="flex-1 min-w-0 pr-4">
              <div class="text-sm font-medium text-slate-700">{{ skill.name }}</div>
              <div class="mt-1 text-xs text-slate-500 line-clamp-2">{{ skill.description || '暂无描述' }}</div>
              <div v-if="skill.triggers.length" class="mt-2 flex flex-wrap gap-1.5">
                <span
                  v-for="trigger in skill.triggers.slice(0, 8)"
                  :key="trigger"
                  class="inline-flex items-center rounded-full bg-slate-200/80 px-2 py-1 text-[11px] font-medium text-slate-600"
                >
                  {{ trigger }}
                </span>
                <span v-if="skill.triggers.length > 8" class="text-[11px] text-slate-400 py-1">
                  +{{ skill.triggers.length - 8 }} 更多
                </span>
              </div>
            </div>
            <input
              :checked="skill.enabled"
              :disabled="toggling === skill.name"
              type="checkbox"
              class="h-4 w-4 cursor-pointer mt-1 flex-shrink-0"
              @change="toggleSkill(skill)"
            >
          </label>
          <div v-if="!builtinSkills.length" class="text-sm text-slate-500 py-4 text-center">
            暂无内置技能
          </div>
        </div>
      </section>

      <section class="rounded-[28px] border border-slate-200 bg-white p-6 shadow-sm">
        <div class="text-sm font-semibold text-slate-900">已学习技能 ({{ learnedSkills.length }})</div>
        <div class="mt-4 space-y-3">
          <label
            v-for="skill in learnedSkills"
            :key="skill.name"
            class="flex items-start justify-between rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3"
          >
            <div class="flex-1 min-w-0 pr-4">
              <div class="text-sm font-medium text-slate-700">{{ skill.name }}</div>
              <div class="mt-1 text-xs text-slate-500 line-clamp-2">{{ skill.description || '暂无描述' }}</div>
              <div v-if="skill.triggers.length" class="mt-2 flex flex-wrap gap-1.5">
                <span
                  v-for="trigger in skill.triggers.slice(0, 8)"
                  :key="trigger"
                  class="inline-flex items-center rounded-full bg-slate-200/80 px-2 py-1 text-[11px] font-medium text-slate-600"
                >
                  {{ trigger }}
                </span>
                <span v-if="skill.triggers.length > 8" class="text-[11px] text-slate-400 py-1">
                  +{{ skill.triggers.length - 8 }} 更多
                </span>
              </div>
            </div>
            <input
              :checked="skill.enabled"
              :disabled="toggling === skill.name"
              type="checkbox"
              class="h-4 w-4 cursor-pointer mt-1 flex-shrink-0"
              @change="toggleSkill(skill)"
            >
          </label>
          <div v-if="!learnedSkills.length" class="text-sm text-slate-500 py-4 text-center">
            暂无已学习技能
          </div>
        </div>
      </section>
    </template>
  </div>
</template>