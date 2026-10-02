<script setup>
// PS3 (RPCS3) and PS Vita (Vita3K) in the PlayStation app: firmware, games, installs from the ROM folders.
import { onMounted, ref } from 'vue'
import { api, bytes, toast, upload } from '../api'
import JobLog from './JobLog.vue'

const data = ref(null)
const progress = ref({})
const zrif = ref({})
const jobId = ref('')
const showGames = ref({})

const SYSTEMS = [
  { id: 'ps3', title: '🎮 PS3 (RPCS3)', pup: 'PS3UPDAT.PUP',
    help: 'Jeux disque : dossiers décryptés (<jeu>/PS3_GAME/…) dans un dossier de jeux, utilisés tels quels. Jeux PSN, mises à jour, DLC : .pkg (+ licence .rap) à installer ci-dessous.' },
  { id: 'vita', title: '🎮 PS Vita (Vita3K)', pup: 'PSVUPDAT.PUP',
    help: 'Les jeux sont installés dans Vita3K : .vpk / .zip / dossier (dumps NoNpDrm), ou .pkg + licence zRIF.' },
]
const KINDS = {
  'ps3-pkg': 'PS3 · paquet', 'ps3-rap': 'PS3 · licence', 'ps3-firmware': 'PS3 · firmware',
  'vita-pkg': 'Vita · paquet (zRIF)', 'vita-archive': 'Vita · archive', 'vita-folder': 'Vita · dossier',
  'vita-firmware': 'Vita · firmware',
}

async function load() {
  try { data.value = await api.get('/emulators/retroarch/ps') } catch (e) { toast(e.message, 'error') }
}

async function sendFirmware(system, files) {
  if (!files?.length) return
  const fd = new FormData()
  fd.append('file', files[0], files[0].name)
  progress.value = { ...progress.value, [system]: 0 }
  try {
    const r = await upload(`/emulators/retroarch/ps/firmware/${system}`, fd,
      p => (progress.value = { ...progress.value, [system]: p }))
    jobId.value = r.job.id
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    progress.value = { ...progress.value, [system]: null }
  }
}

async function install(item) {
  if (item.kind === 'vita-pkg' && !zrif.value[item.path]) return toast('Colle la licence zRIF du jeu', 'error')
  try {
    const r = await api.post('/emulators/retroarch/ps/install', { path: item.path, zrif: zrif.value[item.path] || '' })
    jobId.value = r.job.id
  } catch (e) {
    toast(e.message, 'error')
  }
}

onMounted(load)
defineExpose({ load })
</script>

<template>
  <template v-if="data">
    <div class="grid cols-2" style="gap:12px">
      <div v-for="s in SYSTEMS" :key="s.id" class="card box">
        <h3>{{ s.title }}</h3>
        <span class="badge" :class="data[s.id].firmware ? 'ok' : 'warn'">
          {{ data[s.id].firmware ? `Firmware ${data[s.id].firmware}` : 'Firmware manquant' }}
        </span>
        <label class="btn sm" :class="{ disabled: progress[s.id] != null }">
          ⬆ Envoyer {{ s.pup }}
          <input type="file" accept=".pup,.PUP" hidden @change="sendFirmware(s.id, $event.target.files); $event.target.value = ''" />
        </label>
        <progress v-if="progress[s.id] != null" :value="progress[s.id]" max="1"></progress>
        <button type="button" class="ghost sm" @click="showGames[s.id] = !showGames[s.id]">
          {{ showGames[s.id] ? '▾' : '▸' }} {{ data[s.id].games.length }} jeu(x)
        </button>
        <ul v-if="showGames[s.id]" class="games small">
          <li v-for="g in data[s.id].games" :key="g.path"><b>{{ g.title }}</b> <span class="muted">{{ g.id }} · {{ g.where }}</span></li>
          <li v-if="!data[s.id].games.length" class="muted">Aucun jeu trouvé.</li>
        </ul>
        <p class="muted small">{{ s.help }}</p>
      </div>
    </div>

    <div class="field" style="margin-top:14px">
      <label>📦 À installer (trouvé dans les dossiers de jeux)</label>
      <div v-for="it in data.installables" :key="it.path" class="row install" style="flex-wrap:nowrap">
        <span class="badge">{{ KINDS[it.kind] }}</span>
        <span class="mono small grow" :title="it.path">{{ it.name }} <span class="muted">{{ it.size != null ? bytes(it.size) : '' }}</span></span>
        <input v-if="it.kind === 'vita-pkg'" v-model="zrif[it.path]" class="mono small" placeholder="zRIF (KO5ifR1d…)" style="max-width:220px" />
        <button type="button" class="sm" @click="install(it)">Installer</button>
      </div>
      <div v-if="!data.installables.length" class="muted small">Rien à installer.</div>
      <div class="help">
        Dépose les .pkg, .rap, .vpk, .zip ou firmwares .PUP dans un dossier de jeux (par ex. <code>ROMS/ps3</code>,
        <code>ROMS/psvita</code>), puis installe-les ici. Les jeux apparaissent dans le XMB à la session suivante.
      </div>
    </div>
  </template>
  <div v-else class="empty"><div class="spinner" style="margin:auto"></div></div>

  <JobLog v-if="jobId" :job-id="jobId" @close="jobId = ''" @done="load" />
</template>

<style scoped>
.box { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; background: var(--card-2); }
.box h3, .box p { margin: 0; }
.btn.disabled { pointer-events: none; opacity: .5; }
progress { width: 100%; accent-color: var(--accent); }
.games { margin: 0; padding-left: 18px; max-height: 200px; overflow: auto; align-self: stretch; }
.install { padding: 6px 0; border-bottom: 1px solid var(--border, rgba(127,127,127,.2)); gap: 8px; }
.grow { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
