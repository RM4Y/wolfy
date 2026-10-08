<script setup>
// "EspBar" tab of the Wii settings: the ESP32 boards that connect Wii Remotes over Bluetooth
// and send them through Wolfy to the Dolphin of the Wii session of each one's device. Its program
// (espbar/firmware.bin for one ESP32, firmware-dual.bin for two: the Wi-Fi one flashes the
// Bluetooth one itself) and Wi-Fi settings are injected from the browser (Web Serial, ESP32
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
const injectClient = ref('')  // device given to the injected EspBar ('' = unchanged)
const variant = ref('dual')  // 'single' (one ESP32) or 'dual' (two)
const dualPart = ref('wifi')  // with two: the ESP32 plugged in, 'wifi' or 'bt' (once, over USB)
const target = () => variant.value === 'dual' && dualPart.value === 'bt' ? 'bt' : variant.value
const fw = () => data.value.firmwares[target()]
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
    if (!data.value.firmwares.dual && data.value.firmwares.single) variant.value = 'single'
    error.value = ''
  } catch (e) {
    error.value = e.message
  }
  timer = setTimeout(load, 3000)
}

async function link(b, clientId) {
  const ok = await act('Enregistrement', () => api.put(`/espbar/boards/${b.key}`, { client_id: clientId || null }),
    clientId ? 'EspBar reliée à l\'appareil' : 'EspBar déliée')
  if (ok) load()
}

async function forget(b) {
  if (!confirm(`Oublier ${boardLabel(b)} ? Elle réapparaîtra à sa prochaine connexion.`)) return
  if (await act('Suppression', () => api.delete(`/espbar/boards/${b.key}`), 'EspBar oubliée')) load()
}

function write(text) {
  log.value += text
  nextTick(() => logBox.value && (logBox.value.scrollTop = logBox.value.scrollHeight))
}
const terminal = { clean: () => (log.value = ''), writeLine: t => write(`${t}\n`), write }

async function flash() {
  const kind = target()
  const fw = data.value.firmwares[kind]
  const withConfig = kind !== 'bt'  // the Bluetooth ESP32 has no Wi-Fi, and is no EspBar of its own
  if (withConfig && (!wifi.value.ssid || !wifi.value.url)) {
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
  let mac = ''  // the chip's base MAC: Wolfy knows the EspBar by it
  try {
    const get = (url, opts) => fetch(url, opts).then(r => {
      if (!r.ok) throw new Error(`${url} : erreur ${r.status}`)
      return r.arrayBuffer()
    })
    const [{ ESPLoader, Transport }, bin, cfg] = await Promise.all([
      import('esptool-js'),
      get(`/api/espbar/firmware?variant=${kind}&sha=${fw.sha256}`, { cache: 'no-store' }),  // not a cached older one
      withConfig && get('/api/espbar/config', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(wifi.value),
      }),
    ])
    // 921600 baud fails on some USB-serial bridges (CP2102: "Invalid head of packet"
    // right after the stub starts): retry at the ROM speed
    for (const baudrate of [921600, 115200]) {
      try {
        transport = new Transport(port, false)
        const loader = new ESPLoader({ transport, baudrate, romBaudrate: 115200, terminal })
        const chip = await loader.main()
        mac = await loader.chip.readMac(loader).catch(() => '')
        if (fw.chip && loader.chip.IMAGE_CHIP_ID !== fw.chip_id) {
          throw Object.assign(new Error(`Le programme est compilé pour ${fw.chip}, la carte branchée est un ${chip}`), { final: true })
        }
        await loader.writeFlash({
          fileArray: [
            { data: new Uint8Array(bin), address: fw.offset },
            ...withConfig ? [{ data: new Uint8Array(cfg), address: fw.config_offset }] : [],  // Wi-Fi + Wolfy
          ],
          flashMode: 'keep', flashFreq: 'keep', flashSize: 'keep',
          eraseAll: fw.merged && eraseAll.value, compress: true,
          reportProgress: (_, written, total) => (flashing.value = written / total),
        })
        await loader.after('hard_reset')
        break
      } catch (e) {
        if (e.final || baudrate === 115200) throw e
        write(`\n⚠️ ${e.message}\nNouvel essai à 115200 bauds (plus lent)...\n\n`)
        flashing.value = 0
        await transport.disconnect().catch(() => {})
        transport = null
        await new Promise(r => setTimeout(r, 500))
      }
    }
    write({
      dual: '\n✅ Programme écrit, l\'ESP32 Wi-Fi redémarre et met à jour l\'ESP32 Bluetooth si besoin (~15 s).\n',
      bt: '\n✅ Programme écrit dans l\'ESP32 Bluetooth : débranche-le de l\'USB et relie-le à l\'ESP32 Wi-Fi.\n',
    }[kind] || '\n✅ Programme écrit, l\'ESP32 redémarre.\n')
    toast('Programme injecté dans l\'ESP32')
    if (mac && withConfig && injectClient.value) {
      await api.put(`/espbar/boards/${mac}`, { client_id: injectClient.value })
      load()
    }
  } catch (e) {
    write(`\n❌ ${e.message}\n`)
    toast(e.message, 'error')
  } finally {
    flashing.value = null
    await transport?.disconnect().catch(() => {})
  }
}

