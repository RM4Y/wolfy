<script setup>
// "EspBar" tab of the Wii settings: the ESP32 program (.bin), flashed from the browser
// (Web Serial, ESP32 plugged into this computer), and the paired Moonlight device it is linked to.
import { nextTick, onMounted, ref } from 'vue'
import { act, api, bytes, toast, upload } from '../api'

const data = ref(null)
const error = ref('')
const progress = ref(null)
const input = ref(null)
const serial = 'serial' in navigator  // Chrome / Edge, over https or localhost
const flashing = ref(null)  // progress 0..1 while flashing
const eraseAll = ref(false)
const log = ref('')
const logBox = ref(null)

async function load() {
  try {
    data.value = await api.get('/espbar')
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
}

async function send(e) {
  const file = e.target.files[0]
  if (!file) return
  if (data.value.firmware && !confirm(`Remplacer le programme actuel par « ${file.name} » ?`)) {
    input.value.value = ''
    return
  }
  const fd = new FormData()
  fd.append('file', file)
  progress.value = 0
  try {
    await upload('/espbar/firmware', fd, p => (progress.value = p))
    toast('Programme envoyé')
    load()
  } catch (err) {
    toast(err.message, 'error')
  } finally {
    progress.value = null
    input.value.value = ''
  }
}

async function remove() {
  if (!confirm('Supprimer le programme ESP32 ?')) return
  if (await act('Suppression', () => api.del('/espbar/firmware'), 'Programme supprimé')) load()
}

async function link(clientId) {
  const ok = await act('Enregistrement', () => api.put('/espbar/client', { client_id: clientId || null }),
    clientId ? 'EspBar reliée à l\'appareil' : 'EspBar déliée')
  if (ok) load()
}

function write(text) {
  log.value += text
  nextTick(() => logBox.value && (logBox.value.scrollTop = logBox.value.scrollHeight))
}
const terminal = { clean: () => (log.value = ''), writeLine: t => write(`${t}\n`), write }

async function flash() {
  const fw = data.value.firmware
  let port
  try {
    port = await navigator.serial.requestPort()
  } catch {
    return // no port chosen
  }
  log.value = ''
  flashing.value = 0
  let transport
  try {
    const [{ ESPLoader, Transport }, bin] = await Promise.all([
      import('esptool-js'),
      fetch('/api/espbar/firmware').then(r => {
        if (!r.ok) throw new Error(`Téléchargement du programme : erreur ${r.status}`)
        return r.arrayBuffer()
      }),
    ])
    transport = new Transport(port, false)
    const loader = new ESPLoader({ transport, baudrate: 921600, romBaudrate: 115200, terminal })
    const chip = await loader.main()
    if (fw.chip && loader.chip.IMAGE_CHIP_ID !== fw.chip_id) {
      throw new Error(`Le programme est compilé pour ${fw.chip}, la carte branchée est un ${chip}`)
    }
    await loader.writeFlash({
      fileArray: [{ data: new Uint8Array(bin), address: fw.offset }],
      flashMode: 'keep', flashFreq: 'keep', flashSize: 'keep',
      eraseAll: fw.merged && eraseAll.value, compress: true,
      reportProgress: (_, written, total) => (flashing.value = written / total),
    })
    await loader.after('hard_reset')
    write('\n✅ Programme écrit, l\'ESP32 redémarre.\n')
    toast('ESP32 flashé')
  } catch (e) {
    write(`\n❌ ${e.message}\n`)
    toast(e.message, 'error')
  } finally {
    flashing.value = null
    await transport?.disconnect().catch(() => {})
  }
}

const hex = n => `0x${n.toString(16)}`
const download = () => { window.location.href = '/api/espbar/firmware' }
const clientLabel = c => c.name || `Appareil ${c.client_ip || c.client_id.slice(-4)}`

onMounted(load)
</script>

<template>
  <div v-if="error" class="alert bad">{{ error }}</div>
  <template v-if="data">
    <div class="card">
      <h2 style="margin:0">💾 Programme ESP32</h2>
      <div class="muted small" style="margin-bottom:14px">
        Fichier <code>.bin</code> compilé (Arduino : « Exporter les binaires compilés », PlatformIO :
        <code>.pio/build/…/firmware.bin</code>). Un nouvel envoi remplace le programme actuel.
      </div>
      <div v-if="data.firmware" class="row" style="align-items:center;margin-bottom:12px">
        <div style="flex:1;min-width:200px">
          <b>{{ data.firmware.filename }}</b>
          <div class="muted small">
            {{ bytes(data.firmware.size) }} · envoyé le {{ data.firmware.uploaded_at }} ·
            <span :title="data.firmware.sha256">sha256 {{ data.firmware.sha256.slice(0, 12) }}…</span>
          </div>
          <div v-if="data.firmware.offset !== undefined" class="muted small">
            {{ data.firmware.chip || 'puce inconnue' }} ·
            {{ data.firmware.merged ? 'image complète (bootloader + partitions + appli)' : 'appli seule' }},
            écrite à {{ hex(data.firmware.offset) }}
          </div>
        </div>
        <button type="button" class="ghost sm" title="Télécharger" @click="download">⬇️</button>
        <button type="button" class="ghost sm" title="Supprimer" @click="remove">🗑️</button>
      </div>
      <div v-else class="muted small" style="margin-bottom:12px">Aucun programme envoyé.</div>
      <div class="row" style="align-items:center;gap:8px">
        <input ref="input" type="file" accept=".bin,application/octet-stream" :disabled="progress !== null"
               style="flex:1;min-width:200px" @change="send" />
        <span v-if="progress !== null" class="muted">{{ Math.round(progress * 100) }} %</span>
      </div>
    </div>

    <div v-if="data.firmware" class="card">
      <h2 style="margin:0 0 4px">⚡ Flasher l'ESP32</h2>
      <div class="muted small" style="margin-bottom:14px">
        Branche l'ESP32 en USB sur cet ordinateur, puis choisis son port série. Si la carte ne répond pas,
        maintiens le bouton BOOT au début du flash.
      </div>
      <div v-if="!serial" class="alert warn small">
        Ce navigateur ne peut pas accéder à l'USB : ouvre Wolfy dans Chrome ou Edge, en https
        (ou sur localhost).
      </div>
      <div v-else-if="data.firmware.offset === undefined" class="alert warn small">
        Renvoie le fichier .bin pour que Wolfy détecte sa puce et son adresse.
      </div>
      <template v-else>
        <div v-if="!data.firmware.merged" class="alert info small" style="margin-bottom:12px">
          Appli seule : la carte doit déjà avoir un bootloader et une table de partitions (un premier
          téléversement depuis Arduino / PlatformIO). Sinon, envoie l'image complète (<code>merged.bin</code>).
        </div>
        <div class="row" style="align-items:center;gap:12px">
          <button type="button" class="primary" :disabled="flashing !== null" @click="flash">
            {{ flashing !== null ? `${Math.round(flashing * 100)} %` : '⚡ Flasher' }}
          </button>
          <label v-if="data.firmware.merged" class="row" style="gap:10px;align-items:center">
            <span class="switch"><input v-model="eraseAll" type="checkbox" :disabled="flashing !== null" /><span></span></span>
            Effacer toute la mémoire avant (réglages Wi-Fi compris)
          </label>
        </div>
        <pre v-if="log" ref="logBox" class="flash-log">{{ log }}</pre>
      </template>
    </div>

    <div class="card">
      <h2 style="margin:0 0 4px">📱 Appareil relié</h2>
      <div class="muted small" style="margin-bottom:14px">L'appareil Moonlight appairé qui utilise l'EspBar.</div>
      <div v-if="!data.clients.length" class="muted small">Aucun appareil appairé à Wolfy.</div>
      <select v-else :value="data.client_id || ''" @change="link($event.target.value)">
        <option value="">— Aucun appareil —</option>
        <option v-for="c in data.clients" :key="c.client_id" :value="c.client_id">
          {{ clientLabel(c) }}{{ c.client_ip ? ` (${c.client_ip})` : '' }}
        </option>
      </select>
    </div>
  </template>
  <div v-else-if="!error" class="empty"><div class="spinner" style="margin:auto"></div></div>
</template>

<style scoped>
.flash-log {
  margin: 12px 0 0; max-height: 260px; overflow: auto; white-space: pre-wrap;
  background: var(--card-2); border: 1px solid var(--line); border-radius: 8px; padding: 10px; font-size: 12px;
}
</style>
