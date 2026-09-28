<script setup>
import { computed, onMounted, ref } from 'vue'
import { act, ago, api, bytes } from '../api'
import JobLog from '../components/JobLog.vue'

const emit = defineEmits(['refresh'])
const wolf = ref(null)
const m = ref(null)
const logs = ref('')
const tail = ref(300)
const filter = ref('')
const jobId = ref('')
const jobs = ref([])
const error = ref('')

async function load() {
  try {
    const [o, maint, j] = await Promise.all([api.get('/overview'), api.get('/maintenance'), api.get('/jobs')])
    wolf.value = { ...o.wolf, sessions: o.sessions.length }
    m.value = maint
    jobs.value = j.jobs
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

async function loadLogs() {
  const r = await act('Lecture des journaux', () => api.get(`/wolf/logs?tail=${tail.value}`))
  if (r) logs.value = r.logs.replace(/\x1b\[[0-9;]*m/g, '')
}

const shownLogs = computed(() => {
  if (!filter.value) return logs.value
  const f = filter.value.toLowerCase()
  return logs.value.split('\n').filter(l => l.toLowerCase().includes(f)).join('\n')
})

async function wolfAction(action, label) {
  const n = wolf.value?.sessions
  if (action !== 'start' && n && !confirm(`${n} session(s) en cours seront coupées. Continuer ?`)) return
  if (action === 'stop' && !confirm('Arrêter Wolf ? Plus aucun appareil ne pourra streamer.')) return
  await act(label, () => api.post('/wolf', { action }), 'Terminé')
  load()
  emit('refresh')
}

async function containerAction(c, action) {
  await act('Conteneur', () => api.post(`/containers/${c.name}`, { action }), 'OK')
  load()
}

async function prune() {
  const r = await act('Nettoyage', () => api.post('/containers/prune'))
  if (r) { load() }
}

async function clearBacktraces() {
  if (!confirm('Supprimer tous les rapports de plantage ?')) return
  await act('Suppression', () => api.del('/backtraces'), 'Rapports supprimés')
  load()
}

async function restore(b) {
  if (!confirm(`Restaurer ${b.name} ? Wolf sera redémarré (la config actuelle est sauvegardée avant).`)) return
  await act('Restauration', () => api.post(`/backups/${b.name}/restore`), 'Configuration restaurée')
  load()
}

async function pull(img) {
  const j = await act('Lancement', () => api.post('/images/pull', { image: img.ref }))
  if (j) jobId.value = j.id
}

const date = ts => new Date(ts * 1000).toLocaleString('fr-FR')

onMounted(load)
</script>

<template>
  <div class="page-head"><h1>Maintenance</h1></div>
  <div v-if="error" class="alert bad">{{ error }}</div>

  <div v-if="wolf" class="card">
    <div class="row between">
      <div>
        <h2 class="row" style="margin:0"><span class="dot" :class="wolf.running ? 'ok' : 'bad'"></span> Serveur Wolf</h2>
        <div class="muted small" style="margin-top:4px">
          {{ wolf.status }} · démarré {{ ago(wolf.started_at) }} · API {{ wolf.api ? 'OK' : 'injoignable' }}
          · <span class="mono">{{ wolf.image }}</span>
        </div>
      </div>
      <div class="row">
        <button @click="wolfAction('restart', 'Redémarrage de Wolf')">🔄 Redémarrer</button>
        <button v-if="wolf.running" class="danger" @click="wolfAction('stop', 'Arrêt de Wolf')">⏹ Arrêter</button>
        <button v-else class="primary" @click="wolfAction('start', 'Démarrage de Wolf')">▶ Démarrer</button>
      </div>
    </div>
  </div>

  <div class="card">
    <div class="row between" style="margin-bottom:10px">
      <h2 style="margin:0">Journaux de Wolf</h2>
      <div class="row">
        <input v-model="filter" placeholder="Filtrer (ERROR, pin…)" style="width:200px" />
        <select v-model.number="tail" style="width:auto">
          <option :value="100">100 lignes</option>
          <option :value="300">300 lignes</option>
          <option :value="1000">1000 lignes</option>
          <option :value="5000">5000 lignes</option>
        </select>
        <button @click="loadLogs">📜 {{ logs ? 'Actualiser' : 'Afficher' }}</button>
      </div>
    </div>
    <pre v-if="logs" class="logbox">{{ shownLogs }}</pre>
  </div>

  <template v-if="m">
    <div class="card">
      <div class="row between" style="margin-bottom:10px">
        <h2 style="margin:0">Conteneurs d'applications</h2>
        <button class="sm" @click="prune">🧹 Supprimer les conteneurs arrêtés</button>
      </div>
      <div v-if="!m.containers.length" class="empty">Aucun conteneur d'application.</div>
      <div v-else class="table-wrap">
        <table>
          <thead><tr><th>Nom</th><th>Application</th><th>État</th><th>Créé</th><th></th></tr></thead>
          <tbody>
            <tr v-for="c in m.containers" :key="c.id">
              <td class="mono small">{{ c.name }}</td>
              <td>{{ c.app }}</td>
              <td><span class="badge" :class="c.status === 'running' ? 'ok' : 'warn'">{{ c.status }}</span></td>
              <td class="small muted">{{ ago(c.created) }}</td>
              <td style="text-align:right;white-space:nowrap">
                <button v-if="c.status === 'running'" class="sm" @click="containerAction(c, 'stop')">⏹</button>
                <button class="sm danger" @click="containerAction(c, 'remove')">🗑</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="grid cols-2" style="margin-top:16px">
      <div class="card">
        <h2>Images des applications</h2>
        <table class="small">
          <tbody>
            <tr v-for="img in m.images" :key="img.ref">
              <td class="mono">{{ img.ref }}</td>
              <td>
                <span v-if="img.present" class="muted">{{ ago(img.created) }} · {{ bytes(img.size) }}</span>
                <span v-else class="badge bad">absente</span>
              </td>
              <td style="text-align:right">
                <button v-if="img.ref.includes('/')" class="sm" title="Mettre à jour" @click="pull(img)">⬇</button>
                <router-link v-else to="/emulateurs" class="small">construire</router-link>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="card">
        <div class="row between" style="margin-bottom:10px">
          <h2 style="margin:0">Rapports de plantage ({{ m.backtraces.length }})</h2>
          <button v-if="m.backtraces.length" class="sm danger" @click="clearBacktraces">🗑 Tout supprimer</button>
        </div>
        <div v-if="!m.backtraces.length" class="empty">Aucun plantage enregistré 🎉</div>
        <table v-else class="small">
          <tbody>
            <tr v-for="b in m.backtraces.slice(0, 8)" :key="b.name">
              <td>{{ date(b.mtime) }}</td><td class="muted">{{ bytes(b.size) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <h2>Sauvegardes de config.toml</h2>
      <p class="muted small" style="margin-top:-6px">Une sauvegarde est créée avant chaque modification faite par Wolfy (30 conservées).</p>
      <div v-if="!m.backups.length" class="empty">Aucune sauvegarde pour l'instant.</div>
      <div v-else class="table-wrap">
        <table class="small">
          <tbody>
            <tr v-for="b in m.backups" :key="b.name">
              <td class="mono">{{ b.name.replace('config.toml.', '') }}</td>
              <td class="muted">{{ date(b.mtime) }}</td>
              <td style="text-align:right;white-space:nowrap">
                <a class="btn sm" :href="`/api/backups/${b.name}`" download>⬇</a>
                <button class="sm" @click="restore(b)">↺ Restaurer</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="jobs.length" class="card">
      <h2>Tâches récentes</h2>
      <table class="small">
        <tbody>
          <tr v-for="j in jobs" :key="j.id">
            <td>{{ j.title }}</td>
            <td><span class="badge" :class="{ ok: j.status === 'success', bad: j.status === 'error', warn: j.status === 'running' }">{{ j.status }}</span></td>
            <td class="muted">{{ j.started.replace('T', ' ') }}</td>
            <td style="text-align:right"><button class="sm" @click="jobId = j.id">Journal</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </template>

  <JobLog v-if="jobId" :job-id="jobId" @close="jobId = ''" @done="load" />
</template>
