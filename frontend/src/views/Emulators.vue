<script setup>
import { onMounted, ref } from 'vue'
import { act, api, ago, bytes } from '../api'
import EdenPaths from '../components/EdenPaths.vue'
import RetroArchPaths from '../components/RetroArchPaths.vue'
import SteamPaths from '../components/SteamPaths.vue'
import JobLog from '../components/JobLog.vue'

const emulators = ref([])
const apps = ref([])
const jobId = ref('')
const pathsFor = ref('')
const error = ref('')
const registry = ref(null)  // { registry, token }

async function load() {
  try {
    const [e, p, r] = await Promise.all([api.get('/emulators'), api.get('/profiles'), api.get('/registry')])
    registry.value = r
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

// ghcr.io/<owner>/<name>:tag -> the package's page on GitHub
function packageUrl(ref) {
  const m = /^ghcr\.io\/([^/]+)\/([^:]+)/.exec(ref || '')
  return m ? `https://github.com/users/${m[1]}/packages/container/package/${m[2]}` : ''
}

async function restore(emu) {
  if (emu.image_info.present && !confirm(`Remplacer l'image locale ${emu.image} par la copie de GitHub ?`)) return
  const j = await act('Lancement', () => api.post('/images/restore', { image: emu.image, emulator: emu.id }))
  if (j) jobId.value = j.id
}

async function backup(emu) {
  const j = await act('Lancement', () => api.post('/images/backup', { image: emu.image, emulator: emu.id }))
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
  </div>
  <div v-if="error" class="alert bad" style="margin-bottom:16px"><Icon name="alert" /><div>{{ error }}</div></div>

  <div class="grid cols-2">
    <div v-for="emu in emulators.filter(e => e.id !== 'custom')" :key="emu.id" class="card">
      <div class="row between">
        <h2 style="margin:0">{{ emu.name }}</h2>
        <span v-if="emu.image_info.present" class="badge ok">Image prête</span>
        <span v-else class="badge bad">Image absente</span>
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
          <tr v-if="emu.backup">
            <td class="muted">Sauvegarde</td>
            <td class="mono">
              <a v-if="packageUrl(emu.backup)" :href="packageUrl(emu.backup)" target="_blank" rel="noopener">{{ emu.backup }}</a>
              <template v-else>{{ emu.backup }}</template>
            </td>
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
        <button v-if="emu.paths_page" class="primary" @click="pathsFor = emu.paths_page"><Icon name="sliders" />{{ { eden: 'Clés, firmware, jeux', retroarch: 'BIOS, jeux, sauvegardes', steam: 'Bibliothèques, compte' }[emu.paths_page] }}</button>
        <button v-if="emu.buildable" @click="build(emu)"><Icon name="hammer" />{{ emu.image_info.present ? 'Reconstruire' : 'Construire' }}</button>
        <button v-else-if="emu.pullable" @click="pull(emu)"><Icon name="download" />{{ emu.image_info.present ? 'Mettre à jour' : 'Télécharger' }}</button>
        <span v-else class="muted small">Pas de Dockerfile dans <code>images/{{ emu.build_dir }}</code></span>
        <template v-if="emu.backup">
          <button :class="{ primary: !emu.image_info.present }" @click="restore(emu)"><Icon name="download" />Restaurer depuis GitHub</button>
          <button v-if="emu.image_info.present && registry?.token" @click="backup(emu)"><Icon name="upload" />Sauvegarder sur GitHub</button>
        </template>
      </div>
    </div>
  </div>

  <div class="alert" style="margin-top:24px">
    <Icon name="info" />
    <div>Les images locales sont construites depuis <code>images/&lt;émulateur&gt;</code> du dépôt Wolfy (sinon <code>/opt/stacks/wolf/images</code>).
    Une reconstruction ne touche pas aux sessions en cours : les nouvelles sessions utiliseront la nouvelle image.</div>
  </div>
  <div v-if="registry && !registry.token" class="alert" style="margin-top:16px">
    <Icon name="info" />
    <div>Une copie publique des images est gardée sur <code>{{ registry.registry }}</code> : « Restaurer depuis
      GitHub » la récupère. Pour la mettre à jour d'ici, ajoute <code>WOLFY_REGISTRY_TOKEN</code> (jeton GitHub
      avec <code>write:packages</code>) dans <code>.env</code>, puis redémarre Wolfy.</div>
  </div>

  <EdenPaths v-if="pathsFor === 'eden'" @close="pathsFor = ''; load()" />
  <RetroArchPaths v-if="pathsFor === 'retroarch'" @close="pathsFor = ''; load()" />
  <SteamPaths v-if="pathsFor === 'steam'" @close="pathsFor = ''; load()" />
  <JobLog v-if="jobId" :job-id="jobId" @close="jobId = ''" @done="load" />
</template>
