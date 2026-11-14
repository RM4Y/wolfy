<script setup>
import { onMounted, ref } from 'vue'
import { act, api, ago, bytes } from '../api'
import SwitchPaths from '../components/SwitchPaths.vue'
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

// app Switch: installed emulator (Eglantine, or Lichii), newest release on GitHub, update with the patches
const emuVer = ref(null)
async function loadEmuVer(refresh = false) {
  const r = refresh ? await act('Vérification', () => api.get('/emulators/switch/version?refresh=true'))
    : await api.get('/emulators/switch/version').catch(() => null)
  if (r) emuVer.value = r
}

async function updateEmu() {
  const name = emuVer.value.current.name
  const to = emuVer.value.latest.tag
  if (!confirm(`Mettre ${name} à jour vers ${to} ?\n\nWolfy télécharge les sources, réapplique ses patchs (menu HOME, `
    + `lanceur, profil…), recompile ${name} puis reconstruit l'image : 15 à 40 minutes. Si un patch ne s'applique `
    + `plus, rien n'est changé.\nLa nouvelle version sera active à la prochaine session Switch.`)) return
  const j = await act('Lancement', () => api.post('/emulators/switch/update', { tag: to }))
  if (j) { jobId.value = j.id; loadEmuVer() }
}

// other apps' images (Wii / GameCube, PlayStation, Steam): the emulators and base image they hold,
// the newest versions, update = the image built again with them
const imgVer = ref({})  // emulator id -> { components, update_available, error, job }
async function loadImgVer(emu, refresh = false) {
  const url = `/emulators/${emu.id}/image-versions${refresh ? '?refresh=true' : ''}`
  const r = refresh ? await act('Vérification', () => api.get(url)) : await api.get(url).catch(() => null)
  if (r) imgVer.value = { ...imgVer.value, [emu.id]: r }
}
const loadAllImgVer = () => emulators.value.filter(e => e.updatable).forEach(e => loadImgVer(e))
const toUpdate = emu => (imgVer.value[emu.id]?.components || []).filter(c => c.update)

async function updateImage(emu) {
  const list = toUpdate(emu).map(c => `• ${c.name} : ${c.installed || '?'} → ${c.latest}`).join('\n')
  if (!confirm(`Mettre ${emu.name} à jour ?\n\n${list}\n\nWolfy reconstruit l'image ${emu.image} avec ces versions`
    + (emu.id === 'dolphin' ? ' (Dolphin est recompilé : 10 à 20 minutes)' : '')
    + `. Si la construction échoue, l'image installée ne change pas.\nActif à la prochaine session.`)) return
  const j = await act('Lancement', () => api.post(`/emulators/${emu.id}/image-update`))
  if (j) { jobId.value = j.id; loadImgVer(emu) }
}

async function pull(emu) {
  const j = await act('Lancement', () => api.post('/images/pull', { image: emu.image, emulator: emu.id }))
  if (j) jobId.value = j.id
}

onMounted(async () => { await load(); loadEmuVer(); loadAllImgVer() })
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
          <tr v-if="emu.id === 'switch' && emuVer">
            <td class="muted">Version</td>
            <td>
              <b>{{ emuVer.current.name }} {{ emuVer.current.tag }}</b>
              <span v-if="emuVer.job" class="badge warn" style="margin-left:6px">mise à jour en cours…</span>
              <span v-else-if="emuVer.update_available" class="badge warn" style="margin-left:6px">
                <a :href="emuVer.latest.url" target="_blank" rel="noopener">{{ emuVer.latest.tag }}</a> disponible</span>
              <span v-else-if="emuVer.latest" class="badge ok" style="margin-left:6px">à jour</span>
              <span v-if="emuVer.error" class="muted"> · {{ emuVer.error }}</span>
            </td>
          </tr>
          <template v-if="imgVer[emu.id]">
            <tr v-for="c in imgVer[emu.id].components" :key="c.key">
              <td class="muted">{{ c.name }}</td>
              <td>
                <b>{{ c.installed || 'inconnue' }}</b>
                <span v-if="c.update" class="badge warn" style="margin-left:6px">
                  <a v-if="c.url" :href="c.url" target="_blank" rel="noopener">{{ c.latest }}</a><template v-else>{{ c.latest }}</template>
                  disponible</span>
                <span v-else-if="c.latest" class="badge ok" style="margin-left:6px">à jour</span>
              </td>
            </tr>
            <tr v-if="imgVer[emu.id].job || imgVer[emu.id].error">
              <td></td>
              <td>
                <span v-if="imgVer[emu.id].job" class="badge warn">mise à jour en cours…</span>
                <span v-if="imgVer[emu.id].error" class="muted small"> {{ imgVer[emu.id].error }}</span>
              </td>
            </tr>
          </template>
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
        <button v-if="emu.paths_page" class="primary" @click="pathsFor = emu.paths_page"><Icon name="sliders" />{{ { switch: 'Clés, firmware, jeux', retroarch: 'BIOS, jeux, sauvegardes', steam: 'Bibliothèques, compte' }[emu.paths_page] }}</button>
        <template v-if="emu.id === 'switch' && emuVer">
          <button v-if="emuVer.job" @click="jobId = emuVer.job.id"><Icon name="hammer" />Voir la mise à jour</button>
          <button v-else-if="emuVer.update_available" class="primary" @click="updateEmu">
            <Icon name="download" />Mettre à jour vers {{ emuVer.latest.tag }}</button>
          <button v-else @click="loadEmuVer(true)"><Icon name="refresh" />Vérifier les mises à jour</button>
        </template>
        <template v-if="emu.updatable && imgVer[emu.id] && emu.image_info.present">
          <button v-if="imgVer[emu.id].job" @click="jobId = imgVer[emu.id].job.id"><Icon name="hammer" />Voir la mise à jour</button>
          <button v-else-if="imgVer[emu.id].update_available" class="primary" @click="updateImage(emu)">
            <Icon name="download" />Mettre à jour ({{ toUpdate(emu).length }})</button>
          <button v-else @click="loadImgVer(emu, true)"><Icon name="refresh" />Vérifier les mises à jour</button>
        </template>
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

  <SwitchPaths v-if="pathsFor === 'switch'" @close="pathsFor = ''; load()" />
  <RetroArchPaths v-if="pathsFor === 'retroarch'" @close="pathsFor = ''; load()" />
  <SteamPaths v-if="pathsFor === 'steam'" @close="pathsFor = ''; load()" />
  <JobLog v-if="jobId" :job-id="jobId" @close="jobId = ''; loadEmuVer(); loadAllImgVer()" @done="load(); loadEmuVer(); loadAllImgVer()" />
</template>
