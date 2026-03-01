<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { getRecords, importCsv, type Record } from '@/api/accounting'
import { useRouter } from 'vue-router'

const authStore = useAuthStore()
const router = useRouter()

const records = ref<Record[]>([])
const loading = ref(false)
const uploading = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const errorMessage = ref('')
const selectedBookId = ref<number>(1) // Hardcoded to 1 for MVP

const fetchRecords = async () => {
    loading.value = true
    errorMessage.value = ''
    try {
        const res = await getRecords(selectedBookId.value)
        records.value = res.data
    } catch (e: any) {
        errorMessage.value = e.response?.data?.detail || 'Failed to load records'
    } finally {
        loading.value = false
    }
}

const triggerUpload = () => {
    fileInput.value?.click()
}

const handleFileUpload = async (event: Event) => {
    const target = event.target as HTMLInputElement
    if (target.files && target.files.length > 0) {
        const file = target.files[0]
        if (!file) return
        uploading.value = true
        errorMessage.value = ''
        try {
            await importCsv(selectedBookId.value, file)
            alert('Import successful!')
            await fetchRecords()
        } catch (e: any) {
             errorMessage.value = e.response?.data?.detail || 'Import failed'
        } finally {
            uploading.value = false
            target.value = '' // Reset input
        }
    }
}

const handleLogout = async () => {
    await authStore.logout()
    router.push('/login')
}

onMounted(() => {
    fetchRecords()
})
</script>

<template>
  <div class="min-h-screen bg-gray-50 flex flex-col">
    <!-- Fast App Header -->
    <header class="bg-indigo-600 text-white p-4 shadow-md flex justify-between items-center sticky top-0 z-10">
      <h1 class="text-xl font-bold tracking-tight">X-Bot Accounting</h1>
      <button @click="handleLogout" class="text-sm px-3 py-1 bg-indigo-700 hover:bg-indigo-800 rounded">
        Logout
      </button>
    </header>

    <main class="flex-1 p-4 max-w-2xl mx-auto w-full">
      <!-- Error Banner -->
      <div v-if="errorMessage" class="bg-red-100 text-red-800 p-3 rounded mb-4 text-sm border border-red-200">
        {{ errorMessage }}
      </div>
      
      <!-- Actions -->
      <div class="mb-6 flex gap-2">
        <button 
          @click="triggerUpload" 
          :disabled="uploading"
          class="flex-1 bg-white border-2 border-dashed border-indigo-300 text-indigo-700 py-3 rounded-xl font-medium hover:bg-indigo-50 transition drop-shadow-sm disabled:opacity-50 flex items-center justify-center gap-2">
           <svg v-if="uploading" class="animate-spin h-5 w-5 text-indigo-700" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
             <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
             <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
           </svg>
           <span v-else>Import CSV</span>
        </button>
        <input 
          type="file" 
          ref="fileInput" 
          accept=".csv" 
          class="hidden" 
          @change="handleFileUpload"
        />
      </div>

      <!-- Record List -->
      <div class="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
        <div class="p-4 border-b border-gray-100 flex justify-between items-center bg-gray-50/50">
          <h2 class="font-semibold text-gray-800">Recent Records</h2>
          <button @click="fetchRecords" class="text-xs text-indigo-600 font-medium">Refresh</button>
        </div>
        
        <div v-if="loading" class="p-8 text-center text-gray-400">
          Loading records...
        </div>
        
        <div v-else-if="records.length === 0" class="p-8 text-center text-gray-400">
          No records found.
        </div>
        
        <ul v-else class="divide-y divide-gray-50">
          <li v-for="record in records" :key="record.id" class="p-4 hover:bg-gray-50 transition cursor-pointer">
            <div class="flex justify-between items-start mb-1">
              <span class="font-medium text-gray-800">{{ record.remark || record.payee || 'Untagged' }}</span>
              <span :class="record.type === '收入' ? 'text-green-600' : 'text-gray-900'" class="font-semibold tracking-tight">
                {{ record.type === '收入' ? '+' : '-' }}{{ record.amount }}
              </span>
            </div>
            <div class="flex justify-between items-center text-xs text-gray-500">
              <span class="bg-gray-100 px-2 py-0.5 rounded text-gray-600">{{ record.type }}</span>
              <span>{{ new Date(record.record_time).toLocaleString() }}</span>
            </div>
          </li>
        </ul>
      </div>
    </main>
  </div>
</template>
