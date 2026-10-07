<script setup>
// "EspBar" tab of the Wii settings: the ESP32 that connects Wii Remotes over Bluetooth and
// sends them through Wolfy to the Dolphin of the linked device's Wii session. Its program
// (espbar/firmware.bin) and Wi-Fi settings are injected from the browser (Web Serial, ESP32
// plugged into this computer).
import { nextTick, onMounted, onUnmounted, ref } from 'vue'
import { act, api, bytes, toast } from '../api'

const data = ref(null)
const error = ref('')
const serial = 'serial' in navigator  // Chrome / Edge, over https or localhost
const flashing = ref(null)  // progress 0..1 while flashing
const eraseAll = ref(false)
const log = ref('')
const logBox = ref(null)
const wifi = ref(null)  // { ssid, password, url }
let timer

// Wolfy's WebSocket for the ESP32: the external address (Paramètres), else the address
// Wolfy is opened with (https://wolfy.rm4.fr -> wss://wolfy.rm4.fr/api/espbar/ws)
const defaultUrl = () => data.value?.public_host
  ? `wss://${data.value.public_host}/api/espbar/ws`
  : `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/espbar/ws`

async function load() {
  clearTimeout(timer)
  try {
    data.value = await api.get('/espbar')
    wifi.value ??= { ...data.value.wifi, url: data.value.wifi.url || defaultUrl() }
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
  timer = setTimeout(load, 3000)
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
  if (!wifi.value.ssid || !wifi.value.url) {
    toast('Renseigne le Wi-Fi avant d\'injecter', 'error')
    return
  }
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
    const get = (url, opts) => fetch(url, opts).then(r => {
      if (!r.ok) throw new Error(`${url} : erreur ${r.status}`)
      return r.arrayBuffer()
    })
    const [{ ESPLoader, Transport }, bin, cfg] = await Promise.all([
      import('esptool-js'),
      get('/api/espbar/firmware'),
      get('/api/espbar/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(wifi.value),
      }),
    ])
    transport = new Transport(port, false)
    const loader = new ESPLoader({ transport, baudrate: 921600, romBaudrate: 115200, terminal })
    const chip = await loader.main()
    if (fw.chip && loader.chip.IMAGE_CHIP_ID !== fw.chip_id) {
      throw new Error(`Le programme est compilé pour ${fw.chip}, la carte branchée est un ${chip}`)
    }
    await loader.writeFlash({
      fileArray: [
        { data: new Uint8Array(bin), address: fw.offset },
        { data: new Uint8Array(cfg), address: fw.config_offset },  // Wi-Fi + Wolfy
      ],
      flashMode: 'keep', flashFreq: 'keep', flashSize: 'keep',
      eraseAll: fw.merged && eraseAll.value, compress: true,
      reportProgress: (_, written, total) => (flashing.value = written / total),
    })
    await loader.after('hard_reset')
    write('\n✅ Programme écrit, l\'ESP32 redémarre.\n')
    toast('Programme injecté dans l\'ESP32')
  } catch (e) {
    write(`\n❌ ${e.message}\n`)
    toast(e.message, 'error')
  } finally {
    flashing.value = null
    await transport?.disconnect().catch(() => {})
  }
}

const clientLabel = c => c.name || `Appareil ${c.client_ip || c.client_id.slice(-4)}`

