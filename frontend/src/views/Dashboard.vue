<script setup>
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { act, ago, api } from '../api'
import SessionList from '../components/SessionList.vue'

const data = ref(null)
const error = ref('')
let timer

async function load() {
  clearTimeout(timer)
  try {
    data.value = await api.get('/overview')
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
  timer = setTimeout(load, 5000)
}

const wolf = computed(() => data.value?.wolf)

async function restart() {
  const n = data.value?.sessions.length
  if (n && !confirm(`${n} session(s) en cours seront coupées. Redémarrer Wolf ?`)) return
  await act('Redémarrage de Wolf', () => api.post('/wolf', { action: 'restart' }), 'Wolf redémarré')
  load()
}

onMounted(load)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <div class="page-head">
    <h1>Tableau de bord</h1>
    <span v-if="data" class="muted">{{ data.hostname }}</span>
    <div class="spacer"></div>
    <button @click="restart">🔄 Redémarrer Wolf</button>
  </div>

  <div v-if="error" class="alert bad">{{ error }}</div>

  <template v-if="data">
    <div v-if="data.pending.length" class="alert info" style="margin-bottom:16px">
      🔑 <b>{{ data.pending.length }} appareil(s)</b> attendent l'appairage.
      <router-link to="/appairage">Saisir le code PIN →</router-link>
    </div>
    <div v-if="!wolf.api" class="alert warn" style="margin-bottom:16px">
      L'API de Wolf n'est pas joignable : appairage et sessions indisponibles.
      Vérifie que Wolf tourne et que le volume <code>wolf-api</code> est monté (voir README).
    </div>
    <div v-if="data.api_error" class="alert bad" style="margin-bottom:16px">{{ data.api_error }}</div>

    <div class="grid cols-4">
      <div class="card stat">
        <div class="label">Wolf</div>
        <div class="value row">
          <span class="dot" :class="wolf.running ? 'ok' : 'bad'"></span>
          {{ wolf.running ? 'En ligne' : wolf.status }}
        </div>
        <div class="hint">démarré {{ ago(wolf.started_at) }} · {{ wolf.image.split('/').pop() }}</div>
      </div>
      <div class="card stat">
        <div class="label">Sessions actives</div>
        <div class="value">{{ data.sessions.length }}</div>
        <div class="hint"><router-link to="/sessions">Gérer les sessions</router-link></div>
      </div>
      <div class="card stat">
        <div class="label">Appareils appairés</div>
        <div class="value">{{ data.clients }}</div>
        <div class="hint"><router-link to="/appairage">Appairage</router-link></div>
      </div>
      <div class="card stat">
        <div class="label">Applications Moonlight</div>
        <div class="value">{{ data.apps }}</div>
        <div class="hint">GPU : pilote NVIDIA {{ data.gpu_driver || '?' }}</div>
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <h2>Sessions en cours</h2>
      <SessionList :sessions="data.sessions" @changed="load" />
    </div>
  </template>
  <div v-else-if="!error" class="empty"><div class="spinner" style="margin:auto"></div></div>
</template>
