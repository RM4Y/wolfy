<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import SessionList from '../components/SessionList.vue'

const sessions = ref([])
const error = ref('')
const raw = ref(false)
let timer

async function load() {
  clearTimeout(timer)
  try {
    sessions.value = (await api.get('/sessions')).sessions
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
  timer = setTimeout(load, 4000)
}

onMounted(load)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <div class="page-head">
    <h1>Sessions</h1>
    <span class="muted small">actualisé toutes les 4 s</span>
    <div class="spacer"></div>
    <label class="check"><input v-model="raw" type="checkbox" /> Détails bruts</label>
  </div>
  <div v-if="error" class="alert bad">{{ error }}</div>
  <div class="card">
    <SessionList :sessions="sessions" @changed="load" />
  </div>
  <div v-if="raw && sessions.length" class="card">
    <pre class="logbox">{{ JSON.stringify(sessions, null, 2) }}</pre>
  </div>
  <div class="alert info" style="margin-top:16px">
    Astuce : si une session plante, quitte-la dans Moonlight (« Quitter la session ») avant de la relancer —
    reprendre une session dont le conteneur est mort fait planter Wolf.
  </div>
</template>