onMounted(load)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <div v-if="error" class="alert bad">{{ error }}</div>
  <template v-if="data">
    <div class="card">
      <h2 style="margin:0 0 4px">📡 État</h2>
      <div class="muted small" style="margin-bottom:12px">
        L'EspBar connecte les Wiimotes en Bluetooth et les envoie, par le Wi-Fi, au Dolphin de la session Wii
        de l'appareil relié. Pour connecter une Wiimote : appuie sur 1 + 2 pendant une session Wii, avec le
        joueur réglé sur « Vraie Wiimote » (onglet Wolfy-Dolphin).
      </div>
      <div v-if="!data.status.online" class="alert warn small">
        ESP32 non connecté à Wolfy (LED bleue clignotante : Wi-Fi ou adresse de Wolfy à vérifier).
      </div>
      <template v-else>
        <div class="small">
          ✅ ESP32 connecté depuis {{ data.status.esp.since }} — {{ data.status.esp.ip }}
          <span class="muted">· {{ data.status.esp.mac }}</span>
        </div>
        <div class="small" style="margin-top:6px">
          <template v-if="data.status.session">
            🎮 Session Wii de {{ data.status.client_name || 'l\'appareil relié' }} en cours : recherche des Wiimotes active
          </template>
          <span v-else class="muted">Pas de session Wii de l'appareil relié : les Wiimotes ne sont pas recherchées</span>
        </div>
        <div v-for="w in data.status.wiimotes" :key="w.slot" class="small" style="margin-top:4px">
          🕹️ Wiimote {{ w.slot }} <span class="muted">{{ w.addr }}</span>
        </div>
      </template>
    </div>

    <div class="card">
      <h2 style="margin:0 0 4px">📶 Wi-Fi de l'EspBar</h2>
      <div class="muted small" style="margin-bottom:14px">
        Écrit dans l'ESP32 avec le programme : réinjecte après un changement.
      </div>
      <div class="row" style="gap:8px">
        <input v-model="wifi.ssid" placeholder="Nom du Wi-Fi (SSID)" maxlength="32" style="flex:1;min-width:160px" />
        <input v-model="wifi.password" type="password" placeholder="Mot de passe" maxlength="64"
               autocomplete="new-password" style="flex:1;min-width:160px" />
      </div>
      <div class="row" style="gap:8px;margin-top:8px;align-items:center">
        <span class="small" style="white-space:nowrap">Adresse de Wolfy</span>
        <input v-model="wifi.url" maxlength="200" style="flex:1;min-width:220px" />
        <button type="button" class="ghost sm" title="Adresse externe (Paramètres)" @click="wifi.url = defaultUrl()">↺</button>
      </div>
      <div class="muted small" style="margin-top:6px">
        L'ESP32 joint Wolfy à cette adresse : <code>wss://&lt;adresse externe&gt;/…</code> (Paramètres › Adresse
        externe) marche de partout, même chez un appareil distant ; <code>ws://&lt;IP du serveur&gt;:8420/…</code>
        seulement sur le réseau local.
        <router-link v-if="!data.public_host" to="/parametres">Renseigner l'adresse externe</router-link>
      </div>
    </div>

    <div class="card">
      <h2 style="margin:0 0 4px">💉 Injecter le programme dans l'ESP32</h2>
      <div class="muted small" style="margin-bottom:14px">
        Branche l'ESP32 en USB sur cet ordinateur, clique sur « Injecter » et choisis son port série. Si la
        carte ne répond pas, maintiens le bouton BOOT au début de l'injection.
      </div>
      <div v-if="!data.firmware" class="alert warn small">
        Le programme de l'EspBar n'est pas encore compilé (<code>espbar/firmware.bin</code>).
      </div>
      <div v-else-if="!serial" class="alert warn small">
        Ce navigateur ne peut pas accéder à l'USB : ouvre Wolfy dans Chrome ou Edge, en https
        (ou sur localhost).
      </div>
      <template v-else>
        <div class="row" style="align-items:center;gap:12px">
          <button type="button" class="primary" :disabled="flashing !== null" @click="flash">
            {{ flashing !== null ? `${Math.round(flashing * 100)} %` : '💉 Injecter' }}
          </button>
          <label v-if="data.firmware.merged" class="row" style="gap:10px;align-items:center">
            <span class="switch"><input v-model="eraseAll" type="checkbox" :disabled="flashing !== null" /><span></span></span>
            Effacer toute la mémoire avant (réglages Wi-Fi compris)
          </label>
        </div>
        <div class="muted small" style="margin-top:8px">
          {{ data.firmware.chip || 'puce inconnue' }} · {{ bytes(data.firmware.size) }} ·
          compilé le {{ data.firmware.built_at }} ·
          <span :title="data.firmware.sha256">sha256 {{ data.firmware.sha256.slice(0, 12) }}…</span>
          <template v-if="!data.firmware.merged"> · appli seule (la carte doit déjà avoir un bootloader)</template>
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
