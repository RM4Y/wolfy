<script setup>
// App Switch (Eglantine): keys and firmware uploads, games folders (fixed locations).
import { onMounted, ref } from 'vue'
import { api, toast, upload } from '../api'

const emit = defineEmits(['close'])
const status = ref(null)
const running = ref(false)
const progress = ref({}) // keys|firmware -> 0..1

async function load() {
  const r = await api.get('/emulators/switch/paths')
  status.value = r.status
  running.value = r.session_running
}

async function send(kind, files) {
  if (!files?.length) return
  if (kind === 'firmware' && !confirm('Remplacer le firmware installé ? L\'actuel est gardé en sauvegarde (registered.bak).')) return
  const fd = new FormData()
  if (kind === 'keys') for (const f of files) fd.append('files', f, f.name)
  else fd.append('file', files[0], files[0].name)
  progress.value = { ...progress.value, [kind]: 0 }
  try {
    const r = await upload(`/emulators/switch/${kind}`, fd, p => (progress.value = { ...progress.value, [kind]: p }))
    status.value = r.status
    toast(kind === 'keys' ? `Clés installées : ${r.installed.join(', ')}`
      : `Firmware installé (${r.installed} fichiers) — version affichée au prochain lancement de Switch`)
  } catch (e) {
    toast(e.message, 'error')
  } finally {
    const p = { ...progress.value }; delete p[kind]; progress.value = p
  }
}

function badge(s) {
  if (!s) return { cls: '', text: '…' }
  if (!s.exists) return { cls: 'bad', text: 'introuvable' }
  return { cls: s.ok ? 'ok' : 'warn', text: s.detail }
}

onMounted(load)
</script>

<template>
  <div class="modal-back" @click.self="emit('close')">
    <div class="modal">
      <div class="row between" style="margin-bottom:14px">
        <h2 style="margin:0">Switch (Eglantine) — clés, firmware, jeux</h2>
        <button type="button" class="ghost sm icon" @click="emit('close')" aria-label="Fermer"><Icon name="x" /></button>
      </div>

      <template v-if="status">
        <div v-if="running" class="alert warn small" style="margin-bottom:14px">
          <Icon name="alert" />Une session Switch est en cours : quitte-la avant d'installer un firmware. Les clés
          sont prises en compte au prochain lancement.
        </div>
        <div class="grid cols-3" style="gap:12px">
          <div class="card box">
            <h3>Clés</h3>
            <span class="badge" :class="badge(status.keys).cls">{{ badge(status.keys).text }}</span>
            <p class="muted small">prod.keys et title.keys (ou un .zip les contenant). Les actuelles sont gardées en sauvegarde.</p>
            <label class="btn sm" :class="{ disabled: progress.keys !== undefined }">
              <Icon name="upload" />Envoyer les clés
              <input type="file" multiple accept=".keys,.zip" hidden @change="send('keys', $event.target.files); $event.target.value = ''" />
            </label>
            <progress v-if="progress.keys !== undefined" :value="progress.keys" max="1"></progress>
          </div>

          <div class="card box">
            <h3>Firmware</h3>
            <span class="badge" :class="badge(status.firmware).cls">{{ badge(status.firmware).text }}</span>
            <p class="muted small">Archive .zip du firmware (fichiers .nca). Remplace l'actuel, gardé en sauvegarde.</p>
            <label class="btn sm" :class="{ disabled: progress.firmware !== undefined || running }">
              <Icon name="upload" />Installer un firmware
              <input type="file" accept=".zip" hidden @change="send('firmware', $event.target.files); $event.target.value = ''" />
            </label>
            <template v-if="progress.firmware !== undefined">
              <progress :value="progress.firmware" max="1"></progress>
              <span class="small muted">{{ progress.firmware < 1 ? `envoi ${Math.round(progress.firmware * 100)} %` : 'installation…' }}</span>
            </template>
          </div>

          <div class="card box">
            <h3>Jeux</h3>
            <span class="badge" :class="badge(status.roms).cls">{{ badge(status.roms).text }}</span>
            <p class="muted small">À déposer dans <code>{{ status.roms.path }}</code> (par SSH), en lecture seule dans la session.</p>
            <span class="muted small">{{ status.saves.detail }}</span>
          </div>
        </div>
        <div class="help" style="margin-top:14px">Dans <code>config/switch/data/keys</code> et
          <code>config/switch/data/nand</code> (comptes et sauvegardes compris).</div>

        <div class="row end" style="margin-top:16px">
          <button type="button" class="ghost" @click="emit('close')">Fermer</button>
        </div>
      </template>
      <div v-else class="empty"><div class="spinner" style="margin:auto"></div></div>
    </div>
  </div>
</template>

<style scoped>
.box { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; background: var(--surface-raised); }
.box h3 { margin: 0; }
.box p { margin: 0; }
.btn.disabled { pointer-events: none; opacity: .5; }
progress { width: 100%; accent-color: var(--brand); }
</style>
