<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { api } from '../api/client'

interface AppNotification {
  id: number
  message: string
  is_read: boolean
  created_at: string
}

const notifications = ref<AppNotification[]>([])
const open = ref(false)
const root = ref<HTMLElement | null>(null)

const unreadCount = computed(() => notifications.value.filter((n) => !n.is_read).length)

async function load() {
  notifications.value = await api.get<AppNotification[]>('/notifications')
}

async function markRead(n: AppNotification) {
  if (n.is_read) return
  n.is_read = true
  try {
    await api.patch(`/notifications/${n.id}/read`)
  } catch {
    n.is_read = false
  }
}

function toggle() {
  open.value = !open.value
}

function onDocClick(e: MouseEvent) {
  if (open.value && root.value && !root.value.contains(e.target as Node)) {
    open.value = false
  }
}

onMounted(() => {
  load()
  document.addEventListener('click', onDocClick)
})
onUnmounted(() => document.removeEventListener('click', onDocClick))
</script>

<template>
  <div class="notif-bell" ref="root">
    <button type="button" class="notif-bell-btn" @click="toggle" aria-label="Upozornění">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
        <path d="M6 9a6 6 0 1 1 12 0c0 4 1.5 5.5 2 6.5H4c.5-1 2-2.5 2-6.5Z" />
        <path d="M10 19a2 2 0 0 0 4 0" />
      </svg>
      <span v-if="unreadCount" class="notif-badge">{{ unreadCount }}</span>
    </button>

    <div v-if="open" class="notif-panel">
      <div class="notif-panel-header">Upozornění</div>
      <p v-if="!notifications.length" class="notif-empty">Zatím nic.</p>
      <ul v-else class="notif-list">
        <li v-for="n in notifications" :key="n.id" :class="{ unread: !n.is_read }" @click="markRead(n)">
          <p>{{ n.message }}</p>
          <span class="notif-time">{{ new Date(n.created_at).toLocaleString('cs-CZ') }}</span>
        </li>
      </ul>
    </div>
  </div>
</template>
