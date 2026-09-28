<script setup>
import { onMounted, ref } from 'vue'
import { act, api, ago, bytes } from '../api'
import EdenPaths from '../components/EdenPaths.vue'
import JobLog from '../components/JobLog.vue'

const emulators = ref([])
const apps = ref([])
const jobId = ref('')
const pathsFor = ref('')
const error = ref('')

async function load() {
  try {
    const [e, p] = await Promise.all([api.get('/emulators'), api.get('/profiles')])
    emulators.value = e.emulators
    apps.value = p.profiles.flatMap(pr => pr.apps.map(a => ({ ...a, moonlight: pr.moonlight })))
    error.value = ''
  } catch (err) {
    error.value = err.message
  }
}

const usedBy = emu => apps.value.filter(a => a.emulator === emu.id && a.moonlight)

async function build(emu) {
  const j = await act('Lancement', () => api.post('/images/build', { image: emu.image, emulator: emu.id }))
  if (j) jobId.value = j.id
}

async function pull(emu) {
  const j = await act('Lancement', () => api.post('/images/pull', { image: emu.image, emulator: emu.id }))
  if (j) jobId.value = j.id
}

onMounted(load)
</script>

<template>
  <div class="page-head">
    <h1>Émulateurs</h1>
    <span class="muted">catalogue des émulateurs principaux utilisables par les applications</span>
  </div>
  <div v-if="error" class="alert bad">{{ error }}</div>

  <div class="grid cols-2">
    <div v-for="emu in emulators.filter(e => e.id !== 'custom')" :key="emu.id" class="card">
      <div class="row between">
        <h2 style="margin:0">{{ emu.name }}</h2>
        <span v-if="emu.image_info.present" class="badge ok">image prête</span>
        <span v-else class="badge bad">image absente</span>
      </div>
      <div class="row" style="margin:8px 0">
        <span v-for="s in emu.systems" :key="s" class="badge">{{ s }}</span>
        <span v-if="!emu.multi_session" class="badge warn">1 session max</span>
      </div>
      <p class="muted small" style="margin:0 0 10px">{{ emu.description }}</p>
      <table class="small">
        <tbody>
          <tr><td class="muted">Image</td><td class="mono">{{ emu.image }}</td></tr>
          <tr v-if="emu.image_info.present">
            <td class="muted">Construite</td>
            <td>{{ ago(emu.image_info.created) }} · {{ bytes(emu.image_info.size) }}</td>
          </tr>
          <tr><td class="muted">ROMs</td><td class="mono">{{ emu.rom_dir || '—' }}</td></tr>
          <tr>
            <td class="muted">Utilisé par</td>
            <td>
              <span v-for="a in usedBy(emu)" :key="a.title" class="badge accent" style="margin-right:4px">{{ a.title }}</span>
              <span v-if="!usedBy(emu).length" class="muted">aucune application Moonlight</span>
            </td>
          </tr>
        </tbody>
      </table>
      <div class="row end" style="margin-top:12px">
        <button v-if="emu.paths_page" class="primary" @click="pathsFor = emu.paths_page">📁 Chemins</button>
        <button v-if="emu.buildable" @click="build(emu)">🔨 {{ emu.image_info.present ? 'Reconstruire' : 'Construire' }}</button>
        <button v-else-if="emu.pullable" @click="pull(emu)">⬇ {{ emu.image_info.present ? 'Mettre à jour' : 'Télécharger' }}</button>
        <span v-else class="muted small">Pas de Dockerfile dans <code>images/{{ emu.build_dir }}</code></span>
      </div>
    </div>
  </div>

  <div class="alert info" style="margin-top:16px">
    Les images locales sont construites depuis <code>images/&lt;émulateur&gt;</code> du dépôt Wolfy (sinon <code>/opt/stacks/wolf/images</code>).
    Une reconstruction ne touche pas aux sessions en cours : les nouvelles sessions utiliseront la nouvelle image.
  </div>

  <EdenPaths v-if="pathsFor === 'eden'" @close="pathsFor = ''; load()" />
  <JobLog v-if="jobId" :job-id="jobId" @close="jobId = ''" @done="load" />
</template>