const clientLabel = c => c.name || `Appareil ${c.client_ip || c.client_id.slice(-4)}`
const boardLabel = b => `l'EspBar ${b.key}`
const clientName = id => {
  const c = data.value.clients.find(c => c.client_id === id)
  return c ? clientLabel(c) : 'l\'appareil relié'
}

onMounted(load)
onUnmounted(() => clearTimeout(timer))
</script>

<template>
  <div v-if="error" class="alert bad">{{ error }}</div>
  <template v-if="data">
    <div class="card">
      <h2 style="margin:0 0 4px">📡 EspBar</h2>
      <div class="muted small" style="margin-bottom:12px">
        Une EspBar connecte les Wiimotes en Bluetooth et les envoie, par le Wi-Fi, au Dolphin de la session Wii
        de son appareil (une EspBar par appareil). Pendant une session Wii, elle cherche tant qu'aucune Wiimote
        n'est connectée (LED D15 clignotante) : appuie sur 1 + 2. Pour en ajouter une autre : maintiens 3 s le
        bouton (D4), 30 s de recherche (avec 2 ESP32 : LED et bouton sur l'ESP32 Bluetooth). Joueurs réglés sur
        « Vraie Wiimote » (onglet Wolfy-Dolphin).
      </div>
      <div v-if="!data.boards.length" class="muted small">
        Aucune EspBar : injecte le programme dans un ESP32 (plus bas), elle apparaît ici à sa première connexion.
      </div>
      <div v-for="b in data.boards" :key="b.key" class="board">
        <div class="row" style="gap:8px;align-items:center">
          <code class="small">{{ b.key }}</code>
          <select :value="b.client_id || ''" style="flex:1;min-width:160px" @change="link(b, $event.target.value)">
            <option value="">— Aucun appareil —</option>
            <option v-for="c in data.clients" :key="c.client_id" :value="c.client_id">
              {{ clientLabel(c) }}{{ c.client_ip ? ` (${c.client_ip})` : '' }}
            </option>
          </select>
          <button v-if="!b.status" type="button" class="ghost sm" title="Oublier cette EspBar" @click="forget(b)">🗑️</button>
        </div>
        <div v-if="!b.status" class="small muted" style="margin-top:6px">
          ⚪ Non connectée à Wolfy (LED bleue clignotante : Wi-Fi ou adresse de Wolfy à vérifier)
        </div>
        <template v-else>
          <div class="small" style="margin-top:6px">
            ✅ Connectée depuis {{ b.status.esp.since }} — {{ b.status.esp.ip }}
            <span class="muted">· v{{ b.status.esp.version }}{{ b.status.esp.boards === '2' ? ' · 2 ESP32' : '' }}</span>
          </div>
          <div class="small" style="margin-top:4px">
            <template v-if="b.status.session">
              🎮 Session Wii de {{ clientName(b.client_id) }} en cours : elle reçoit les Wiimotes
            </template>
            <span v-else-if="b.client_id" class="muted">Pas de session Wii de {{ clientName(b.client_id) }} : les Wiimotes s'éteignent</span>
            <span v-else class="muted">Reliée à aucun appareil : choisis-en un</span>
          </div>
          <div v-for="w in b.status.wiimotes" :key="w.slot" class="small" style="margin-top:4px">
            🕹️ Wiimote {{ w.slot }} <span class="muted">{{ w.addr }}</span>
          </div>
          <div v-if="b.status.flow && (b.status.wiimotes.length || b.status.esp.boards === '2')" class="small muted" style="margin-top:4px">
            Flux : {{ b.status.flow }}
          </div>
        </template>
      </div>
    </div>

    <div class="card">
      <h2 style="margin:0 0 4px">📶 Wi-Fi des EspBar</h2>
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
      <div class="row variants" style="gap:8px;margin-bottom:12px">
        <label :class="{ on: variant === 'single' }">
          <input v-model="variant" type="radio" value="single" :disabled="flashing !== null" />
          <b>1 ESP32</b>
          <span class="small muted">Wi-Fi et Bluetooth se partagent l'antenne : ~37 rapports/s par Wiimote</span>
        </label>
        <label :class="{ on: variant === 'dual' }">
          <input v-model="variant" type="radio" value="dual" :disabled="flashing !== null" />
          <b>2 ESP32</b>
          <span class="small muted">Un pour le Wi-Fi, un pour le Bluetooth : jusqu'à 100 rapports/s par Wiimote</span>
        </label>
      </div>
      <div v-if="variant === 'dual'" class="small wiring">
        <div class="row" style="gap:8px;margin-bottom:8px;align-items:center">
          <span style="white-space:nowrap">ESP32 branché en USB</span>
          <select v-model="dualPart" :disabled="flashing !== null" style="flex:1;min-width:160px">
            <option value="wifi">ESP32 Wi-Fi</option>
            <option value="bt">ESP32 Bluetooth (une seule fois)</option>
          </select>
        </div>
        <div style="margin-bottom:6px">
          Injecte <b>une fois</b> l'ESP32 Bluetooth seul, puis l'ESP32 Wi-Fi : ensuite l'ESP32 Wi-Fi met
          lui-même à jour l'ESP32 Bluetooth par les fils. Câblage (ESP32 Wi-Fi → ESP32 Bluetooth) :
        </div>
        <table>
          <tr><td>TX2 (GPIO17)</td><td>→</td><td>RX0 (GPIO3)</td></tr>
          <tr><td>RX2 (GPIO16)</td><td>←</td><td>TX0 (GPIO1)</td></tr>
          <tr><td>D25</td><td>→</td><td>EN</td></tr>
          <tr class="muted"><td>D26</td><td>→</td><td>GPIO0 / BOOT, facultatif (sans lui : injection USB une fois)</td></tr>
          <tr><td>VIN (5 V)</td><td>—</td><td>VIN (5 V)</td></tr>
          <tr><td>GND</td><td>—</td><td>GND</td></tr>
        </table>
        <div class="muted" style="margin-top:6px">
          Bouton de recherche (D4 ↔ 3V3) et LED de recherche (D15) : sur l'ESP32 Bluetooth. Ne branche pas
          l'ESP32 Bluetooth en USB pendant qu'il est relié.
        </div>
      </div>
      <div v-if="!fw()" class="alert warn small">
        Ce programme de l'EspBar n'est pas encore compilé
        (<code>espbar/{{ variant === 'dual' ? 'firmware-dual.bin' : 'firmware.bin' }}</code>).
      </div>
      <div v-else-if="!serial" class="alert warn small">
        Ce navigateur ne peut pas accéder à l'USB : ouvre Wolfy dans Chrome ou Edge, en https
        (ou sur localhost).
      </div>
      <template v-else>
        <div v-if="target() !== 'bt'" class="row" style="gap:8px;margin-bottom:12px;align-items:center">
          <span class="small" style="white-space:nowrap">Appareil de l'EspBar</span>
          <select v-model="injectClient" style="flex:1;min-width:160px">
            <option value="">— Appareil : inchangé —</option>
            <option v-for="c in data.clients" :key="c.client_id" :value="c.client_id">
              {{ clientLabel(c) }}{{ c.client_ip ? ` (${c.client_ip})` : '' }}
            </option>
          </select>
        </div>
        <div class="row" style="align-items:center;gap:12px">
          <button type="button" class="primary" :disabled="flashing !== null" @click="flash">
            {{ flashing !== null ? `${Math.round(flashing * 100)} %` : '💉 Injecter' }}
          </button>
          <label v-if="fw().merged" class="row" style="gap:10px;align-items:center">
            <span class="switch"><input v-model="eraseAll" type="checkbox" :disabled="flashing !== null" /><span></span></span>
            Effacer toute la mémoire avant (réglages Wi-Fi compris)
          </label>
        </div>
        <div class="muted small" style="margin-top:8px">
          {{ fw().chip || 'puce inconnue' }} · {{ bytes(fw().size) }} ·
          compilé le {{ fw().built_at }} ·
          <span :title="fw().sha256">sha256 {{ fw().sha256.slice(0, 12) }}…</span>
          <template v-if="!fw().merged"> · appli seule (la carte doit déjà avoir un bootloader)</template>
        </div>
        <pre v-if="log" ref="logBox" class="flash-log">{{ log }}</pre>
      </template>
    </div>

  </template>
  <div v-else-if="!error" class="empty"><div class="spinner" style="margin:auto"></div></div>
</template>

<style scoped>
.variants label {
  flex: 1; min-width: 200px; display: flex; flex-direction: column; gap: 2px; cursor: pointer;
  border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px;
}
.variants label.on { border-color: var(--accent); }
.variants input { display: none; }
.wiring { margin-bottom: 12px; padding: 10px; background: var(--card-2); border-radius: 8px; }
.wiring td { padding: 1px 8px 1px 0; }
.board + .board { margin-top: 12px; padding-top: 12px; border-top: 1px solid var(--line); }
.flash-log {
  margin: 12px 0 0; max-height: 260px; overflow: auto; white-space: pre-wrap;
  background: var(--card-2); border: 1px solid var(--line); border-radius: 8px; padding: 10px; font-size: 12px;
}
</style>
