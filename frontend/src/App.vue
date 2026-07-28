<script setup lang="ts">
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useAuth } from './stores/auth'
import AppNav from './components/AppNav.vue'

const route = useRoute()
const { fetchMe } = useAuth()

onMounted(fetchMe)
</script>

<template>
  <div v-if="route.name === 'login'">
    <router-view />
  </div>
  <div v-else class="layout">
    <AppNav />
    <main class="content">
      <router-view />
    </main>
  </div>
</template>
