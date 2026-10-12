<script setup>
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { act, ago, api } from '../api'
import SessionList from '../components/SessionList.vue'

const data = ref(null)
const clients = ref([])
const error = ref('')
let timer

async function load() {
  clearTimeout(timer)
  try {
    data.value = await api.get('/overview')
    if (data.value.wolf.api) clients.value = (await api.get('/pairing')).clients
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
    <div>
      <h1>Tableau de bord</h1>
      <div v-if="data" class="sub">{{ data.hostname }} · <span class="mono">{{ wolf.image }}</span></div>
    </div>
    <div class="spacer"></div>
    <button @click="restart"><Icon name="refresh" />Redémarrer Wolf</button>
  </div>

  <div v-if="error" class="alert bad" style="margin-bottom:16px"><Icon name="alert" /><div>{{ error }}</div></div>

  <div v-if="data" class="stack">
    <div v-if="data.pending.length" class="alert">
      <Icon name="key" />
      <div><b>{{ data.pending.length }} appareil(s)</b> attendent l'appairage.
        <router-link to="/appairage">Saisir le code PIN</router-link></div>
    </div>
    <div v-if="!wolf.api" class="alert warn">
      <Icon name="alert" />
      <div>L'API de Wolf n'est pas joignable : appairage et sessions indisponibles.
        Vérifie que Wolf tourne et que le volume <code>wolf-api</code> est monté (voir README).</div>
    </div>
    <div v-if="data.api_error" class="alert bad"><Icon name="alert" /><div>{{ data.api_error }}</div></div>

    <div class="grid cols-4 stats">
      <div class="card stat">
        <span class="overline">Serveur Wolf</span>
        <span class="value text">
          <span class="dot" :class="wolf.running ? 'ok' : 'bad'"></span>
          {{ wolf.running ? 'En ligne' : wolf.status }}
        </span>
        <span class="hint">démarré {{ ago(wolf.started_at) }} · API {{ wolf.api ? 'OK' : 'absente' }}</span>
      </div>
      <div class="card stat">
        <span class="overline">Sessions actives</span>
        <span class="value">{{ data.sessions.length }}</span>
        <span class="hint"><router-link to="/sessions">Gérer les sessions</router-link></span>
      </div>
      <div class="card stat">
        <span class="overline">Appareils appairés</span>
        <span class="value">{{ data.clients }}</span>
        <span class="hint"><router-link to="/appairage">Appairer un appareil</router-link></span>
      </div>
      <div class="card stat">
        <span class="overline">Applications</span>
        <span class="value">{{ data.apps }}</span>
        <span class="hint">GPU NVIDIA · pilote {{ data.gpu_driver || '?' }}</span>
      </div>
    </div>

    <div class="dash-split">
      <section class="card">
        <div class="card-head">
          <div><h2>Sessions en cours</h2><p class="desc">Actualisé toutes les 5 s</p></div>
        </div>
        <SessionList :sessions="data.sessions" @changed="load" />
      </section>
      <section class="card">
        <div class="card-head">
          <div>
            <h2>Appareils</h2>
            <p class="desc">{{ data.clients }} appairé(s) · {{ data.pending.length ? `${data.pending.length} demande(s)` : 'aucune demande' }}</p>
          </div>
          <router-link to="/appairage">Tout voir</router-link>
        </div>
        <div v-for="c in clients.slice(0, 4)" :key="c.client_id" class="device">
          <div class="empty-icon"><Icon name="phone" /></div>
          <div style="flex:1;min-width:0">
            <div style="font-weight:600">{{ c.name || 'Sans nom' }}</div>
            <div class="muted small">
              <template v-if="c.paired_at">appairé le {{ c.paired_at }} · </template>manette {{ c.settings?.controllers_override?.[0] || 'Auto' }}
            </div>
          </div>
          <span v-if="data.sessions.some(s => String(s.client_id) === String(c.client_id))" class="badge ok">Actif</span>
        </div>
        <div v-if="!clients.length" class="muted">Aucun appareil appairé.</div>
        <div class="divider"></div>
        <div class="alert">
          <Icon name="info" />
          <div>Si une session plante, <strong>quitte-la dans Moonlight</strong> avant de la relancer.</div>
        </div>
      </section>
    </div>
  </div>
  <div v-else-if="!error" class="empty"><div class="spinner"></div></div>
</template>

<style scoped>
.dash-split { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr); gap: var(--space-4); align-items: start; }
@media (max-width: 1100px) { .dash-split { grid-template-columns: 1fr; } }
.device { display: flex; gap: 12px; align-items: center; padding: 6px 0; }
.empty-icon {
  width: 44px; height: 44px; flex: none; border-radius: var(--radius-md); background: var(--surface-raised);
  border: 1px solid var(--border); display: grid; place-items: center; color: var(--ink-muted);
}
.stack > .grid { margin-top: var(--space-6); }
</style>
